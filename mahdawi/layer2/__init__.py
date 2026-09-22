"""
mahdawi.layer2 — Layer Two: every judgement and every customer-facing word,
written by Gemini through the 9router gateway.

The pipeline has two layers, and each action belongs to exactly one:

  Layer One (code)   facts and rules: fetch, price, gates, file checks, tiers,
                     the send decision, and the check on every Layer Two output.
  Layer Two (9router) language and judgement: market notes, product ranking,
                     image judgement, caption lines, message reading, replies.

Invariants every module here keeps:
  * Layer Two never invents a fact. Prompts carry the facts code supplied, and
    a code check rejects output that states anything else (a price, a number).
  * Every call either returns output that passed its code check, or raises
    Layer2Failure. There is no fallback to rule-written text: the step stops
    and its item waits (see services.mahdawi, STATUS_WAITING_LAYER2).
"""
