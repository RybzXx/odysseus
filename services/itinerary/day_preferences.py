"""Operator routing preferences. Historical text cannot request a destination."""
import re

_BAKHDIDA = re.compile(r'\b(?:bakhdida|baghdida|qaraqosh|karakosh|bakhdeda)\b|بخديدا|قره\s?قوش', re.I)
_NEGATIVE = re.compile(r"\b(?:no|not|without|skip|exclude|avoid|except|don't|dont|already visited)\b|بدون|لا\s", re.I)
_FIELDS = ('required_cities', 'required_sites', 'additionalInterests', 'additional_interests',
           'entry_notes', 'comments', 'special_notes', 'requested_places')


def bakhdida_requested(request):
    """Require a positive place mention in request fields, never route evidence."""
    values = list(getattr(request, 'required_cities', []) or [])
    raw = getattr(request, 'raw_record', {}) or {}
    for key in _FIELDS:
        value = raw.get(key)
        values.extend(value if isinstance(value, list) else [value] if isinstance(value, str) else [])
    positive, negative = False, False
    for value in values:
        if not isinstance(value, str):
            continue
        for clause in re.split(r'[.,;!?\n]|\bbut\b', value, flags=re.I):
            if _BAKHDIDA.search(clause):
                if _NEGATIVE.search(clause):
                    negative = True
                else:
                    positive = True
    return positive and not negative


def preferred_day_codes(codes, request):
    """Use BAEB unless the customer asks for the Bakhdida excursion."""
    selected, overrides = list(codes), {}
    if bakhdida_requested(request):
        return ['MOBKHEB' if code == 'MOBKEB' else code for code in selected], overrides
    for index, code in enumerate(selected):
        if code in ('MOBKHEB', 'MOBKEB'):
            selected[index] = 'BAEB'
            overrides[index + 1] = {'rule': 'BAEB by default; Bakhdida only when requested', 'from_code': code, 'to_code': 'BAEB'}
    return selected, overrides
