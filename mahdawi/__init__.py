"""
mahdawi — the Platforms module: Fedshi products -> priced, captioned posts,
staged for approval and packaged for manual posting to Instagram and TikTok.

`mahdawi.fedshi` and `mahdawi.content` are the vendored stateless engines
(extraction, pricing, caption, media, selection). State and the dashboard live
on the Odysseus host: the MahdawiPost model (core.database), services/mahdawi.py,
and routes/mahdawi/. No Supabase; nothing posts without a human.
"""
