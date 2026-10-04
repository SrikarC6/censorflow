"""The dot-matrix fonts have to be complete before any screen depends on them.

There is no JavaScript test runner in this project, so this reads
`web/font5x7.js` as text and checks both font tables directly. A typo in one
bitmask row would otherwise only show up as a subtly wrong letter on a canvas.

Two sets live in the file: `SANS` (5x7, the default) and `SERIF` (7x9, behind
the toggle on the test page). They have different metrics, so the shape assertions
are parameterised per set.
"""

from __future__ import annotations

import re

import pytest

from censorflow import config

FONT_FILE = config.WEB_DIR / "font5x7.js"
GLYPH_FILE = config.WEB_DIR / "font-glyphs.js"
FLIPDISC_FILE = config.WEB_DIR / "flipdisc.js"
BOARD_FILES = ("flipdisc.js", "board-paint.js", "board-controls.js", "board-field.js")


def _board_source() -> str:
    """The board, including the modules it was split into."""
    return "\n".join((config.WEB_DIR / name).read_text(encoding="utf-8") for name in BOARD_FILES)
MOTION_FILE = config.WEB_DIR / "flip-motion.js"
SOUND_FILE = config.WEB_DIR / "flip-sound.js"
STYLE_FILE = config.WEB_DIR / "style.css"
FONT_TEST = config.WEB_DIR / "font-test.html"

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
    """One glyph table from web/font-glyphs.js as {character: [row masks]}."""
    text = GLYPH_FILE.read_text(encoding="utf-8")
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
    text = _board_source()
    for name in ("--on", "--off", "--bg", "--on-hi"):
        assert f"'{name}'" in text, f"flipdisc.js does not read {name} from the stylesheet"
    assert "getComputedStyle(document.documentElement)" in text


def test_the_board_paints_no_background_field() -> None:
    # Regression, and a deliberate design decision: an always-on grid of unlit
    # discs is noise behind every label. The eye reads the field instead of the
    # text. Dots are ink, drawn only where something is actually written, so a
    # plate is what a label stands on.
    text = _board_source()
    unlit = text.split("if (state === OFF)", 1)[1].split("drawDisc", 1)
    assert len(unlit) == 2, (
        "the OFF branch of paint() still draws an unlit disc, so the board "
        "paints a permanent field of dots behind the labels"
    )


def test_a_plate_is_the_only_container() -> None:
    text = _board_source()
    assert "function plate(" in text, "there is no plate primitive"
    assert "plate," in text, "plate is not exposed on the board object"
    for name in ("button", "progress"):
        assert f"{name}(" in text
    # The two shapes that used to hand-roll their own fill/stroke/guard loop now
    # go through plate, so a sign looks like a sign wherever it is drawn.
    assert text.count("plate({") >= 3, (
        "button and progress should both build on plate, not repeat it"
    )


def test_every_cell_is_painted_as_a_disc_and_never_as_a_square() -> None:
    # The bug this pins: paint() filled a lit cell with `ctx.fillStyle = colours.on`
    # and then drew the highlight, so every dot on the board came out as an amber
    # square. A flip-disc display made of squares is not a flip-disc display, and
    # the gaps between flaps are the whole texture. So: the only fill a cell gets
    # is the background erase, and the state is then drawn with drawDisc.
    text = _board_source()
    block = text.split("function paint(col, row)", 1)[1].split("function repaintAll", 1)[0]
    assert "ctx.fillStyle = colours.on" not in block, (
        "paint() fills a lit cell with the lit colour, which paints a square"
    )
    assert "ctx.fillStyle = state === ON" not in block, (
        "paint() derives the fill colour from the cell state; a lit cell must be "
        "erased to the background and then drawn as a disc"
    )
    assert "drawDisc(env.ctx, cx, cy, env.radius, ink)" in block, (
        "a lit cell must be a disc"
    )


