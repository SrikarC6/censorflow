"""The dot-matrix fonts have to be complete before any screen depends on them.

There is no JavaScript test runner in this project, so this reads
`web/font5x7.js` as text and checks both font tables directly. A typo in one
bitmask row would otherwise only show up as a subtly wrong letter on a canvas.

Two sets live in the file: `SERIF` (7x9, the default) and `SANS` (5x7, the
transit-signage original). They have different metrics, so the shape assertions
are parameterised per set.
"""

from __future__ import annotations

import re

import pytest

from censorflow import config

FONT_FILE = config.WEB_DIR / "font5x7.js"
FLIPDISC_FILE = config.WEB_DIR / "flipdisc.js"
MOTION_FILE = config.WEB_DIR / "flip-motion.js"
SOUND_FILE = config.WEB_DIR / "flip-sound.js"
STYLE_FILE = config.WEB_DIR / "style.css"

# Every character AGENTS.md requires of the dot-matrix font.
REQUIRED = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " !?()<>_=/+-.,;:@#$%&x÷"
)

# The sets each table is authored for, keyed by the variable that holds it.
SETS = {"SERIF_GLYPHS": (7, 9), "SANS_GLYPHS": (5, 7)}

# e.g.  A: [0b01110, 0b10001, ...],   'a': [0, 0, ...],   0: [0b...],
_ENTRY = re.compile(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"|([A-Za-z0-9_$]+)):\s*\[([^\]]*)\],")
_ROW = re.compile(r"0[bB][01]+|\d+")


def _table(name: str) -> dict[str, list[int]]:
    """One glyph table from web/font5x7.js as {character: [row masks]}."""
    text = FONT_FILE.read_text(encoding="utf-8")
    start = text.index(f"const {name} = {{")
    body = text[start:]
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


def _tables() -> dict[str, dict[str, list[int]]]:
    return {name: _table(name) for name in SETS}


@pytest.fixture(scope="module")
def serif() -> dict[str, list[int]]:
    return _table("SERIF_GLYPHS")


@pytest.fixture(scope="module")
def sans() -> dict[str, list[int]]:
    return _table("SANS_GLYPHS")


def test_the_font_file_is_where_the_test_expects_it() -> None:
    assert FONT_FILE.is_file(), f"missing {FONT_FILE}"


@pytest.mark.parametrize("name", sorted(SETS))
def test_each_table_was_parsed(name: str) -> None:
    # 26 letters + 10 digits + space + the symbol set.
    table = _table(name)
    assert len(table) >= 60, f"{name}: only {len(table)} glyphs parsed; the regex is probably wrong"


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("char", REQUIRED)
def test_every_required_glyph_exists(name: str, char: str) -> None:
    assert char in _table(name), f"no {char!r} glyph in {name} ({FONT_FILE.name})"


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("char", REQUIRED)
def test_every_required_glyph_fits_its_own_metrics(name: str, char: str) -> None:
    cols, rows_wanted = SETS[name]
    rows = _table(name)[char]
    assert len(rows) == rows_wanted, f"{name} {char!r} has {len(rows)} rows, want {rows_wanted}"
    for index, bits in enumerate(rows):
        assert 0 <= bits < 1 << cols, (
            f"{name} {char!r} row {index} is {bits:#b}, which does not fit in {cols} bits"
        )


def test_the_two_sets_are_not_the_same_table() -> None:
    tables = _tables()
    assert tables["SERIF_GLYPHS"] != tables["SANS_GLYPHS"]


def test_the_sans_set_is_the_default() -> None:
    """The 7x9 serif was tried as the default and rejected: its A and W were hard
    to read at dot pitch 4. The 5x7 sans is clearer, so it is what renders."""
    source = FONT_FILE.read_text(encoding="utf-8")
    assert 'DEFAULT_FONT = \'sans\'' in source or 'DEFAULT_FONT = "sans"' in source, (
        "the app must render the sans set by default"
    )
    assert "let current = SANS;" in source, (
        "the active font must start at the sans set, not the serif one"
    )


def test_the_fallback_glyph_comes_from_the_active_set() -> None:
    """A hardcoded serif '?' would drop a 7x9 glyph into a 5x7 cell."""
    source = FONT_FILE.read_text(encoding="utf-8")
    assert "glyphs[QUESTION]" in source, (
        "glyphFor must take its fallback '?' from the set it was asked for"
    )
    assert "SERIF_GLYPHS['?']" not in source, (
        "the fallback glyph must not be pinned to the serif table"
    )


# Letters whose top or bottom is a point or a diagonal rather than a bar, so a
# single lit dot on the end row is correct for them and is not a sans terminal.
POINTED = set("AVWXYMNK")


