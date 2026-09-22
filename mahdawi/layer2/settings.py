"""
layer2.settings — which Gemini model does which task, overridable by env.

Two model roles. The writer produces customer-facing Arabic; the judge ranks,
checks images, and reads messages, where reasoning depth matters more than
speed. Any 9router model id works; these defaults are the Gemini models 9router
listed on 2026-09-22 and are not yet measured for Iraqi Arabic quality.
"""
import os

# "on": fetch runs send products through Layer Two. "off": the rule-written
# draft is staged, as before this layer existed. An off switch is operator
# state, never an automatic fallback when 9router fails.
ENABLED = os.environ.get("MAHDAWI_LAYER2", "on") == "on"

MODEL_WRITER = os.environ.get("MAHDAWI_MODEL_WRITER", "ag/gemini-3.8-flash-medium")
MODEL_JUDGE = os.environ.get("MAHDAWI_MODEL_JUDGE", "ag/gemini-3.8-flash-high")

TIMEOUT_SECONDS = float(os.environ.get("MAHDAWI_LAYER2_TIMEOUT", "90"))
MAX_TOKENS = int(os.environ.get("MAHDAWI_LAYER2_MAX_TOKENS", "2048"))

# Output limits that code enforces on Layer Two text.
CAPTION_LINE_MAX_CHARS = int(os.environ.get("MAHDAWI_CAPTION_LINE_MAX", "160"))
MARKET_NOTE_MAX_CHARS = int(os.environ.get("MAHDAWI_MARKET_NOTE_MAX", "600"))
REPLY_MAX_CHARS = int(os.environ.get("MAHDAWI_REPLY_MAX", "400"))

# The share of letters that must be Arabic script in customer-facing text.
MIN_ARABIC_SHARE = float(os.environ.get("MAHDAWI_MIN_ARABIC_SHARE", "0.7"))