def test_an_inverted_cell_is_a_hole_wider_than_the_flap_it_covers() -> None:
    # Hovering a plate lights its interior and stamps the label INV. If the
    # inverted disc were the same size as the lit one underneath, antialiasing
    # would leave an amber rim and the label would read as a smudge.
    text = _board_source()
    block = text.split("if (state === INV)", 1)[1].split("const ink =", 1)[0]
    assert "radius * INV_OVERDRAW" in block, (
        "an inverted cell must overdraw the flap beneath it"
    )
    assert "const INV_OVERDRAW = 1.16;" in text


def test_the_lit_cells_of_a_tile_are_discs_too() -> None:
    # renderField had the same square bug: a lit cell was filled with the lit
    # colour to erase the unlit disc underneath, which made the lit dots square.
    text = _board_source()
    block = text.split("export function renderField(", 1)[1].split("function drawDisc", 1)[0]
    assert "ctx.fillStyle = colours.on;\n      ctx.fillRect" not in block, (
        "renderField fills a lit cell with the lit colour, which paints a square"
    )
    assert (
        "drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, ink ?? colours.on)" in block
    ), "a lit cell in a tile must be a disc"


def test_sound_is_wired_up_and_the_wipe_and_the_idle_flips_are_gone() -> None:
    # Sound was asked for back: every press clicks. The wipe and the idle flips
    # were both dropped - the board is bare, so a full-field wipe has nothing to
    # wipe and a lone flipping disc has nothing to flip - which is why neither is
    # called even though `fullWipe` and `startIdleFlips` still exist in the module.
    page = (config.WEB_DIR / "font-test.html").read_text(encoding="utf-8")
    assert "from './flip-sound.js'" in page
    assert "playRowFlip(" in page
    assert "subscribeSound(" in page
    assert "from './flip-motion.js'" in page
    assert "fullWipe" not in page, "the wipe is meant to be gone from this page"
    assert "startIdleFlips" not in page, "idle flips are meant to be gone too"
    assert "animate" not in page.lower().replace("animation", ""), (
        "no animation toggle is meant to be left on the page"
    )


def test_a_sound_toggle_is_clickable_in_both_states() -> None:
    # Regression. The toggle greyed its own label out when sound was off, and a
    # greyed button is a disabled button: the hit test skips it. So the one control
    # you need in order to switch the sound on was the one control you could not
    # press. State now goes in the border colour instead.
    text = _board_source()
    hit = text.split("function buttonAt(col, row)", 1)[1].split("\n  function ", 1)[0]
    assert "handle.enabled === false" in hit, (
        "hit testing still skips disabled buttons, so a toggle must never be disabled"
    )
    page = (config.WEB_DIR / "font-test.html").read_text(encoding="utf-8")
    assert "soundBtn.setEnabled" not in page, (
        "the sound toggle must not be disabled to show its state"
    )
    assert "soundBtn.setTone(on ? 'go' : 'stop')" in page


def test_a_plate_border_is_a_hairline_and_not_a_row_of_dots() -> None:
    # The dot frame read as a beaded edge rather than as the side of a panel. The
    # border is drawn, one CSS pixel, per cell edge - the same box as the `.chip`
    # outline in the stylesheet.
    text = _board_source()
    assert "const PLATE_LINE = 1;" in text
    assert "function drawPanelEdges(panel, col, row, x, y)" in text
    block = text.split("function drawPanelEdges", 1)[1].split("function toneColour", 1)[0]
    assert "ctx.fillStyle = panel.border;" in block
    for edge in ("col === panel.col", "col === panel.col + panel.cols - 1",
                 "row === panel.row", "row === panel.row + panel.rows - 1"):
        assert edge in block, f"the plate is missing its {edge} edge"
    assert "stroke(col, row" not in text.split("function plate(", 1)[1].split("panels", 1)[0], (
        "plate must not draw its border out of cells any more"
    )


