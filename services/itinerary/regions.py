"""
services/itinerary/regions.py

The four regions, the words a customer writes for each, and the city each holds.

One module, because three others answered the same question differently. The
normalizer folded eight intake labels onto three names, the matcher held its own
city map, and the binder read whichever of the two answered first. A request for
"Western Iraq & Nineveh Plains" therefore became "Northern Iraq", matched a
Kurdistan route, and its coverage read 1.00 (ws-03 phase seven, D60).

The names are the intake form's own words. A label and a region are now the same
string, so `REGION_NAME_MAP` is close to an identity map and a new label on the
form is one line here.

Nothing in this module decides a template's region. `region_of_template` does,
and it reads the template's own field first, because a day's region is a
judgement the owner made and not a lookup (D61).
"""
from __future__ import annotations

from typing import Optional

# The four the intake form offers, spelled as it spells them.
REGION_KURDISTAN = "Iraqi Kurdistan"
REGION_WEST_NINEVEH = "Western Iraq & Nineveh Plains"
REGION_CENTRAL = "Central Iraq & Middle Euphrates"
REGION_SOUTH = "Southern Iraq"

REGIONS = (REGION_KURDISTAN, REGION_WEST_NINEVEH, REGION_CENTRAL, REGION_SOUTH)

# What a request answers when it named no region at all.
#
# It is a guess, and `NormalizedRequest.defaulted_fields` is what says so. A
# caller that reports coverage against this without reading that list reports a
# confidence nobody earned (D65).
REGION_WHEN_UNSTATED = REGION_CENTRAL

# Every spelling seen on the live Curated and Queue records, plus the shorter
# forms a person types. A key is lower case; a value is one of REGIONS.
REGION_NAME_MAP = {
    # Central Iraq & Middle Euphrates
    "central iraq & middle euphrates": REGION_CENTRAL,
    "central iraq and middle euphrates": REGION_CENTRAL,
    "center & middle euphrates": REGION_CENTRAL,
    "central iraq": REGION_CENTRAL,
    "central": REGION_CENTRAL,
    "middle euphrates": REGION_CENTRAL,
    # Southern Iraq
    "southern iraq": REGION_SOUTH,
    "southern": REGION_SOUTH,
    "south": REGION_SOUTH,
    "south of iraq": REGION_SOUTH,
    # Iraqi Kurdistan
    "iraqi kurdistan": REGION_KURDISTAN,
    "kurdistan": REGION_KURDISTAN,
    "northern iraq / kurdistan": REGION_KURDISTAN,
    "northern iraq": REGION_KURDISTAN,
    "north of iraq": REGION_KURDISTAN,
    # Western Iraq & Nineveh Plains
    "western iraq & nineveh plains": REGION_WEST_NINEVEH,
    "western iraq and nineveh plains": REGION_WEST_NINEVEH,
    "west & nineveh plains": REGION_WEST_NINEVEH,
    "western iraq": REGION_WEST_NINEVEH,
    "west of iraq": REGION_WEST_NINEVEH,
    "nineveh plains": REGION_WEST_NINEVEH,
    "nineveh": REGION_WEST_NINEVEH,
}

# The city a day sleeps in, or a customer names, and the region it sits in.
#
# Keys are lower case. `binder._normalize_city_name` and `matcher` both lower
# case before they read, and `move_map.place_key` resolves the spellings the
# sold routes carry.
CITY_REGION_MAP = {
    # Central Iraq & Middle Euphrates
    "baghdad": REGION_CENTRAL,
    "samarra": REGION_CENTRAL,
    "babylon": REGION_CENTRAL,
    "karbala": REGION_CENTRAL,
    "najaf": REGION_CENTRAL,
    "kufa": REGION_CENTRAL,
    "salman pak": REGION_CENTRAL,
    "al kifl": REGION_CENTRAL,         # Ezekiel's shrine, between Najaf and Babylon
    # Southern Iraq
    "nasiriyah": REGION_SOUTH,
    "ur": REGION_SOUTH,
    "uruk": REGION_SOUTH,
    "eridu": REGION_SOUTH,
    "samawa": REGION_SOUTH,
    "chibayish": REGION_SOUTH,
    "marshes": REGION_SOUTH,
    "qurna": REGION_SOUTH,
    "basra": REGION_SOUTH,
    "zubair": REGION_SOUTH,
    # Western Iraq & Nineveh Plains
    "mosul": REGION_WEST_NINEVEH,
    "nineveh": REGION_WEST_NINEVEH,
    "bakhdida": REGION_WEST_NINEVEH,
    "bashiqa": REGION_WEST_NINEVEH,
    "alqosh": REGION_WEST_NINEVEH,
    "al qosh": REGION_WEST_NINEVEH,
    "lalish": REGION_WEST_NINEVEH,
    "nimrud": REGION_WEST_NINEVEH,
    "jerwan": REGION_WEST_NINEVEH,
    "ashur": REGION_WEST_NINEVEH,
    "salahdin": REGION_WEST_NINEVEH,   # how the ticket index spells Ashur's town
    "khinnis": REGION_WEST_NINEVEH,    # the Bavian reliefs, beside Jerwan
    "hatra": REGION_WEST_NINEVEH,
    "fallujah": REGION_WEST_NINEVEH,
    # Iraqi Kurdistan
    "erbil": REGION_KURDISTAN,
    "sulaymaniyah": REGION_KURDISTAN,
    "duhok": REGION_KURDISTAN,
    "zakho": REGION_KURDISTAN,
    "akre": REGION_KURDISTAN,
    "amedi": REGION_KURDISTAN,
    "amadiya": REGION_KURDISTAN,
    "barzan": REGION_KURDISTAN,
    "soran": REGION_KURDISTAN,
    "rawanduz": REGION_KURDISTAN,
    "korek mountain": REGION_KURDISTAN,
    "koya": REGION_KURDISTAN,
    "halabja": REGION_KURDISTAN,
    "choman": REGION_KURDISTAN,
    "rezan": REGION_KURDISTAN,
    "shush village": REGION_KURDISTAN,
}

