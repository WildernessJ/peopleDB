"""Template-level checks for dark-mode support (issue #8): the pre-paint theme
script and toggle button render on a page that needs no live CardDAV server,
and the stylesheet defines the attribute-selector overrides the toggle relies
on."""

from pathlib import Path

from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings


def make_client(tmp_path):
    settings = Settings(
        dav_url="http://127.0.0.1:1",  # unreachable; unused by GET /login
        secret_key="",
        db_path=str(tmp_path / "cache.db"),
        secure_cookies=False,
    )
    app = create_app(settings)
    return TestClient(app, follow_redirects=False)


def test_login_page_has_pre_paint_theme_script_but_no_toggle(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/login")
    assert resp.status_code == 200
    body = resp.text
    # Inline script runs before body render and reads only localStorage —
    # no user/request data interpolated into it.
    assert "localStorage.getItem('peopledb-theme')" in body
    # The pre-paint script still applies the saved/OS theme on login (no flash),
    # but the toggle control itself moved into the authenticated top bar
    # (_topbar.html, issue #26) — login has no top bar, so no toggle here.
    assert 'id="theme-toggle"' not in body
    # The toggle still exists — just in the shared top bar, not on login.
    topbar = (
        Path(__file__).resolve().parent.parent
        / "src" / "peopledb" / "templates" / "_topbar.html"
    ).read_text()
    assert 'id="theme-toggle"' in topbar
    # Pre-paint script must run before the stylesheet, so <html> already has
    # data-theme stamped by the time CSS applies (no flash of wrong theme).
    assert body.index("localStorage.getItem('peopledb-theme')") < body.index("<style>")
    # Effective theme resolution falls back to OS preference in the script,
    # not via a media-query palette block in the stylesheet.
    assert "prefers-color-scheme: dark" in body.split("<style>")[0]


def test_stylesheet_defines_dark_theme_overrides(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/login")
    body = resp.text
    assert ":root[data-theme=" + '"dark"]' in body
    stylesheet = body.split("<style>", 1)[1]
    assert "prefers-color-scheme: dark" not in stylesheet
