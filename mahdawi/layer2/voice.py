"""
layer2.voice — the store's voice, defined once for every Layer Two task.

Every prompt that produces Arabic starts from system_message(). The register
rules and examples live only here, so a change to the voice is one edit.

Register: Iraqi Arabic, somewhat formal — the polite, clean dialect an Iraqi
shop uses with a customer it respects. Iraqi words and grammar, no street slang,
no Egyptian or Gulf forms, and no stiff Modern Standard phrasing.
"""
from __future__ import annotations

import json
from typing import List

from mahdawi.content import settings as content_settings

STORE_NAME = "مهداوي ستور"

_RULES = """\
You write for {store}, an Iraqi online shop. Tagline: {tagline}.

Language rules, all mandatory:
1. Write in Iraqi Arabic, somewhat formal: polite and clean, the way a respected
   Baghdad shop talks to a customer. Use Iraqi forms such as شلون، شكد، اكو،
   ماكو، هواية، هسه، تكدر، عدنا، راح، خوش.
2. No street slang, no jokes at the customer's expense, no exaggeration.
3. Never use Egyptian forms (ازاي، عايز، كده، اوي) or Gulf forms (وايد، زين
   as "good", شلونك يا الغالي). Never use stiff Modern Standard phrasing
   (يسرنا أن نقدم لكم، نود إعلامكم).
4. Arabic script only. No English words unless they are a product name.
5. Use only the facts given in the FACTS block. Never state a price, a number,
   a size, a material, a guarantee, a discount, or a delivery time that the
   FACTS block does not contain. If a fact is missing, do not mention it.
6. No emoji. No hashtags.

Examples of the register:
- هلا بيك، المنتج متوفر وتكدر تطلبه هسه.
- التوصيل لكل المحافظات والدفع عند الاستلام.
- خوش اختيار للبيت، عملي وسهل الاستعمال.
- {cta}
"""


def system_message() -> dict:
    """Post: the one system message every Arabic-writing prompt starts with."""
    return {"role": "system", "content": _RULES.format(
        store=STORE_NAME, tagline=content_settings.TAGLINE,
        cta=content_settings.ORDER_CTA_DM)}


def facts_block(facts: dict) -> str:
    """
    Pre : facts holds only values code produced or read from Fedshi.
    Post: a labelled block the model is told to treat as its only source.
    """
    clean = {k: v for k, v in facts.items() if v not in (None, "", [], {})}
    return "FACTS:\n" + json.dumps(clean, ensure_ascii=False, indent=1)


def messages(task: str, facts: dict) -> List[dict]:
    """Post: [system voice, user task + FACTS] — the shape every task sends."""
    return [system_message(),
            {"role": "user", "content": task.strip() + "\n\n" + facts_block(facts)}]