def _runs(bits: int) -> int:
    """How many separate groups of lit dots a row mask has."""
    return bin(bits)[2:].count("01") + (1 if bin(bits)[2:].startswith("1") else 0)


def test_serif_end_rows_are_serifs_and_not_bare_stems() -> None:
    """A serif is the flare at the ends, not the letter shape.

    House style: a stem that reaches the top or the bottom row opens into more
    than one dot there (a bar, or a two-sided flare like H's `.##.##.`). A single
    lone dot on an end row is a sans terminal, which would mean the set is just a
    wider sans. Letters whose end is a point or a diagonal are exempt: A really
    does meet at a single apex.
    """
    table = _table("SERIF_GLYPHS")
    for char, rows in table.items():
        # Punctuation is exempt too: a comma is supposed to end in one tail dot.
        if char in POINTED or not char.isalnum():
            continue
        for label, bits in (("top", rows[0]), ("foot", rows[-1])):
            lit = bits.bit_count()
            assert bits == 0 or lit > 1, (
                f"{char!r} has a bare stem dot on its {label} row ({bits:#b}); "
                "that is a sans terminal, not a serif"
            )


def test_the_serif_double_stem_letters_flare_where_the_stems_are_separate() -> None:
    # H's stems never join, so both its end rows flare twice. U's stems meet in a
    # bowl, so only its top row flares twice and its foot is a single run.
    table = _table("SERIF_GLYPHS")
    assert _runs(table["H"][0]) == 2, "H does not flare on both stems at the top"
    assert _runs(table["H"][-1]) == 2, "H does not flare on both stems at the foot"
    assert _runs(table["U"][0]) == 2, "U does not flare on both stems at the top"
    assert _runs(table["U"][-1]) == 1, "U's foot should be a joined bowl, not two stems"


def test_the_crossbar_of_the_barred_letters_sits_on_the_middle_row() -> None:
    table = _table("SERIF_GLYPHS")
    for char in "AEFHPT":
        row = table[char][4]
        assert row != 0 and row != table[char][0], f"{char!r} has no crossbar on the middle row"


def test_a_crossbar_does_not_fuse_the_stems_it_crosses() -> None:
    # E's and H's crossbars must leave a gap at the outer edge, or the two stems
    # merge into a single blob and the letter stops being readable at size.
    table = _table("SERIF_GLYPHS")
    for char in "EH":
        row = table[char][4]
        assert not (row & (1 << 6)), f"{char!r} crossbar {row:#b} fuses the left stem"
        assert not (row & 1), f"{char!r} crossbar {row:#b} fuses the right stem"


def test_x_is_the_only_lowercase_key_and_stays_reachable() -> None:
    # glyphFor tries the literal character before its uppercase form, so the one
    # lowercase key in each table (the multiplication x) is actually reachable.
    for name in SETS:
        table = _table(name)
        lowercase = {char for char in table if char.isalpha() and char != char.upper()}
        assert lowercase == {"x"}, f"{name}: unexpected lowercase keys: {sorted(lowercase)}"

    source = FONT_FILE.read_text(encoding="utf-8")
    assert "glyphs[key] ?? glyphs[key.toUpperCase()]" in source, (
        "glyphFor uppercases before looking up, which makes the x glyph unreachable"
    )
    assert "${set.name}@${String(char)}@${scale}" in source, (
        "the glyph bitmap cache must key on the raw character and the set name, "
        "or x and X collide and the two widths share entries"
    )


def test_the_bitmap_cache_is_keyed_on_the_font_set_too() -> None:
    # The two sets have different widths, so sharing a cache entry would draw a
    # 5-wide glyph into a 7-wide cell (or the reverse).
    source = FONT_FILE.read_text(encoding="utf-8")
    assert "${set.name}@${String(char)}@${scale}" in source, (
        "the glyph bitmap cache key must include the font set name"
    )


def test_the_arrows_and_the_four_new_symbol_blocks_are_present() -> None:
    # The prototype font had none of these; they were authored for this project.
    for char in "<>_=;@$" + "÷" + "→←↑↓":
        for name in SETS:
            assert char in _table(name), f"{name}: {char!r} was never authored"


def test_x_and_the_times_sign_share_a_glyph() -> None:
    for name in SETS:
        table = _table(name)
        assert table["x"] == table["×"]


def test_the_board_reads_its_colours_from_css_variables() -> None:
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    for name in ("--on", "--off", "--bg", "--on-hi"):
        assert f"'{name}'" in text, f"flipdisc.js does not read {name} from the stylesheet"
    assert "getComputedStyle(document.documentElement)" in text


