#!/usr/bin/env python3
"""capture_briefing_fixture.py

Capture the live phone's briefing stores and write a pseudonymised fixture.

The Overview and Organisers modules read four stores that are empty in every
local worktree: the email urgency state file, ``email_message_index``,
``email_summaries``, and the organiser/memory tables. With all four empty, the
faults in those modules are invisible locally -- which is why a duplicated
summary shipped and stayed. This script reads the live instance over SSH and
writes a fixture that keeps the *shape* of that data while carrying none of its
content, so ``seed_briefing_fixture.py`` can reproduce the live conditions on a
developer machine.

Shape is the point. A hand-written fixture would naturally give every message a
``snippet``, and the composition bug at overview_routes.py:146 only appears when
``snippet`` is absent -- which it is on 100% of live rows. The capture therefore
preserves field *presence* exactly, and replaces only field *content*.

Pre:  the phone is reachable via phone_connection (Tailscale SSH), and the
      remote data directory exists. Read-only on the remote side: this opens
      SQLite connections and a JSON file, and writes nothing.
Post: --out holds a JSON fixture in which no real name, address, phone number,
      subject, summary text or message-id survives, and every field that was
      present remains present.
Inv:  pseudonymisation is a consistent, deterministic bijection applied across
      every store. A sender rewritten in the email index is rewritten to the
      same alias in the urgency state and in any organiser rule that names it,
      so organiser matching over the fixture behaves as it does over live data.
      Break that and the fixture stops representing the system it stands in for.

Usage:
    python scripts/capture_briefing_fixture.py
    python scripts/capture_briefing_fixture.py --out tests/fixtures/briefing_shape.json
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
import sys
from email.utils import formataddr, getaddresses
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKSPACE_ROOT = _REPO_ROOT.parent

DEFAULT_OUT = _REPO_ROOT / "tests" / "fixtures" / "briefing_shape.json"
REMOTE_DATA_DIR = "/data/data/com.termux/files/home/odysseus-data"

# Reserved by RFC 2606 / RFC 6761 — guaranteed never to resolve, so a fixture
# address can never be mailed even by accident.
ALIAS_DOMAIN = "example.invalid"


# ─────────────────────────── remote read ───────────────────────────

_REMOTE_DUMP = '''
import base64, gzip, json, os, sqlite3, sys

D = {data_dir!r}
out = {{}}

# 1. Urgency state files — one per owner slug.
states = {{}}
for name in sorted(os.listdir(D)):
    if name.startswith("email_urgency_state_") and name.endswith(".json"):
        try:
            with open(os.path.join(D, name), encoding="utf-8") as fh:
                states[name] = json.load(fh)
        except Exception as exc:
            states[name] = {{"__error__": str(exc)}}
out["urgency_states"] = states

def rows(db_name, table, limit=None):
    path = os.path.join(D, db_name)
    if not os.path.exists(path):
        return {{"columns": [], "rows": []}}
    conn = sqlite3.connect(path)
    try:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(%s)" % table)]
        if not cols:
            return {{"columns": [], "rows": []}}
        sql = "SELECT * FROM %s" % table
        if limit:
            sql += " LIMIT %d" % limit
        return {{"columns": cols, "rows": [list(r) for r in conn.execute(sql)]}}
    except Exception as exc:
        return {{"columns": [], "rows": [], "__error__": str(exc)}}
    finally:
        conn.close()

out["email_message_index"] = rows("scheduled_emails.db", "email_message_index")
out["email_summaries"] = rows("scheduled_emails.db", "email_summaries")
out["work_organisers"] = rows("app.db", "work_organisers")

try:
    with open(os.path.join(D, "memory.json"), encoding="utf-8") as fh:
        out["memories"] = json.load(fh)
except Exception:
    out["memories"] = []

blob = gzip.compress(json.dumps(out).encode("utf-8"))
sys.stdout.write("<<<FIXTURE>>>" + base64.b64encode(blob).decode("ascii"))
'''


def _fetch_remote(data_dir: str) -> Dict[str, Any]:
    """Run the dump on the phone and return its decoded payload.

    Pre:  paramiko importable and the host reachable.
    Post: returns the parsed dump. Raises RuntimeError with the remote stderr
          if the sentinel never arrives, rather than returning a partial dict.
    """
    sys.path.insert(0, str(_WORKSPACE_ROOT))
    try:
        import paramiko
        from phone_connection import HOST, PASSWORD, PORT, USER
    except ImportError as exc:
        raise RuntimeError(
            f"cannot reach the phone: {exc}. Install paramiko, and run from a "
            f"checkout beside phone_connection.py ({_WORKSPACE_ROOT})."
        ) from exc

    source = _REMOTE_DUMP.format(data_dir=data_dir)
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    # Ship the dump base64-encoded so no quoting of the remote source is needed.
    command = (
        "python3 -c \"exec(__import__('base64')"
        f".b64decode('{encoded}').decode('utf-8'))\""
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=20)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=180)
        payload = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
    finally:
        client.close()

    marker = "<<<FIXTURE>>>"
    if marker not in payload:
        raise RuntimeError(f"remote dump produced no payload. stderr:\n{err.strip()}")

    blob = payload.split(marker, 1)[1].strip()
    return json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))


# ─────────────────────────── pseudonymiser ───────────────────────────

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+|00)?\d[\d\s().-]{7,}\d(?!\w)")

# Words a subject may keep: they come from the user's own organiser rules, are
# not personal data, and preserving them keeps rule-to-subject matching in the
# fixture behaving as it does live.
_SUBJECT_FILLER = [
    "quarterly", "update", "notice", "request", "confirmation", "schedule",
    "review", "summary", "reminder", "statement", "enquiry", "report",
]


class Pseudonymiser:
    """Deterministic alias assignment, stable across every store in one run.

    Pre:  none.
    Post: repeated calls with the same input return the same alias; distinct
          inputs never collide within a category.
    Inv:  the maps are the single source of truth for every rewrite, so a name
          seen first in the email index and later in an organiser rule resolves
          to one alias. Callers must never mint an alias by another route.
    """

    def __init__(self) -> None:
        self.people: Dict[str, str] = {}
        self.addresses: Dict[str, str] = {}
        self.domains: Dict[str, str] = {}
        self.keep_words: set[str] = set()

    # -- people & addresses --

    def person(self, name: str | None) -> str:
        """Alias a display name, including the ``Name <addr>`` form.

        Pre:  name is a display name or a full address header, or empty.
        Post: the result contains neither the original name nor the original
              address. Sender fields carry both forms in practice, so treating
              this as a plain name would pass an address straight through.
        """
        if not name or not str(name).strip():
            return ""
        key = str(name).strip()
        if "@" in key or "<" in key:
            return self.address_list(key)
        if key not in self.people:
            self.people[key] = f"Contact {len(self.people) + 1:02d}"
        return self.people[key]

    def address(self, addr: str | None) -> str:
        if not addr or "@" not in str(addr):
            return ""
        key = str(addr).strip().lower()
        if key not in self.addresses:
            local = f"contact{len(self.addresses) + 1:02d}"
            self.addresses[key] = f"{local}@{self.domain(key.split('@', 1)[1])}"
        return self.addresses[key]

    def domain(self, dom: str | None) -> str:
        if not dom:
            return ALIAS_DOMAIN
        key = str(dom).strip().lower().lstrip("@")
        if key not in self.domains:
            self.domains[key] = f"org{len(self.domains) + 1:02d}.{ALIAS_DOMAIN}"
        return self.domains[key]

    def address_list(self, text: str | None) -> str:
        """Rewrite a To/Cc header, aliasing display names as well as addresses.

        Post: no display name survives. Substituting only the address part
              leaves ``Real Name <alias@example.invalid>``, which is still a
              real person -- the header has to be parsed, not pattern-replaced.
        """
        if not text:
            return ""
        raw = str(text)
        parsed = [(n, a) for n, a in getaddresses([raw]) if n or a]
        if not parsed:
            # Unparseable header: alias any address, then drop everything else
            # rather than risk passing a bare display name through.
            found = _EMAIL_RE.findall(raw)
            return ", ".join(self.address(a) for a in found)
        return ", ".join(
            formataddr((self.person(name) if name else "", self.address(addr) if addr else ""))
            for name, addr in parsed
        )

    # -- free text --

    def subject(self, text: str | None, seed: str = "") -> str:
        """Replace a subject, keeping any organiser rule keyword it contains.

        Keeping rule keywords is deliberate: they are the user's own taxonomy
        vocabulary, carry no personal data, and dropping them would silently
        break every keyword rule in the fixture.
        """
        if not text:
            return ""
        original = str(text)
        kept = [w for w in sorted(self.keep_words) if w and w in original.lower()]
        rng = int(hashlib.sha256((seed + original).encode("utf-8")).hexdigest(), 16)
        filler = [
            _SUBJECT_FILLER[(rng >> (i * 5)) % len(_SUBJECT_FILLER)]
            for i in range(2 + rng % 3)
        ]
        words = filler + kept
        return " ".join(words).strip().capitalize() or "Message"

    def summary(self, text: str | None, seed: str = "") -> str:
        """Replace summary prose, preserving bullet count and any action line.

        The Overview's action pill is parsed out of this text, so the fixture
        has to keep an action line where the original had one and omit it where
        it did not -- otherwise the parser's real hit rate is unmeasurable.
        """
        if not text:
            return ""
        original = str(text)
        lines = [ln for ln in original.splitlines() if ln.strip()]
        rng = int(hashlib.sha256((seed + original).encode("utf-8")).hexdigest(), 16)
        out: List[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            prefix = "- " if stripped.startswith(("-", "*", "•")) else ""
            lowered = stripped.lower().lstrip("-*• ")
            if lowered.startswith("action"):
                label = "Action items:" if lowered.startswith("action items") else "Action:"
                out.append(f"{prefix}{label} follow up on the {_SUBJECT_FILLER[(rng >> i) % len(_SUBJECT_FILLER)]} request.")
            else:
                out.append(
                    f"{prefix}A {_SUBJECT_FILLER[(rng >> (i * 3)) % len(_SUBJECT_FILLER)]} "
                    f"item was recorded for review."
                )
        return "\n".join(out)

    def free_text(self, text: str | None) -> str:
        """Strip identifiers out of text kept for its shape (memories, notes)."""
        if not text:
            return ""
        out = _EMAIL_RE.sub(lambda m: self.address(m.group(0)), str(text))
        out = _PHONE_RE.sub("+00 000 000 0000", out)
        for real, alias in self.people.items():
            if len(real) > 3:
                out = re.sub(re.escape(real), alias, out, flags=re.IGNORECASE)
        return out

    def message_id(self, mid: str | None) -> str:
        if not mid:
            return ""
        digest = hashlib.sha256(str(mid).encode("utf-8")).hexdigest()[:16]
        return f"<{digest}@{ALIAS_DOMAIN}>"


# ─────────────────────────── scrub ───────────────────────────

def _collect_keep_words(organisers: Dict[str, Any]) -> set[str]:
    """Rule keywords survive into scrubbed subjects — see Pseudonymiser.subject."""
    cols, rows = organisers.get("columns", []), organisers.get("rows", [])
    if "rules_json" not in cols:
        return set()
    idx = cols.index("rules_json")
    words: set[str] = set()
    for row in rows:
        try:
            rules = json.loads(row[idx] or "{}")
        except Exception:
            continue
        for kw in rules.get("keywords") or []:
            token = str(kw).strip().lower()
            if token:
                words.add(token)
    return words


def _scrub_urgency_states(states: Dict[str, Any], p: Pseudonymiser) -> Dict[str, Any]:
    """Rewrite per_uid and accounts entries, preserving every key that was set.

    Post: for each message, the set of present keys is unchanged. A message that
          had no ``snippet`` still has none -- that absence is the fixture's
          whole reason to exist.
    """
    out: Dict[str, Any] = {}
    for filename, state in states.items():
        if not isinstance(state, dict) or "__error__" in state:
            continue
        clean = {k: v for k, v in state.items() if k not in ("per_uid", "accounts")}
        clean["owner"] = "admin"

        per_uid = {}
        for key, msg in (state.get("per_uid") or {}).items():
            if not isinstance(msg, dict):
                continue
            scrubbed = dict(msg)
            if "from" in scrubbed:
                scrubbed["from"] = p.person(scrubbed.get("from"))
            if "subject" in scrubbed:
                scrubbed["subject"] = p.subject(scrubbed.get("subject"), seed=key)
            if "message_id" in scrubbed:
                scrubbed["message_id"] = p.message_id(scrubbed.get("message_id"))
            for field in ("snippet", "preview", "summary"):
                if field in scrubbed and scrubbed[field]:
                    scrubbed[field] = p.summary(scrubbed[field], seed=key)
            per_uid[key] = scrubbed
        clean["per_uid"] = per_uid

        accounts = {}
        for acc_id, info in (state.get("accounts") or {}).items():
            messages = []
            for msg in (info or {}).get("messages") or []:
                scrubbed = dict(msg)
                for field, fn in (
                    ("sender_name", p.person),
                    ("from_name", p.person),
                    ("sender", p.person),
                ):
                    if field in scrubbed:
                        scrubbed[field] = fn(scrubbed.get(field))
                for field in ("sender_email", "from_email"):
                    if field in scrubbed:
                        scrubbed[field] = p.address(scrubbed.get(field))
                if "subject" in scrubbed:
                    scrubbed["subject"] = p.subject(scrubbed.get("subject"), seed=acc_id)
                for field in ("snippet", "preview", "ai_comment", "summary"):
                    if field in scrubbed and scrubbed[field]:
                        scrubbed[field] = p.summary(scrubbed[field], seed=acc_id)
                messages.append(scrubbed)
            accounts[acc_id] = {**(info or {}), "messages": messages}
        if accounts:
            clean["accounts"] = accounts

        out[filename] = clean
    return out


def _scrub_table(table: Dict[str, Any], p: Pseudonymiser, rules: Dict[str, str]) -> Dict[str, Any]:
    """Apply a column -> pseudonymiser-method mapping across a table dump."""
    cols = table.get("columns", [])
    if not cols:
        return {"columns": [], "rows": []}

    method = {
        "person": lambda v, s: p.person(v),
        "address": lambda v, s: p.address(v),
        "address_list": lambda v, s: p.address_list(v),
        "subject": lambda v, s: p.subject(v, seed=s),
        "summary": lambda v, s: p.summary(v, seed=s),
        "free_text": lambda v, s: p.free_text(v),
        "message_id": lambda v, s: p.message_id(v),
        "owner": lambda v, s: "admin" if v else v,
    }

    out_rows = []
    for n, row in enumerate(table.get("rows", [])):
        new = list(row)
        for col, kind in rules.items():
            if col in cols:
                i = cols.index(col)
                new[i] = method[kind](new[i], f"{col}{n}")
        out_rows.append(new)
    return {"columns": cols, "rows": out_rows}


def _scrub_organisers(table: Dict[str, Any], p: Pseudonymiser) -> Dict[str, Any]:
    """Rewrite sender and domain rules to the aliases used everywhere else.

    Inv: an organiser that named a real sender now names that sender's alias,
         so the rule still selects the same messages in the fixture.
    """
    cols = table.get("columns", [])
    if not cols:
        return {"columns": [], "rows": []}

    rules_i = cols.index("rules_json") if "rules_json" in cols else None
    owner_i = cols.index("owner") if "owner" in cols else None
    desc_i = cols.index("description") if "description" in cols else None
    instr_i = cols.index("ai_instructions") if "ai_instructions" in cols else None

    out_rows = []
    for row in table.get("rows", []):
        new = list(row)
        if owner_i is not None and new[owner_i]:
            new[owner_i] = "admin"
        if desc_i is not None:
            new[desc_i] = p.free_text(new[desc_i])
        if instr_i is not None:
            new[instr_i] = p.free_text(new[instr_i])
        if rules_i is not None and new[rules_i]:
            try:
                rules = json.loads(new[rules_i])
            except Exception:
                rules = {}
            rules["senders"] = [p.person(s) for s in rules.get("senders") or []]
            rules["domains"] = [p.domain(d) for d in rules.get("domains") or []]
            # keywords are the user's taxonomy vocabulary, not personal data
            new[rules_i] = json.dumps(rules)
        out_rows.append(new)
    return {"columns": cols, "rows": out_rows}


def scrub(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Pseudonymise a raw dump. See module docstring for the bijection invariant.

    Pre:  raw is the structure produced by _fetch_remote.
    Post: the returned fixture carries no real identifier, and field presence
          matches the input exactly.
    """
    p = Pseudonymiser()
    organisers_raw = raw.get("work_organisers") or {"columns": [], "rows": []}
    p.keep_words = _collect_keep_words(organisers_raw)

    # Order matters: the index populates the people and address maps that the
    # organiser rules and memory text are then rewritten against.
    index = _scrub_table(
        raw.get("email_message_index") or {},
        p,
        {
            "owner": "owner",
            "from_name": "person",
            "from_address": "address",
            "to_text": "address_list",
            "cc_text": "address_list",
            "subject": "subject",
            "message_id": "message_id",
        },
    )
    summaries = _scrub_table(
        raw.get("email_summaries") or {},
        p,
        {
            "owner": "owner",
            "message_id": "message_id",
            "subject": "subject",
            "sender": "person",
            "summary": "summary",
        },
    )
    states = _scrub_urgency_states(raw.get("urgency_states") or {}, p)
    organisers = _scrub_organisers(organisers_raw, p)

    memories = []
    for mem in raw.get("memories") or []:
        if not isinstance(mem, dict):
            continue
        clean = dict(mem)
        clean["text"] = p.free_text(clean.get("text"))
        if clean.get("owner"):
            clean["owner"] = "admin"
        memories.append(clean)

    return {
        "_meta": {
            "source": "live phone instance, pseudonymised",
            "note": (
                "Field presence mirrors production exactly. Content does not. "
                "Regenerate with scripts/capture_briefing_fixture.py."
            ),
            "aliases": {
                "people": len(p.people),
                "addresses": len(p.addresses),
                "domains": len(p.domains),
            },
        },
        "urgency_states": states,
        "email_message_index": index,
        "email_summaries": summaries,
        "work_organisers": organisers,
        "memories": memories,
    }


