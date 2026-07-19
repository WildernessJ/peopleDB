"""The safe_url template filter must neutralize script-bearing URL schemes."""

import pytest

from peopledb.app import _safe_url


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.com", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("mailto:a@b.com", "mailto:a@b.com"),
        ("example.com", "https://example.com"),
        ("  https://x.test  ", "https://x.test"),
        ("javascript:alert(document.cookie)", "#"),
        ("JavaScript:alert(1)", "#"),
        ("data:text/html,<script>alert(1)</script>", "#"),
        ("vbscript:msgbox(1)", "#"),
    ],
)
def test_safe_url(value, expected):
    assert _safe_url(value) == expected
