"""
messaging.settings — every tunable, in one place, overridable by env.
"""
import os

# The message ledger is its own SQLite file beside the post media, so the
# messaging tables need no change to app.db.
DB_PATH = os.environ.get(
    "MAHDAWI_MESSAGES_DB",
    os.path.join(os.environ.get(
        "ODYSSEUS_DATA_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data")), "mahdawi", "messages.db"),
)

# -- gate thresholds ----------------------------------------------------------
DAILY_REPLY_CAP = int(os.environ.get("MAHDAWI_DAILY_REPLY_CAP", "3"))
CONFIDENCE_THRESHOLD = float(os.environ.get("MAHDAWI_REPLY_CONFIDENCE", "0.75"))

# -- private replies to comments (Meta: one per comment, 7 days) ---------------
COMMENT_REPLY_WINDOW_SECONDS = 7 * 24 * 3600

# -- agent override ------------------------------------------------------------
# False = the agent may raise a tier but may never lower one into auto-send.
ALLOW_DOWNWARD_OVERRIDE = os.environ.get("MAHDAWI_DOWNWARD_OVERRIDE") == "1"

# -- automatic send ------------------------------------------------------------
# Off by default. When off, every reply stages for the owner, FAQ included.
# The owner switches it on after reviewing staged FAQ replies.
AUTOSEND = os.environ.get("MAHDAWI_AUTOSEND", "0") == "1"