class FixtureLeak(Exception):
    """A real identifier survived scrubbing. The fixture must not be written."""


def _identifiers_in(raw: Dict[str, Any]) -> set[str]:
    """Every real name and address the dump contains, as literal strings."""
    found: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        for name, addr in getaddresses([text]):
            if addr and "@" in addr:
                found.add(addr.lower())
            display = (name or "").strip().strip("'\"")
            if len(display) > 3 and "@" not in display:
                found.add(display)
        if "@" not in text and "<" not in text and len(text) > 3:
            found.add(text)

    for table, columns in (
        (raw.get("email_message_index"), ("from_name", "from_address", "to_text", "cc_text")),
        (raw.get("email_summaries"), ("sender",)),
    ):
        cols = (table or {}).get("columns") or []
        for col in columns:
            if col in cols:
                i = cols.index(col)
                for row in table.get("rows", []):
                    add(row[i])

    for state in (raw.get("urgency_states") or {}).values():
        if not isinstance(state, dict):
            continue
        for msg in (state.get("per_uid") or {}).values():
            if isinstance(msg, dict):
                add(msg.get("from"))

    org = raw.get("work_organisers") or {}
    cols = org.get("columns") or []
    if "rules_json" in cols:
        i = cols.index("rules_json")
        for row in org.get("rows", []):
            try:
                rules = json.loads(row[i] or "{}")
            except Exception:
                continue
            for sender in rules.get("senders") or []:
                add(sender)

    return {f for f in found if len(f) > 3}