# The templates whose region is not the region of the city they sleep in.
#
# Each one works in one region and takes its hotel in another, so the plain rule
# answers wrongly for it and the owner set it by hand on 2026-09-08 (D61).
#
# The list is here rather than in the template files so a reader can see all
# seven at once. `region_of_template` applies it, and the template files carry
# the same value, so a caller that reads the file alone is not misled.
REGION_EXCEPTIONS = {
    "SAFA": REGION_WEST_NINEVEH,      # Fallujah and Aqar Quf; sleeps in Baghdad
    "BGFA": REGION_WEST_NINEVEH,      # the same day without Samarra
    "MO1EB": REGION_WEST_NINEVEH,     # the region's only exit; sleeps in Erbil
    "NA2BG": REGION_SOUTH,            # the Ahwar marshes; sleeps in Baghdad
    "NAURUKNJ": REGION_SOUTH,         # Ur and Uruk; sleeps in Najaf
    "URNJ": REGION_SOUTH,             # Ur; sleeps in Najaf
    "UrukNJ": REGION_SOUTH,           # Uruk; sleeps in Najaf
}

# A template that carries no overnight city takes the region of the city it ends
# in, because that is where its customer is when the day closes (D62).
#
# `BB` ends nowhere the catalogue names: Babylon is reached from Baghdad and from
# Karbala alike, and both are Central, so the answer is the same either way.
REGION_WHEN_NO_OVERNIGHT = {
    "BANA": REGION_SOUTH,             # ends in Nasiriyah
    "MOBKHEB": REGION_KURDISTAN,      # ends in Erbil
    "SUEBDEP": REGION_KURDISTAN,      # ends in Erbil
    "BB": REGION_CENTRAL,             # Babylon, reached from either side
}


def region_of_city(city: str, default: Optional[str] = None) -> str:
    """
    Post: the region a city sits in, or `default` when the map has no word for
          it. `default` is None by default, so a caller must decide what an
          unknown city means rather than inherit a guess.

    Pre:  `city` is a place name in any case and any of the map's spellings.
    """
    return CITY_REGION_MAP.get((city or "").strip().lower(), default)


def region_of_template(code: str, template=None) -> Optional[str]:
    """
    Post: the region one template belongs to, or None when nothing can say.

    Pre:  `code` is the template's code. `template` is its row, as a dict or a
          DayTemplate, or None when the caller holds only the code.

    Inv:  an exception wins over every other source, and the template's own
          `region` field wins over its overnight city. The owner's judgement is
          what this answers; the city is only the fallback (D61).

    Blame: a template whose file carries a region the exception list contradicts
    is a data error. This returns the exception, because the list is the record
    of the decision and the file is a copy of it.
    """
    if code in REGION_EXCEPTIONS:
        return REGION_EXCEPTIONS[code]

    stated = ""
    if template is not None:
        stated = (template.get("region") if isinstance(template, dict)
                  else getattr(template, "region", "")) or ""
        stated = str(stated).strip()
    if stated in REGIONS:
        return stated

    overnight = ""
    if template is not None:
        overnight = (template.get("overnight_city") if isinstance(template, dict)
                     else getattr(template, "overnight_city", "")) or ""
    by_city = region_of_city(str(overnight).strip())
    if by_city:
        return by_city
    return REGION_WHEN_NO_OVERNIGHT.get(code)


def normalize_region_label(label: str) -> str:
    """
    Post: the region a customer's words name, or the words unchanged when the
          map has none.

    Pre:  `label` is one region, already split out of a comma-separated cell.

    Blame: an unchanged answer is not a region. `unmapped_regions` finds it and
    the caller records a warning, because a silent pass-through matched no route
    and read as a weak match rather than a label nobody taught the catalogue.
    """
    text = (label or "").strip()
    return REGION_NAME_MAP.get(text.lower(), text)
