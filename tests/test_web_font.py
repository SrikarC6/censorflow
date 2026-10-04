"""The 5x7 font has to be complete before any screen depends on it.

There is no JavaScript test runner in this project, so this reads
`web/font5x7.js` as text and checks the font table directly. A typo in one
bitmask row would otherwise only show up as a subtly wrong letter on a canvas.
"""

from __future__ import annotations

import re

import pytest

from censorflow import config

FONT_FILE = config.WEB_DIR / "font5x7.js"
FLIPDISC_FILE = config.WEB_DIR / "flipdisc.js"

# Every character AGENTS.md requires of the 5x7 font.
REQUIRED = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " !?()<>_=/+-.,;:@#$%&x÷"
)

GLYPH_COLS = 5
GLYPH_ROWS = 7

# e.g.  A: [0b01110, 0b10001, ...],   'a': [0, 0, ...],   0: [0b...],
_ENTRY = re.compile(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"|([A-Za-z0-9_$]+)):\s*\[([^\]]*)\],")
_ROW = re.compile(r"0[bB][01]+|\d+")


def _font_table() -> dict[str, list[int]]:
    """The FONT object in web/font5x7.js as {character: [row masks]}."""
    text = FONT_FILE.read_text(encoding="utf-8")
    start = text.index("const FONT = {")
    body = text[start:]
    # The table ends at the first line that is exactly "};".
    end = body.index("\n};")
    table: dict[str, list[int]] = {}
    for line in body[:end].splitlines():
        match = _ENTRY.match(line)
        if match is None:
            continue
        key = match.group(1) or match.group(2) or match.group(3)
        # JS escapes the backslash and quote characters in single-quoted keys.
        key = key.replace("\\\\", "\\").replace("\\'", "'")
        rows = [int(row, 0) for row in _ROW.findall(match.group(4))]
        table[key] = rows
    return table


@pytest.fixture(scope="module")
def font() -> dict[str, list[int]]:
    return _font_table()


def test_the_font_file_is_where_the_test_expects_it() -> None:
    assert FONT_FILE.is_file(), f"missing {FONT_FILE}"


def test_the_table_was_parsed(font: dict[str, list[int]]) -> None:
    # 26 letters + 10 digits + space + the symbol set.
    assert len(font) >= 60, f"only {len(font)} glyphs parsed; the regex is probably wrong"


@pytest.mark.parametrize("char", REQUIRED)
def test_every_required_glyph_exists(font: dict[str, list[int]], char: str) -> None:
    assert char in font, f"no glyph for {char!r} in {FONT_FILE.name}"


@pytest.mark.parametrize("char", REQUIRED)
def test_every_required_glyph_is_seven_rows_of_five_bits(
    font: dict[str, list[int]], char: str
) -> None:
    rows = font[char]
    assert len(rows) == GLYPH_ROWS, f"{char!r} has {len(rows)} rows, want {GLYPH_ROWS}"
    for index, bits in enumerate(rows):
        assert 0 <= bits < 1 << GLYPH_COLS, (
            f"{char!r} row {index} is {bits:#b}, which does not fit in {GLYPH_COLS} bits"
        )


def test_x_is_the_only_lowercase_key_and_stays_reachable() -> None:
    # glyphFor tries the literal character before its uppercase form, so the one
    # lowercase key in the table (the multiplication x) is actually reachable.
    table = _font_table()
    lowercase = {char for char in table if char.isalpha() and char != char.upper()}
    assert lowercase == {"x"}, f"unexpected lowercase keys: {sorted(lowercase)}"
    source = FONT_FILE.read_text(encoding="utf-8")
    assert "FONT[key] ?? FONT[key.toUpperCase()]" in source, (
        "glyphFor uppercases before looking up, which makes the x glyph unreachable"
    )
    assert "${String(char)}@${scale}" in source, (
        "the glyph bitmap cache must key on the raw character or x and X collide"
    )


def test_the_arrows_and_the_four_new_symbol_blocks_are_present() -> None:
    # The prototype font had none of these; they were authored for this project.
    for char in "<>_=;@$" + "÷" + "→←↑↓":
        assert char in _font_table(), f"{char!r} was never authored"


def test_x_and_the_times_sign_share_a_glyph() -> None:
    table = _font_table()
    assert table["x"] == table["×"]


def test_the_board_reads_its_colours_from_css_variables() -> None:
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    for name in ("--on", "--off", "--bg", "--on-hi"):
        assert f"'{name}'" in text, f"flipdisc.js does not read {name} from the stylesheet"
    assert "getComputedStyle(document.documentElement)" in text


def test_the_board_has_no_animation_loop() -> None:
    # AGENTS.md forbids requestAnimationFrame in the UI. It stays out until
    # someone decides, deliberately, that animation is worth the battery.
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    assert "requestAnimationFrame" not in text
    assert "setInterval" not in text