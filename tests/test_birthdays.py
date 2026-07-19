"""Tests for birthday parsing/ordering and the ICS feed content."""

from datetime import date

from peopledb.birthdays import format_bday_date, ics_feed, next_birthday, parse_bday


def test_parse_full_date():
    assert parse_bday("1985-04-12") == (1985, 4, 12)


def test_parse_no_year_forms():
    assert parse_bday("--04-12") == (None, 4, 12)
    # Apple stores year-omitted birthdays as year 1604.
    assert parse_bday("1604-04-12") == (None, 4, 12)


def test_parse_compact_form():
    assert parse_bday("19850412") == (1985, 4, 12)


def test_parse_garbage_returns_none():
    assert parse_bday("not-a-date") is None
    assert parse_bday("") is None


def test_next_birthday_upcoming_this_year():
    nxt, age = next_birthday("1985-04-12", today=date(2026, 3, 1))
    assert nxt == date(2026, 4, 12)
    assert age == 41


def test_next_birthday_already_passed_rolls_over():
    nxt, age = next_birthday("1985-04-12", today=date(2026, 5, 1))
    assert nxt == date(2027, 4, 12)
    assert age == 42


def test_next_birthday_today_counts_as_today():
    nxt, _ = next_birthday("1985-04-12", today=date(2026, 4, 12))
    assert nxt == date(2026, 4, 12)


def test_next_birthday_without_year_has_no_age():
    nxt, age = next_birthday("--12-25", today=date(2026, 7, 13))
    assert nxt == date(2026, 12, 25)
    assert age is None


def test_next_birthday_feb29_on_non_leap_year():
    nxt, _ = next_birthday("2000-02-29", today=date(2026, 1, 1))
    assert nxt == date(2026, 2, 28)


def test_ics_feed_escapes_special_chars_and_newlines():
    # A name with a newline / comma / semicolon / backslash must not be able to
    # inject new iCalendar lines or break the SUMMARY value.
    ics = ics_feed([("Evil\r\nX-INJECTED:owned,me;now\\here", "1990-01-01")])
    lines = ics.split("\r\n")
    assert not any(line.startswith("X-INJECTED") for line in lines)
    summary = next(line for line in lines if line.startswith("SUMMARY:"))
    assert "\\n" in summary  # newline folded into an escaped sequence
    assert "\\," in summary and "\\;" in summary and "\\\\" in summary


def test_format_bday_date_strips_leading_zero_from_single_digit_day():
    # birthdays.html previously rendered this via strftime("%a %b %-d"), a
    # glibc/BSD extension that raises ValueError on Windows Python. The
    # portable replacement must produce identical output: no leading zero.
    assert format_bday_date(date(2026, 7, 4)) == "Sat Jul 4"


def test_format_bday_date_keeps_two_digit_day_as_is():
    assert format_bday_date(date(2026, 7, 13)) == "Mon Jul 13"


def test_ics_feed_contains_yearly_events():
    ics = ics_feed([("Sarah Jones", "1985-04-12"), ("No Year", "--12-25")])
    assert ics.startswith("BEGIN:VCALENDAR")
    assert "SUMMARY:Sarah Jones's birthday" in ics
    assert "RRULE:FREQ=YEARLY" in ics
    assert "SUMMARY:No Year's birthday" in ics
    assert ics.rstrip().endswith("END:VCALENDAR")
