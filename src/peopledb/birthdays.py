"""Birthday parsing, next-occurrence math, and the ICS feed.

Handles the BDAY dialects Apple clients write: full dates (1985-04-12,
19850412), year-omitted (--04-12), and Apple's omit-year sentinel (1604)."""

from __future__ import annotations

import re
from datetime import date

_APPLE_OMIT_YEAR = 1604

_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"^--(\d{2})-?(\d{2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
)


def parse_bday(value: str) -> tuple[int | None, int, int] | None:
    """Return (year-or-None, month, day), or None if unparseable."""
    value = value.strip()
    for pattern in _PATTERNS:
        match = pattern.match(value)
        if not match:
            continue
        groups = [int(g) for g in match.groups()]
        year, month, day = (None, *groups) if len(groups) == 2 else groups
        if year == _APPLE_OMIT_YEAR:
            year = None
        try:
            date(2000, month, day)  # leap-safe validity check
        except ValueError:
            return None
        return year, month, day
    return None


def format_bday_date(value: date) -> str:
    """ "Sat Jul 4" style rendering for the upcoming-birthdays list.

    Avoids strftime's "%-d" (a glibc/BSD extension not supported on Windows
    Python) by computing the unpadded day via `.day` instead."""
    return f"{value:%a %b} {value.day}"


def _ics_escape(text: str) -> str:
    """Escape a value for an iCalendar TEXT property (RFC 5545 §3.3.11).
    Backslash first, then delimiters, and fold CR/LF into the literal \\n so a
    name can never terminate the line and inject new properties."""
    text = text.replace("\\", "\\\\")
    text = text.replace(",", "\\,").replace(";", "\\;")
    text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return text


def _occurrence_in(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:  # Feb 29 in a non-leap year
        return date(year, month, day - 1)


def next_birthday(value: str, today: date) -> tuple[date, int | None] | None:
    """Next occurrence of the birthday on/after `today`, plus the age they
    turn (None when the birth year is unknown)."""
    parsed = parse_bday(value)
    if parsed is None:
        return None
    year, month, day = parsed
    nxt = _occurrence_in(today.year, month, day)
    if nxt < today:
        nxt = _occurrence_in(today.year + 1, month, day)
    age = (nxt.year - year) if year else None
    return nxt, age


def ics_feed(people: list[tuple[str, str]]) -> str:
    """Yearly recurring all-day birthday events for (name, bday) pairs."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//peopleDB//birthdays//EN",
        "X-WR-CALNAME:Birthdays (peopleDB)",
    ]
    for name, bday in people:
        parsed = parse_bday(bday)
        if parsed is None:
            continue
        year, month, day = parsed
        start = date(year or 2000, month, day)
        uid_name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
        summary = _ics_escape(f"{name}'s birthday")
        lines += [
            "BEGIN:VEVENT",
            f"UID:bday-{uid_name}-{month:02d}{day:02d}@peopledb",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            "RRULE:FREQ=YEARLY",
            f"SUMMARY:{summary}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
