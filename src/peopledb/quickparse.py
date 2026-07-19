"""Natural-language quick-entry parser: turns one free-text line into
`ContactFields` for the add-contact form to pre-fill. Rule-based only (no
network dependency, no LLM); the user reviews every field before Save, so
this is deliberately forgiving -- a misplaced token landing in Note or the
name is acceptable, not a bug.

Extraction order matters (each match is removed from the working string
before the next step runs, so later steps can't re-grab it): email, url,
phone, #group, bday, org, then whatever leading words remain become the name
and anything still left over becomes the note. A removed match is replaced with
a `_SENTINEL` marker rather than deleted outright, so the name/note split
(the leading run of words *before the first match*) can still be located
after several steps have each spliced the string."""

from __future__ import annotations

import re
from datetime import date

from peopledb.vcard import ContactFields

_SENTINEL = "\x00"

_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
# Phone chars are `+`/digits/spaces/dashes/parens (per spec) -- note NO `.`,
# so a decimal, IP, or version string (`3.14159`, `192.168.1.1`) in free text
# isn't misread as a phone. A phone never *starts* on `)` (allowing it let a
# label's closing paren `... (work) +44 ...` begin a bogus candidate that
# swallowed the next number); `(` stays a valid start for `(555) 123-4567`.
_PHONE_CANDIDATE_RE = re.compile(r"[+(\d][\d+\-()\s]*\d")

# A `+` that isn't the first character starts a new international number: the
# greedy scan above spans two space-separated numbers into one run, so split
# there first. What's left of each `+`-delimited piece may still be several
# whitespace-joined domestic numbers (`555-123-4567 555-987-6543`) -- those
# are split by the greedy digit-count rule in `_split_phone_run` below.
_PHONE_SPLIT_RE = re.compile(r"\s+(?=\+)")
_LABEL_RE = re.compile(r"\s*\(([^)]*)\)")
# A `#` followed by one-or-more non-space, non-`#` chars. Run *after*
# email/url/phone extraction so a `#fragment` inside a URL (the URL regex
# grabs `\S+`, fragment included) has already been consumed and can't be
# misread as a group tag. A bare `#` (nothing follows) doesn't match at all,
# so it's left untouched -- ignored rather than captured as an empty group.
_GROUP_RE = re.compile(r"#([^\s#]+)")
_BDAY_RE = re.compile(r"\bbday\b", re.IGNORECASE)
_ORG_RE = re.compile(r"\borg\b", re.IGNORECASE)

# Keywords that bound a keyword-led capture (bday's date, org's name) -- and
# that a phone/date scan must not cross over.
_SIGIL_WORDS = {"bday", "org"}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _take_label(text: str, start: int) -> tuple[str, int]:
    """If `text[start:]` begins with `(label)` (allowing leading whitespace),
    return (label, end_index_after_the_paren). Else ("", start)."""
    match = _LABEL_RE.match(text, start)
    if match:
        return match.group(1).strip(), match.end()
    return "", start


def _preceding_word(text: str, idx: int) -> str:
    words = text[:idx].split()
    return words[-1] if words else ""


def _extract_all(text: str, pattern: re.Pattern) -> tuple[list[tuple[str, str]], str]:
    """Remove every match of `pattern` from `text`, pairing each with a
    trailing `(label)` if present, replacing the consumed span with a
    sentinel. Returns (items, remaining_text)."""
    items: list[tuple[str, str]] = []
    out = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() < pos:
            continue  # overlaps a span already consumed
        out.append(text[pos:m.start()])
        label, end = _take_label(text, m.end())
        items.append((label, m.group(0)))
        out.append(_SENTINEL)
        pos = end
    out.append(text[pos:])
    return items, "".join(out)