def test_a_plate_border_colour_comes_from_the_same_variables_as_the_chips() -> None:
    style = STYLE_FILE.read_text(encoding="utf-8")
    for name in ("--plate-bg", "--plate-line", "--go", "--stop"):
        assert f"{name}:" in style, f"the stylesheet does not define {name}"
    assert ".fonttest .chip.go" in style and ".fonttest .chip.stop" in style, (
        "the HTML specimens must show the two semantic plates"
    )
    text = _board_source()
    for name in ("--plate-bg", "--plate-line", "--go", "--stop"):
        assert f"'{name}'" in text, f"flipdisc.js does not read {name}"
    assert "TONE_GO" in text and "TONE_STOP" in text and "TONE_PLAIN" in text
    assert "export const TONE_GO" in text


def test_the_knockout_is_the_plate_colour_not_whatever_the_plate_is_lit_with() -> None:
    # Regression. The inverted cell was drawn in `panel.fill`, which for a hovered
    # button is the tone it lit up in - green dots on a green plate, so the label
    # vanished exactly when you were pressing it.
    text = _board_source()
    block = text.split("if (state === INV)", 1)[1].split("const ink =", 1)[0]
    assert "colours.plateBg" in block
    assert "panel.fill" not in block


def test_a_toned_sign_letters_itself_in_its_own_colour() -> None:
    # A green frame around amber dots reads as two objects bolted together; a
    # green frame around green dots reads as one sign. The plate owns the ink
    # colour, so a toned button and an HTML chip can agree.
    text = _board_source()
    assert "ink = null" in text.split("function plate(", 1)[1].split("const record", 1)[0]
    assert "panel && panel.ink ? panel.ink : env.colours.on" in text
    draw = text.split("function draw()", 1)[1].split("stampText(handle.label", 1)[0]
    assert "handle.tone !== TONE_PLAIN" in draw
    assert "toneColour(handle.tone)" in draw
    # Lit, the plate fills and the label is knocked out, so the ink is dropped again.
    assert "tone: lit ? TONE_PLAIN : handle.tone" in draw
    # A tinted disc skips the specular highlight, which belongs to amber flaps.
    assert "if (ink === env.colours.on) drawHighlight" in text
    # renderField takes the same option so an HTML chip can be lettered too.
    assert "paintField = true, ink = null" in text
    page = FONT_TEST.read_text(encoding="utf-8")
    assert "ink: tone ? board.colours[tone] : null" in page
    style = STYLE_FILE.read_text(encoding="utf-8")
    assert "outline-color: var(--go);\n  color: var(--go);" in style
    assert "outline-color: var(--stop);\n  color: var(--stop);" in style


def test_the_banner_scrolls_the_whole_caption_with_no_seam() -> None:
    # Regression. The strip was one caption long, so once the offset passed the end
    # of the text the right-hand side of the sign went blank and the caption jumped
    # back to the left. Each cell is now offered at two positions, one repeat
    # apart, so the strip is periodic and the wrap cannot be seen.
    motion = MOTION_FILE.read_text(encoding="utf-8")
    assert "export function startMarquee(" in motion
    # A short title on a wide sign needs more than two copies, or the right side
    # stays blank. The period is one caption plus its gap, so the wrap has no seam.
    assert "Math.ceil(visible / one.width) + 1" in motion
    assert "offset % one.width" in motion
    assert "key: 'marquee'" in motion, (
        "the banner re-plates on every tick; without a key it would append a panel "
        "per tick and the board's panel list would grow without bound"
    )
    assert "prefersReducedMotion()" in motion.split("export function startMarquee", 1)[1]
    page = (config.WEB_DIR / "font-test.html").read_text(encoding="utf-8")
    assert "startMarquee(" in page
    assert "THE PREMIERE MUSIC FILE CENSORER" in page