def _already_in_committed_source(term: str) -> bool:
    """Whether this term is already written in the repository's own source.

    A vendor or product name the codebase already names in the clear -- GitHub,
    Ollama, the operator's own company -- is not disclosed by a fixture that
    also names it. Customer and correspondent names appear nowhere in source,
    so this exempts exactly the class that is not personal data, without
    softening the check for the class that is.

    Pre:  term is a candidate identifier.
    Post: True only when the term occurs in a tracked source file outside the
          fixture and data directories.
    """
    needle = term.lower()
    roots = ("routes", "src", "mcp_servers", "static", "core", "services", "companion")
    for root in roots:
        base = _REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() not in (".py", ".js", ".md") or not path.is_file():
                continue
            try:
                if needle in path.read_text(encoding="utf-8", errors="ignore").lower():
                    return True
            except OSError:
                continue
    return False


def verify_no_leak(raw: Dict[str, Any], fixture: Dict[str, Any]) -> List[str]:
    """Fail generation if any real identifier survived into the fixture.

    Pre:  raw and fixture are the same capture, before and after scrubbing.
    Post: returns the list of terms exempted as already-public; raises
          FixtureLeak if anything else survived.
    Inv:  this runs inside generation, never as a follow-up step -- an
          unscrubbed fixture must be impossible to produce, not merely
          detectable afterwards.
    """
    serialised = json.dumps(fixture, ensure_ascii=False).lower()
    survivors = sorted(i for i in _identifiers_in(raw) if i.lower() in serialised)

    exempt, leaked = [], []
    for term in survivors:
        if "@" not in term and _already_in_committed_source(term):
            exempt.append(term)
        else:
            leaked.append(term)

    if leaked:
        shown = ", ".join(repr(x) for x in leaked[:8])
        raise FixtureLeak(
            f"{len(leaked)} real identifier(s) survived scrubbing: {shown}"
            f"{' ...' if len(leaked) > 8 else ''}. Fixture not written."
        )
    return exempt