def _greedy_domestic_split(piece: str) -> list[str]:
    """Split one phone piece (already delimited on any interior `+`, so it
    may still *start* with a `+`) into whitespace-joined domestic
    numbers by a greedy digit count: accumulate space-separated groups into
    a "current number" and close it as soon as its digit count reaches >=10
    (a full domestic number), so `555 123 4567` (10 digits, closes only at
    the last group) stays one phone while `555-123-4567 555-987-6543`
    (10 digits each) closes after every group.

    Whatever groups are left over at the end form the last number. If that
    leftover has <7 digits (the phone-shaped minimum), it's not a number on
    its own -- fold it back onto the previous number rather than emitting a
    fragment (e.g. a trailing extension-like tail with too few digits)."""
    numbers: list[str] = []
    current: list[str] = []
    digits = 0
    for group in piece.split():
        current.append(group)
        digits += sum(c.isdigit() for c in group)
        if digits >= 10:
            numbers.append(" ".join(current))
            current = []
            digits = 0
    if current:
        remainder = " ".join(current)
        # `digits` already holds the remainder's digit count (reset to 0 at
        # each close, then re-accumulated over the leftover groups).
        if numbers and digits < 7:
            numbers[-1] = f"{numbers[-1]} {remainder}"
        else:
            numbers.append(remainder)
    return numbers


def _split_phone_run(run: str) -> list[str]:
    """Split a matched phone-candidate run into individual numbers: first on
    any non-leading `+` (a new international number), then greedily within
    each resulting piece for whitespace-joined domestic runs."""
    numbers: list[str] = []
    for piece in _PHONE_SPLIT_RE.split(run):
        numbers.extend(_greedy_domestic_split(piece))
    return numbers


def _extract_phones(text: str) -> tuple[list[tuple[str, str]], str]:
    """Like `_extract_all` but for phone-shaped runs: requires >=7 digits,
    and skips a candidate immediately preceded by `bday` -- an ISO date
    (`1990-03-03`) is digit-and-dash shaped enough to otherwise look like a
    phone number, and bday is parsed in a later step."""
    items: list[tuple[str, str]] = []
    out = []
    pos = 0
    for m in _PHONE_CANDIDATE_RE.finditer(text):
        if m.start() < pos:
            continue
        if sum(c.isdigit() for c in m.group(0)) < 7:
            continue
        if _preceding_word(text, m.start()).lower() == "bday":
            continue
        out.append(text[pos:m.start()])
        label, end = _take_label(text, m.end())
        numbers = _split_phone_run(m.group(0).strip())
        # A single trailing label describes the last number in the run.
        for i, number in enumerate(numbers):
            items.append((label if i == len(numbers) - 1 else "", number))
        out.append(_SENTINEL)
        pos = end
    out.append(text[pos:])
    return items, "".join(out)


def _extract_groups(text: str) -> tuple[list[str], str]:
    """Remove every `#token` from `text`, collecting the token (case
    preserved -- matching against existing group names is the route's job,
    not the parser's) and splicing a sentinel in its place, mirroring
    `_extract_all`/`_extract_org`."""
    names: list[str] = []
    out = []
    pos = 0
    for m in _GROUP_RE.finditer(text):
        out.append(text[pos:m.start()])
        names.append(m.group(1))
        out.append(_SENTINEL)
        pos = m.end()
    out.append(text[pos:])
    return names, "".join(out)


