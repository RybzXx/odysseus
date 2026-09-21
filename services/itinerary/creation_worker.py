"""Consume durable website requests without models or customer messaging."""
import asyncio
import logging
import os

import httpx

from services.itinerary.candidates import build_candidates
from services.itinerary.drafts import open_draft, add_sequence, ProposedSequence, SOURCE_RULES
from services.itinerary.group_quote import GroupQuoteOptions
from services.itinerary.normalizer import normalize_from_dict, request_kind
from services.itinerary.propose_sequence import active_day_templates
from services.itinerary.resolved_plan import resolve_plan
from services.itinerary.sequence_check import check_sequence
from services.itinerary.workspace_sync import workspace_request

logger = logging.getLogger(__name__)


def prepare_job(job):
    """Save a route draft. Price only complete routes with known guest counts."""
    key, row = job['source_key'], job['request_data']
    request = normalize_from_dict(key, row, source=request_kind(key))
    draft = open_draft(row, request_id=key)
    checks = []
    blocked = False
    if not draft.group_quote_basis:
        templates = active_day_templates()
        staff_codes = row.get('_staff_route_codes')
        if staff_codes is not None:
            if (not isinstance(staff_codes, list) or len(staff_codes) != request.day_count
                    or any(not isinstance(code, str) or code not in templates for code in staff_codes)):
                return None, {'days': [], 'checks': ['The saved team route is incomplete or uses an inactive code. Edit the route again.']}
            day_codes = list(staff_codes)
            plan = resolve_plan(day_codes, templates, request)
            check = check_sequence(day_codes, templates, start_date=request.start_date,
                                   normalized_request=request, plan=plan)
            statement = 'Team-selected route'
        else:
            found = build_candidates(request, templates, ceiling=1)
            if not found.candidates:
                return None, {'days': [], 'checks': found.untested or ['No matching route is available.']}
            candidate = found.candidates[0]
            day_codes, plan, check, statement = candidate.day_codes, candidate.plan, candidate.check, candidate.statement
        checks = [fault.statement for fault in check.faults]
        checks += list(check.untested) + list(request.parse_warnings)
        checks += [flag.statement for flag in check.flags]
        checks += list(plan.issues)
        for day in plan.days:
            if day.get('evidence', {}).get('operator_override'):
                checks.append(f"Day {day['number']}: uses BAEB. Bakhdida was not requested.")
        blocked = bool(check.faults or check.unknown_codes or check.untested or plan.issues or request.parse_warnings)
        if len(day_codes) != request.day_count:
            checks.append(f'The draft has {len(day_codes)} days. The request needs {request.day_count}.')
            blocked = True
        for field in ('pax', 'day_count'):
            if request.was_defaulted(field):
                checks.append(f'Confirm the missing {field.replace("_", " ")} before pricing.')
                blocked = True
        sequence = ProposedSequence(source=SOURCE_RULES, day_codes=day_codes,
                                    note=statement, plan=plan.to_dict())
        if not draft.sequences or draft.sequences[-1].plan != sequence.plan:
            draft = add_sequence(draft.draft_id, sequence)
        # Use the queued source snapshot for this calculation. Preserve saved history.
        draft.request_row = row
    else:
        checks.append('Uses the saved operations plan and its approved group pricing basis.')
    body = workspace_request(draft, GroupQuoteOptions(**draft.group_quote_options))
    days = [{'number': n, 'code': day['code'], 'title': day['title'],
             'text': day['full_text'], 'overnight': day['overnight_city'] or ''}
            for n, day in enumerate(body['day_templates'], 1)]
    if not draft.group_quote_basis:
        foc = row.get('foc_per_group', 0)
        if isinstance(foc, bool) or not isinstance(foc, int) or not 0 <= foc <= 10:
            checks.append('Confirm the number of FOC guests.'); blocked = True; foc = 0
        pax = request.pax
        total = pax + foc
        group = request.tour_type == 'group' or pax >= 10 or foc > 0
        vehicle = 'SMALL_CAR' if total <= 2 else 'LARGE_CAR' if total == 3 else 'TOYOTA_COASTER' if total <= 13 else 'VIP_BUS'
        if total > 40:
            checks.append('More than 40 travellers require a confirmed vehicle arrangement.')
            blocked = True
        body['request'].update(tour_type='group' if group else 'individual', num_people=pax,
            single_rooms=pax % 2, double_rooms=pax // 2, selected_vehicle=vehicle,
            group_sizes=[(pax, pax)], foc_per_group=foc, group_vehicle='TOYOTA_COASTER' if total <= 13 else 'VIP_BUS',
            compare_group_vehicles=group)
    if not body['request']['start_date']:
        checks.append('Dates are not confirmed. Site opening days require review.')
    result = {'draft_id': draft.draft_id, 'days': days, 'checks': list(dict.fromkeys(checks))[:100]}
    return None if blocked else body, result


async def process_job(job):
    from src.ops_hub import _post
    result = {'days': [], 'checks': []}
    quote = None
    status, summary = 'failed', 'The itinerary could not be created. Retry after checking the itinerary service.'
    try:
        body, result = await asyncio.to_thread(prepare_job, job)
        if body is None:
            status, summary = 'needs_review', 'The route draft is saved. Resolve the listed requirements before pricing.'
        else:
            base, token = os.environ.get('NEWOPS_API_URL', '').rstrip('/'), os.environ.get('NEWOPS_API_TOKEN', '')
            if not base or not token:
                raise ValueError('Pricing connection is not configured.')
            async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
                response = await client.post(base + '/api/operations/quote', json=body,
                                             headers={'Authorization': f'Bearer {token}'})
            if response.status_code == 200:
                quote = response.json()
                quote['warnings'] = list(dict.fromkeys(quote.get('warnings', []) + result['checks']))[:200]
                active = next(v for v in quote['variants'] if v['key'] == quote['active_variant'])
                result['days'] = [{key: day[key] for key in ('number', 'code', 'title', 'text', 'overnight')}
                                  for day in active['days']]
                status = 'needs_review' if not body['request']['start_date'] else 'ready'
                summary = 'The itinerary and prices are ready for team review.'
            else:
                summary = 'The route is saved, but New Operations could not price it. Check rates and service availability, then retry.'
    except Exception as exc:
        # Do not log customer records, credentials, or remote response bodies.
        logger.warning('Itinerary creation failed (%s)', type(exc).__name__)
    return await _post(f"/api/agent/ops/itinerary-jobs/{job['id']}/result",
        {'lease_token': job['lease_token'], 'status': status, 'summary': summary, 'result': result, 'quote': quote})


async def creation_loop():
    """One leased job at a time. An interrupted job becomes available again."""
    from src.ops_hub import _post
    while True:
        try:
            response = await _post('/api/agent/ops/itinerary-jobs', {})
            jobs = response.get('body', {}).get('jobs', []) if response.get('ok') else []
            for job in jobs:
                await process_job(job)
            await asyncio.sleep(2 if jobs else 30)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Itinerary queue unavailable (%s)', type(exc).__name__)
            await asyncio.sleep(30)
