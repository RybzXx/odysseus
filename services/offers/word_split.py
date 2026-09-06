"""
services/offers/word_split.py

Put the spaces back into text a PDF reader ran together.

Two readers already tried. pypdf drops every space in some files and PyMuPDF
recovers those, but one document defeats both: it loses spaces irregularly, so
`Meet andGreet andtransfer fromtheairport` survives every re-extraction. That
document supplies two of the approved catalogue rows, and no amount of reading
the attachment again will separate those words.

The lexicon comes from the corpus itself. 1785 stored days kept their spaces,
written by the same people about the same tours, so they hold the place names,
the dishes and the turns of phrase a general word list would not: Qaimer,
mashoof, Ukhaidir, Rawanduz.

Only spaces are inserted. No letter is added, removed or changed, so a repaired
day still says exactly what was sent.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

# A run of letters longer than this is worth splitting. English tops out around
# fifteen letters outside chemistry, and the corpus's own longest real word is
# shorter than that.
MIN_RUN_TO_SPLIT = 9

# No word in a split may be shorter than this unless the lexicon knows it well.
# Without a floor, a greedy split shatters a long run into "a n d t h e".
MIN_PIECE = 2

# A boundary the reader ate mid-word, anchored at a word start so "MondayMar"
# splits at "Monday" and not at "onday".
EATEN_BOUNDARY_RE = re.compile(r"\b([A-Za-z][a-z]+)([A-Z][a-z]{2,})")
LETTER_RUN_RE = re.compile(r"[A-Za-z]{%d,}" % MIN_RUN_TO_SPLIT)
WORD_RE = re.compile(r"[A-Za-z']+")

_lexicon: Optional[dict] = None


def build_lexicon(texts) -> dict:
    """
    Post: {lowercase word: log probability}, from text that kept its spaces.

    Pre:  `texts` are day texts. A text that lost its own spaces must not be
          here: it would teach the lexicon the run-together forms this module
          exists to undo.
    """
    counts = Counter()
    for text in texts:
        counts.update(w.lower() for w in WORD_RE.findall(text or "") if len(w) > 1)
    total = sum(counts.values()) or 1
    return {word: math.log(n / total) for word, n in counts.items()}


def corpus_lexicon(refresh: bool = False) -> dict:
    """
    Post: the lexicon built from every stored day that kept its spaces.

    Cached: the corpus is 2449 days and the lexicon does not change inside one
    pass over it.
    """
    global _lexicon
    if _lexicon is not None and not refresh:
        return _lexicon
    from services.offers.offer_store import iter_offers
    from services.offers.offer_text import looks_unspaced

    _lexicon = build_lexicon(
        day.text for offer in iter_offers() for day in offer.days
        if (day.text or "").strip() and not looks_unspaced(day.text)
    )
    return _lexicon


def split_run(run: str, lexicon: dict) -> str:
    """
    Split one run of letters into the likeliest sequence of known words.

    Pre:  `run` holds letters only.
    Post: the same letters, with spaces between them. A run the lexicon cannot
          explain comes back unchanged, because a bad split is worse than none.

    Viterbi over every prefix, scoring a word by its log probability and an
    unknown piece by a penalty that grows with its length. The penalty is what
    stops the split from inventing short nonsense words to reach the end.
    """
    if not run or len(run) < MIN_RUN_TO_SPLIT:
        return run
    lowered = run.lower()
    n = len(lowered)
    unknown = min(lexicon.values()) - 6 if lexicon else -30.0

    best = [0.0] + [-math.inf] * n
    back = [0] * (n + 1)
    for end in range(1, n + 1):
        for start in range(max(0, end - 24), end):
            piece = lowered[start:end]
            if len(piece) < MIN_PIECE and piece not in ("a", "i"):
                continue
            score = lexicon.get(piece)
            if score is None:
                score = unknown * len(piece)
            total = best[start] + score
            if total > best[end]:
                best[end], back[end] = total, start

    if best[n] == -math.inf:
        return run

    pieces, end = [], n
    while end > 0:
        start = back[end]
        pieces.append(run[start:end])
        end = start
    pieces.reverse()

    # A split that leaves a piece the lexicon does not know is a guess, and a
    # guess here would put invented words into the catalogue. Keep the run.
    if any(p.lower() not in lexicon for p in pieces):
        return run
    return " ".join(pieces)


def respace(text: str, lexicon: Optional[dict] = None) -> str:
    """
    Put the spaces back into one day's text.

    Pre:  `text` is a stored day. `lexicon` is built from spaced days, or None
          to use the corpus.
    Post: the same characters in the same order, with spaces inserted. No
          letter is added, removed or changed.

    Blame: a run that cannot be explained is left alone. Reporting a day as
    unrepaired is honest; splitting it wrongly puts invented words into a
    catalogue row a client will read.
    """
    if not (text or "").strip():
        return text
    lexicon = corpus_lexicon() if lexicon is None else lexicon

    # A boundary the reader ate mid-word is unambiguous: the capital says where
    # the second word starts. Do those first, so the runs left over are shorter.
    text = EATEN_BOUNDARY_RE.sub(
        lambda m: f"{m.group(1)} {m.group(2)}"
        if m.group(1).lower() in lexicon and m.group(2).lower() in lexicon
        else m.group(0),
        text)

    return LETTER_RUN_RE.sub(lambda m: split_run(m.group(0), lexicon), text)


def letters_of(text: str) -> str:
    """Post: every letter, in order, with nothing else. The repair invariant."""
    return "".join(c for c in (text or "") if c.isalpha())