def _parse_date(text: str) -> str:
    """Best-effort date normalization: YYYY-MM-DD when a year is present,
    else --MM-DD. Returns "" if unparseable.

    Only unambiguous forms are accepted: ISO (`YYYY-MM-DD`) and named-month
    (`3 Mar` / `Mar 3`). Bare numeric slash dates (`3/4`, `12/25`) are *not*
    parsed -- they are D/M-vs-M/D ambiguous and this value feeds the birthday
    ICS feed, so a silent wrong date is worse than leaving it for the user to
    type in the reviewed form (it falls through to Note)."""
    text = text.strip()

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        year, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(year, mon, day)
        except ValueError:
            return ""
        return f"{year:04d}-{mon:02d}-{day:02d}"

    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)", text)
    if m:
        day, mon = int(m.group(1)), _MONTHS.get(m.group(2)[:3].lower())
        if mon is None:
            return ""
        try:
            date(2000, mon, day)
        except ValueError:
            return ""
        return f"--{mon:02d}-{day:02d}"

    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})", text)
    if m:
        mon, day = _MONTHS.get(m.group(1)[:3].lower()), int(m.group(2))
        if mon is None:
            return ""
        try:
            date(2000, mon, day)
        except ValueError:
            return ""
        return f"--{mon:02d}-{day:02d}"

    return ""


def _extract_bday(text: str) -> tuple[str, str]:
    """Find `bday <date>` (case-insensitive keyword) and consume the date
    token(s) that follow, up to 2 tokens (covers `1990-03-03`, `3 Mar`,
    `Mar 3`), stopping early at another recognized sigil word. If the date
    can't be parsed, bday stays "" and the text is left untouched so it
    falls through to Note verbatim."""
    m = _BDAY_RE.search(text)
    if not m:
        return "", text

    after = text[m.end():]
    # Track each word with its end offset in `after` so the splice is by
    # character span, not by re-joining and str.find (which misses when the
    # user typed irregular whitespace, leaking the date into name/note too).
    consumed: list[tuple[str, int]] = []
    for wm in re.finditer(r"\S+", after):
        word = wm.group(0)
        if _SENTINEL in word or word.lower() in _SIGIL_WORDS:
            break
        consumed.append((word, wm.end()))
        if len(consumed) == 2:
            break

    for n in range(len(consumed), 0, -1):
        candidate = " ".join(word for word, _ in consumed[:n])
        bday = _parse_date(candidate)
        if not bday:
            continue
        rest = _SENTINEL + after[consumed[n - 1][1]:]
        return bday, text[:m.start()] + rest

    return "", text


def _extract_org(text: str) -> tuple[str, str]:
    """Find `org <name>` (case-insensitive keyword) and consume words up to
    the next recognized sigil word, sentinel, or end of string (org is
    multi-word)."""
    m = _ORG_RE.search(text)
    if not m:
        return "", text

    after = text[m.end():]
    # Span-based splice (see _extract_bday): consume words up to the next
    # sigil/sentinel/end, then cut by offset so irregular whitespace can't
    # make the removal miss and duplicate the org text into the name.
    org_words: list[str] = []
    end_off = 0
    for wm in re.finditer(r"\S+", after):
        w = wm.group(0)
        if _SENTINEL in w or w.lower() in _SIGIL_WORDS:
            break
        org_words.append(w)
        end_off = wm.end()

    if not org_words:
        return "", text

    org = " ".join(org_words)
    rest = _SENTINEL + after[end_off:]
    return org, text[:m.start()] + rest


def parse_quick_entry(text: str) -> ContactFields:
    """Parse one free-text quick-entry line into ContactFields. Pure
    function -- no I/O, no validation; the add-contact form is the review
    step, so this is forgiving by design."""
    fields = ContactFields()
    working = text

    fields.emails, working = _extract_all(working, _EMAIL_RE)
    fields.urls, working = _extract_all(working, _URL_RE)
    fields.phones, working = _extract_phones(working)
    fields.groups, working = _extract_groups(working)
    fields.bday, working = _extract_bday(working)
    fields.org, working = _extract_org(working)

    first_sentinel = working.find(_SENTINEL)
    if first_sentinel == -1:
        name_zone, leftover = working, ""
    else:
        name_zone, leftover = working[:first_sentinel], working[first_sentinel:]

    words = name_zone.split()
    if words:
        fields.given = words[0]
        fields.family = " ".join(words[1:])

    fields.note = re.sub(r"\s+", " ", leftover.replace(_SENTINEL, " ")).strip()

    return fields
