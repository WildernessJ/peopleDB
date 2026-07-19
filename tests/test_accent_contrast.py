"""Guard the accent palette (issues #12, #13).

Two invariants, both parsed straight from base.html:

1. **Contrast.** Every `--accent` value must clear WCAG AA (4.5:1) on the theme
   it belongs to, in all three ways the token is actually used: accent-as-text on
   the page background and on surfaces, and the accent-fg color on top of the
   accent (button labels, initials avatars). Banner backgrounds are deliberately
   NOT a checked surface: banner links inherit the banner's own high-contrast
   foreground (`.banner a { color: inherit }`), not `--accent`, so the accent is
   never rendered against a banner tint. (That decoupling was the fix for the
   session-audit finding where the default dark accent hit 4.496:1 on a warn
   banner.)

2. **Cross-file key sync.** Each accent key lives in four places — a {light,dark}
   pair of CSS rules, a swatch button, and TWO hand-maintained `ACCENTS`
   allowlists (a pre-paint <head> script and the body picker script). If they
   drift, a swatch can apply on click but silently fail to restore on reload.
   test_accent_keys_in_sync enforces that they all agree.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "peopledb" / "templates"
BASE_HTML = _TEMPLATES / "base.html"
# The accent swatch markup lives in the shared top-bar partial (issue #26);
# the CSS presets and both ACCENTS allowlists stay in base.html.
TOPBAR_HTML = _TEMPLATES / "_topbar.html"

# Theme constants mirrored from base.html's :root rules.
LIGHT_BG, LIGHT_SURFACE, LIGHT_ACCENT_FG = "#fafafa", "#ffffff", "#ffffff"
DARK_BG, DARK_SURFACE, DARK_ACCENT_FG = "#16171a", "#232427", "#1c1c1c"

AA_NORMAL = 4.5

# selector { ... --accent: #rrggbb ... }
ACCENT_RULE = re.compile(r"([^{}]*)\{[^{}]*?--accent:\s*(#[0-9a-fA-F]{6})", re.DOTALL)
# :root[data-accent="green"] { ... }  — the non-default preset CSS rules.
CSS_ACCENT_KEY = re.compile(r':root\[data-accent="([a-z]+)"\]')
# <button ... data-accent-choice="green" ...>  — the swatch buttons in markup.
SWATCH_KEY = re.compile(r'data-accent-choice="([a-z]+)"')
# var ACCENTS = { red:1, ... };  — each of the two allowlist object literals.
ALLOWLIST_BLOCK = re.compile(r"var ACCENTS = \{([^}]*)\}")
ALLOWLIST_KEY = re.compile(r"([a-z]+)\s*:\s*1")


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    r, g, b = linear
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _accent_rules() -> list[tuple[str, str, bool]]:
    """Return (selector, accent_hex, is_dark) for every --accent declaration."""
    text = BASE_HTML.read_text()
    rules = []
    for selector, hex_color in ACCENT_RULE.findall(text):
        is_dark = 'data-theme="dark"' in selector
        rules.append((selector.strip(), hex_color, is_dark))
    return rules


def test_accent_rule_count_matches_palette():
    """base red (light+dark) + each non-default preset (light+dark). Tight, so
    dropping or half-adding a preset's CSS fails instead of passing silently."""
    text = BASE_HTML.read_text()
    non_default = set(CSS_ACCENT_KEY.findall(text))
    expected = 2 + 2 * len(non_default)
    assert len(_accent_rules()) == expected, (
        f"expected {expected} --accent rules for {len(non_default)} presets, "
        f"found {len(_accent_rules())}"
    )


def test_every_accent_meets_aa_contrast():
    failures = []
    for selector, accent, is_dark in _accent_rules():
        if is_dark:
            checks = {
                "text-on-bg": _contrast(accent, DARK_BG),
                "text-on-surface": _contrast(accent, DARK_SURFACE),
                "fg-on-accent": _contrast(DARK_ACCENT_FG, accent),
            }
        else:
            checks = {
                "text-on-bg": _contrast(accent, LIGHT_BG),
                "text-on-surface": _contrast(accent, LIGHT_SURFACE),
                "fg-on-accent": _contrast(LIGHT_ACCENT_FG, accent),
            }
        worst = min(checks.values())
        if worst < AA_NORMAL:
            weak = {k: round(v, 2) for k, v in checks.items() if v < AA_NORMAL}
            failures.append(f"{selector} ({accent}): {weak}")
    assert not failures, "accent(s) below AA 4.5:1:\n" + "\n".join(failures)


def test_accent_keys_in_sync():
    """Swatch markup, both JS allowlists, and the CSS preset rules must agree.
    Catches the 'added a swatch but forgot one allowlist' drift, which otherwise
    only shows up as an accent that applies on click but reverts on reload."""
    text = BASE_HTML.read_text()

    swatches = SWATCH_KEY.findall(TOPBAR_HTML.read_text())
    swatch_set = set(swatches)
    css_presets = set(CSS_ACCENT_KEY.findall(text))
    allowlists = [set(ALLOWLIST_KEY.findall(b)) for b in ALLOWLIST_BLOCK.findall(text)]

    assert len(swatches) == len(swatch_set), f"duplicate swatch(es): {swatches}"
    assert len(allowlists) == 2, f"expected 2 ACCENTS allowlists, found {len(allowlists)}"
    assert allowlists[0] == allowlists[1], (
        "the two ACCENTS allowlists disagree: "
        f"only-in-head={allowlists[0] - allowlists[1]}, "
        f"only-in-body={allowlists[1] - allowlists[0]}"
    )
    assert swatch_set == allowlists[0], (
        "swatch markup and ACCENTS allowlist disagree: "
        f"swatch-only={swatch_set - allowlists[0]}, allowlist-only={allowlists[0] - swatch_set}"
    )
    # 'red' is the default and lives in the base :root rules, not a data-accent rule.
    assert css_presets == swatch_set - {"red"}, (
        "CSS preset rules and swatches disagree: "
        f"css-only={css_presets - (swatch_set - {'red'})}, "
        f"swatch-only={(swatch_set - {'red'}) - css_presets}"
    )