def summarise(fixture: Dict[str, Any]) -> str:
    """Report the distribution the fixture preserves, so drift is visible."""
    lines: List[str] = []
    for filename, state in (fixture.get("urgency_states") or {}).items():
        per_uid = state.get("per_uid") or {}
        present: Dict[str, int] = {}
        for msg in per_uid.values():
            for field in ("reason", "snippet", "preview", "summary", "tags"):
                if msg.get(field):
                    present[field] = present.get(field, 0) + 1
        lines.append(f"  {filename}: {len(per_uid)} messages, field presence {present}")

    for name in ("email_message_index", "email_summaries", "work_organisers"):
        table = fixture.get(name) or {}
        lines.append(f"  {name}: {len(table.get('rows', []))} rows")
    lines.append(f"  memories: {len(fixture.get('memories') or [])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"fixture destination (default: {DEFAULT_OUT})")
    parser.add_argument("--data-dir", default=REMOTE_DATA_DIR,
                        help="remote Odysseus data directory")
    parser.add_argument("--raw-out", type=Path, default=None,
                        help="also write the unscrubbed dump here, for debugging the "
                             "scrubber. Name it *.raw.json — .gitignore excludes that "
                             "pattern, so it cannot be committed by accident.")
    args = parser.parse_args()

    print(f"Reading {args.data_dir} on the phone...")
    raw = _fetch_remote(args.data_dir)

    if args.raw_out:
        args.raw_out.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        print(f"  raw dump written to {args.raw_out} — do not commit this")

    fixture = scrub(raw)
    try:
        exempt = verify_no_leak(raw, fixture)
    except FixtureLeak as exc:
        print(f"REFUSING TO WRITE: {exc}", file=sys.stderr)
        return 1
    print("  leak check passed — no personal identifier survives")
    if exempt:
        print(f"  already named in committed source, kept: {', '.join(exempt)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Fixture written to {args.out}")
    print(summarise(fixture))
    aliases = fixture["_meta"]["aliases"]
    print(f"  aliases minted: {aliases}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
