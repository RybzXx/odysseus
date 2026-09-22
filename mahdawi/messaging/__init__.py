"""
mahdawi.messaging — customer DMs and comments, read and answered.

Copied from the FedshiProject engine's socialsrv (the reference copy) and
changed in one place: Gemini writes every reply (layer2.replies), and a code
check on the reply (reply_check) replaces the old template byte-match as the
condition for an automatic send.

Layer split, per item:
    ingest -> gate -> classify (L2) -> tier -> write (L2) -> dispatch -> audit
Code owns the gate, the tier, the reply check, and the send decision. Gemini
owns reading the message and writing the reply. No send call exists outside
mahdawi.messaging.dispatch.
"""