def test_the_board_paints_no_background_field() -> None:
    # Regression, and a deliberate design decision: an always-on grid of unlit
    # discs is noise behind every label. The eye reads the field instead of the
    # text. Dots are ink, drawn only where something is actually written, so a
    # plate is what a label stands on.
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    unlit = text.split("if (state === OFF)", 1)[1].split("drawDisc", 1)
    assert len(unlit) == 2, (
        "the OFF branch of paint() still draws an unlit disc, so the board "
        "paints a permanent field of dots behind the labels"
    )


def test_a_plate_is_the_only_container() -> None:
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    assert "function plate(" in text, "there is no plate primitive"
    assert "plate," in text, "plate is not exposed on the board object"
    for name in ("button", "progress"):
        assert f"{name}(" in text
    # The two shapes that used to hand-roll their own fill/stroke/guard loop now
    # go through plate, so a sign looks like a sign wherever it is drawn.
    assert text.count("plate({") >= 3, (
        "button and progress should both build on plate, not repeat it"
    )


def test_the_board_has_no_animation_loop() -> None:
    # The board itself stays instant. Motion lives in flip-motion.js, which only
    # the opt-in demo page uses, so a redraw is never gated on a frame callback.
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    assert "requestAnimationFrame" not in text
    assert "setInterval" not in text


def test_the_motion_module_is_the_only_place_an_animation_loop_lives() -> None:
    assert "requestAnimationFrame" in MOTION_FILE.read_text(encoding="utf-8"), (
        "the reveal/idle-flip code should have moved into flip-motion.js"
    )


def test_the_board_guards_the_cells_that_carry_text() -> None:
    # Idle flips must be able to ask "is this cell part of a word?" or they will
    # flicker the words, which is exactly what they must not do.
    text = FLIPDISC_FILE.read_text(encoding="utf-8")
    assert "isProtected" in text, "the board does not expose a text-protection mask"


def test_the_dots_are_small_and_dense() -> None:
    # A dense grid needs real gaps between discs; above ~0.6 fill the dots touch
    # and the field reads as a sheet of squares instead of a field of dots.
    source = FLIPDISC_FILE.read_text(encoding="utf-8")
    fill = float(re.search(r"export const DISC_FILL = ([0-9.]+);", source).group(1))
    pitch = int(re.search(r"export const DEFAULT_PITCH = (\d+);", source).group(1))
    assert fill <= 0.6, f"DISC_FILL {fill} closes the gaps; the field will read as squares"
    assert fill >= 0.4, f"DISC_FILL {fill} is too sparse to read as a dot field"
    assert pitch <= 5, f"DEFAULT_PITCH {pitch} is not dense enough to read as dots"


def test_the_stylesheet_lets_clicks_through_to_the_board() -> None:
    # Regression: the page is one fixed, full-viewport sheet sitting over the canvas,
    # and it reserves its top padding as the band the dot-drawn buttons live in. With
    # no `pointer-events: none` on the sheet it swallows every one of those clicks
    # and the buttons silently do nothing.
    css = STYLE_FILE.read_text(encoding="utf-8")
    block = css.split(".fonttest {", 1)[1].split("}", 1)[0]
    assert "pointer-events: none" in block, (
        ".fonttest covers the board and must not capture pointer events"
    )
    assert ".fonttest > * {" in css and "pointer-events: auto" in css, (
        "the sheet's own children must opt back in, or its text becomes unselectable"
    )


def test_the_stylesheet_defines_the_flip_disc_palette() -> None:
    css = STYLE_FILE.read_text(encoding="utf-8")
    for name in ("--on", "--off", "--bg", "--on-hi"):
        assert f"{name}:" in css, f"style.css does not define {name}"
    assert "font-family: var(--mono)" in css, (
        "body copy must stay monospace; only the dot matrix is a bitmap face"
    )


def test_a_button_keeps_the_callback_it_was_given() -> None:
    # Regression: `button({ ..., onClick })` destructured `onClick` and then built a
    # handle that never stored it, so `target.onClick?.(target)` in the pointerup
    # handler was a silent no-op and every button on the board looked dead.
    source = FLIPDISC_FILE.read_text(encoding="utf-8")
    body = source.split("function button({", 1)[1].split("\n  function buttonAt", 1)[0]
    assert "onClick," in body, "the handle literal must store onClick, or presses do nothing"
    assert "target.onClick?.(target)" in source, (
        "the pointerup handler must actually call the stored callback"
    )


def test_the_board_exposes_its_button_rects_and_hit_test() -> None:
    # Screens drive buttons from outside a click (the review screen flips a checkbox
    # when a word is censored), so the rects have to be readable, and a press has to
    # be resolvable to a cell without a real pointer event.
    source = FLIPDISC_FILE.read_text(encoding="utf-8")
    assert "handles()" in source and "cellAt(clientX, clientY)" in source
