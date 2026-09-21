"""Bakhdida requires request evidence, and substitutions use BAEB service facts."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from services.itinerary.day_preferences import bakhdida_requested, preferred_day_codes
from services.itinerary.normalizer import normalize_from_dict
from services.itinerary.pipeline.loader import load_all_templates
from services.itinerary.resolved_plan import resolve_plan
from services.itinerary.sequence_check import check_sequence
from services.itinerary.workspace_sync import workspace_request
from services.itinerary.group_quote import GroupQuoteOptions
from services.itinerary.models import RouteDay, RouteRecord


@pytest.mark.parametrize('notes,expected', [
    ('', False), ('Visit Mosul and Erbil', False), ('Visit Bakhdida', True),
    ('Interested in Qaraqosh', True), ('Visit بخديدا', True),
    ('Skip Bakhdida', False), ('Without Bakhdida', False),
    ('Bakhdida is not needed', False), ('Already visited Bakhdida', False),
    ('No hotels, visit Bakhdida', True),
    ('Visit Bakhdida. Actually, skip Bakhdida.', False),
])
def test_request_mentions_and_exclusions(notes, expected):
    request = normalize_from_dict('queue:test', {'entry_notes': notes})
    assert bakhdida_requested(request) is expected


def test_structured_request_and_code_alias():
    request = normalize_from_dict('queue:test', {'required_cities': ['Bakhdida']})
    assert preferred_day_codes(['MOBKEB'], request) == (['MOBKHEB'], {})
    request = replace(request, raw_record={'special_notes': 'Skip Bakhdida'})
    assert preferred_day_codes(['MOBKHEB'], request)[0] == ['BAEB']


def test_historical_bakhdida_does_not_request_it_and_provenance_is_retained():
    request = normalize_from_dict('queue:test', {'tripDays': 1})
    route = RouteRecord(id='test', source_file='historical.docx', day_count=1,
        tour_type='individual', city_sequence=['Erbil'], themes=[],
        days=[RouteDay(day=1, text='Visit Bakhdida, then drive to Erbil airport for departure.', overnight_city='')])
    rows = load_all_templates()
    codes, overrides = preferred_day_codes(['MOBKHEB'], request)
    plan = resolve_plan(codes, rows, request, route, operator_overrides=overrides)
    assert plan.days[0]['code'] == 'BAEB'
    assert plan.days[0]['overnight_city'] == 'Erbil'
    assert plan.days[0]['evidence']['operator_override']['from_code'] == 'MOBKHEB'
    assert plan.days[0]['evidence']['source_facts']['overnight_status'] == 'none'
    assert not any('historical overnight' in issue for issue in plan.issues)
    # The override does not excuse a conflicting catalogue destination.
    rows['BAEB'] = replace(rows['BAEB'], overnight_city='Baghdad or Erbil')
    broken = resolve_plan(codes, rows, request, route, operator_overrides=overrides)
    assert broken.issues


def test_manual_unrequested_bakhdida_is_blocked():
    rows = load_all_templates()
    request = normalize_from_dict('queue:test', {'tripDays': 1})
    checked = check_sequence(['MOBKHEB'], rows, normalized_request=request)
    assert any(f.kind == 'bakhdida_unrequested' for f in checked.faults)
    requested = replace(request, required_cities=['Bakhdida'])
    checked = check_sequence(['MOBKHEB'], rows, normalized_request=requested)
    assert not any(f.kind == 'bakhdida_unrequested' for f in checked.faults)


def test_saved_workspace_uses_baeb_text_sites_and_night_options():
    draft = SimpleNamespace(draft_id='dr-test', request_id='queue:test', doc_url='',
        request_row={'tripDays': 1}, sequences=[], group_quote_basis={'day_codes': ['MOBKHEB']})
    original = deepcopy(draft.__dict__)
    body = workspace_request(draft, GroupQuoteOptions(omit_final_night=True))
    selected = body['day_templates'][0]
    assert selected['code'] == 'BAEB_DAY_1'
    assert selected['included_sites'] == load_all_templates()['BAEB'].included_sites
    assert 'Bakhdida' not in selected['full_text']
    assert selected['overnight_city'] == 'Erbil'
    assert body['request']['omit_final_night'] is True
    assert body['request']['foc_per_group'] == 1
    assert draft.__dict__ == original
