"""Queue integration keeps guest counts, errors, and saved plans explicit."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from services.itinerary import creation_worker as worker
from services.itinerary.drafts import ItineraryDraft
from services.itinerary.models import NormalizedRequest


@pytest.fixture
def prepared(monkeypatch):
    draft = ItineraryDraft('dr-123456789abc', {}, request_id='manual:test')
    request = NormalizedRequest('manual:test', 'curated', 'Test', pax=2, day_count=1)
    check = NS(faults=[], unknown_codes=[], untested=[])
    candidate = NS(day_codes=['BG1'], check=check, plan=NS(issues=[], to_dict=lambda: {}), statement='Matched route')
    monkeypatch.setattr(worker, 'normalize_from_dict', lambda *a, **k: request)
    monkeypatch.setattr(worker, 'open_draft', lambda *a, **k: draft)
    monkeypatch.setattr(worker, 'active_day_templates', lambda: {})
    monkeypatch.setattr(worker, 'build_candidates', lambda *a, **k: NS(candidates=[candidate]))
    monkeypatch.setattr(worker, 'add_sequence', lambda *a, **k: draft)
    monkeypatch.setattr(worker, 'workspace_request', lambda *a: {
        'request': {'start_date': None, 'group_sizes': [(8, 9)], 'foc_per_group': 1},
        'day_templates': [{'code': 'BG1', 'title': 'Baghdad', 'full_text': 'Visit', 'overnight_city': 'Baghdad'}]})
    return draft, request, check


def test_individual_uses_actual_pax_and_rooms(prepared):
    body, result = worker.prepare_job({'source_key': 'manual:test', 'request_data': {}})
    assert body['request']['num_people'] == 2
    assert body['request']['double_rooms'] == 1
    assert body['request']['foc_per_group'] == 0
    assert body['request']['selected_vehicle'] == 'SMALL_CAR'
    assert any('Dates' in c for c in result['checks'])


@pytest.mark.parametrize('paying,foc,vehicle', [(12,1,'TOYOTA_COASTER'), (13,1,'VIP_BUS'), (3,0,'LARGE_CAR'), (6,0,'TOYOTA_COASTER')])
def test_paying_guests_exclude_foc_and_transport_fits(prepared, paying, foc, vehicle):
    prepared[1].pax = paying
    body, _ = worker.prepare_job({'source_key': 'manual:test', 'request_data': {'foc_per_group': foc}})
    assert body['request']['group_sizes'] == [(paying, paying)]
    assert body['request']['foc_per_group'] == foc
    assert body['request']['selected_vehicle'] == vehicle


def test_saved_operations_basis_keeps_group_bands(prepared):
    prepared[0].group_quote_basis = {'day_codes': ['BG1']}
    body, _ = worker.prepare_job({'source_key': 'manual:test', 'request_data': {}})
    assert body['request']['group_sizes'] == [(8, 9)]
    assert body['request']['foc_per_group'] == 1


@pytest.mark.parametrize('cause', ['fault', 'missing_pax', 'length', 'plan'])
def test_invalid_route_is_visible_but_unpriced(prepared, cause):
    if cause == 'fault': prepared[2].faults = [NS(statement='Wrong arrival city')]
    elif cause == 'missing_pax': prepared[1].defaulted_fields = ['pax']
    elif cause == 'length': prepared[1].day_count = 4
    else: prepared[1].parse_warnings = ['Unknown region']
    body, result = worker.prepare_job({'source_key': 'manual:test', 'request_data': {}})
    assert body is None
    assert result['days'] and result['checks']


def test_failed_pricing_returns_retryable_result(monkeypatch):
    from src import ops_hub
    post = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(ops_hub, '_post', post)
    monkeypatch.setattr(worker, 'prepare_job', lambda j: ({'request': {}}, {'days': [], 'checks': []}))
    monkeypatch.delenv('NEWOPS_API_TOKEN', raising=False)
    asyncio.run(worker.process_job({'id': 'job', 'lease_token': 'claim'}))
    sent = post.call_args.args[1]
    assert sent['status'] == 'failed'
    assert sent['lease_token'] == 'claim'
    assert sent['quote'] is None


def test_completed_result_uses_priced_final_night_variant(monkeypatch):
    from src import ops_hub
    post = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(ops_hub, '_post', post)
    monkeypatch.setenv('NEWOPS_API_TOKEN', 'test-token')
    monkeypatch.setenv('NEWOPS_API_URL', 'https://pricing.example')
    day = {'number': 1, 'code': 'BG1', 'title': 'Baghdad', 'text': 'Visit', 'overnight': ''}
    payload = {'active_variant': 'without_final_night', 'variants': [{'key': 'without_final_night', 'days': [day]}]}
    monkeypatch.setattr(worker, 'prepare_job', lambda j: ({'request': {'start_date': '2027-03-26'}}, {'days': [], 'checks': []}))
    client = AsyncMock()
    client.post.return_value = NS(status_code=200, json=lambda: payload)
    context = AsyncMock(); context.__aenter__.return_value = client
    monkeypatch.setattr(worker.httpx, 'AsyncClient', lambda **k: context)
    asyncio.run(worker.process_job({'id': 'job', 'lease_token': 'claim'}))
    result = post.call_args.args[1]
    assert result['status'] == 'ready'
    assert result['result']['days'] == [day]
    assert result['result']['days'][-1]['overnight'] == ''