def test_running_prose_is_allowed_to_grow_but_tiles_may_not() -> None:
    # Regression. Notes had a fixed whole-dot height so the tiles below them stayed
    # on the grid, which silently clipped any paragraph longer than a few lines -
    # and the board's own text then printed straight through the gap.
    style = STYLE_FILE.read_text(encoding="utf-8")
    note = style.split(".fonttest .note {", 1)[1].split("}", 1)[0]
    assert "min-height" in note
    # `line-height` would satisfy a naive search for "height:", so match the
    # property on its own.
    assert not [line for line in note.splitlines() if line.strip().startswith("height:")]
    assert "overflow: hidden" not in note
    tiles = style.split(".fonttest .tiles {", 1)[1].split("}", 1)[0]
    caps = style.split(".fonttest .caps {", 1)[1].split("}", 1)[0]
    assert "height: calc(var(--pad, 4px) * 3)" in caps, (
        "the caption row is whole-dot sized on purpose and must stay that way"
    )
    assert "padding: var(--pad, 4px)" in tiles


def test_tiles_keep_the_field_that_the_board_dropped() -> None:
    # The two are deliberately different. The board is bare because a full-window
    # field is noise behind every label. A specimen tile keeps its field because a
    # glyph is only legible against the whole matrix - strip the texture and you
    # hide the exact thing you came to inspect. So: no field on the board, a field
    # in the tiles.
    board = _board_source()
    unlit = board.split("if (state === OFF)", 1)[1].split("drawDisc", 1)
    assert len(unlit) == 2, "the board is painting a field again"

    page = (config.WEB_DIR / "font-test.html").read_text(encoding="utf-8")
    tile = page.split("function tileCanvas", 1)[1].split("return canvas;", 1)[0]
    assert "paintField: false" not in tile, (
        "tileCanvas must paint its field; a specimen without its matrix behind it "
        "cannot be judged for legibility"
    )
    assert "renderField(canvas, {" in tile


def test_the_board_has_no_animation_loop() -> None:
    # The board itself stays instant. Motion lives in flip-motion.js, which only
    # the opt-in demo page uses, so a redraw is never gated on a frame callback.
    text = _board_source()
    assert "requestAnimationFrame" not in text
    assert "setInterval" not in text


def test_the_motion_module_is_the_only_place_an_animation_loop_lives() -> None:
    assert "requestAnimationFrame" in MOTION_FILE.read_text(encoding="utf-8"), (
        "the reveal/idle-flip code should have moved into flip-motion.js"
    )


def test_the_board_guards_the_cells_that_carry_text() -> None:
    # Idle flips must be able to ask "is this cell part of a word?" or they will
    # flicker the words, which is exactly what they must not do.
    text = _board_source()
    assert "isProtected" in text, "the board does not expose a text-protection mask"


def test_the_dots_are_small_and_dense() -> None:
    # A dense grid needs real gaps between discs; above ~0.6 fill the dots touch
    # and the field reads as a sheet of squares instead of a field of dots.
    source = _board_source()
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


def test_a_hidden_button_is_not_hit() -> None:
    # Regression: hide() stopped drawing a button but not hitting it. Review opens
    # via the awaiting screen, which parks ANOTHER SONG in the same band as RENDER,
    # so the click went to startUpload and the homepage instead of the render.
    source = _board_source()
    body = source.split("function buttonAt(col, row)", 1)[1].split("\n  function ", 1)[0]
    assert "!handle.shown" in body


def test_a_button_keeps_the_callback_it_was_given() -> None:
    # Regression: `button({ ..., onClick })` destructured `onClick` and then built a
    # handle that never stored it, so `target.onClick?.(target)` in the pointerup
    # handler was a silent no-op and every button on the board looked dead.
    source = _board_source()
    body = source.split("function button({", 1)[1].split("\n  function buttonAt", 1)[0]
    assert "onClick," in body, "the handle literal must store onClick, or presses do nothing"
    assert "target.onClick?.(target)" in source, (
        "the pointerup handler must actually call the stored callback"
    )


def test_the_board_exposes_its_button_rects_and_hit_test() -> None:
    # Screens drive buttons from outside a click (the review screen flips a checkbox
    # when a word is censored), so the rects have to be readable, and a press has to
    # be resolvable to a cell without a real pointer event.
    source = _board_source()
    assert "handles()" in source and "cellAt(clientX, clientY)" in source
