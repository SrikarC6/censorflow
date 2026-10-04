"""The screens and the API client have to agree with the server they talk to.

There is no JavaScript test runner in this project, so this reads `web/*.js` as
text and checks the wiring statically: every path the client asks for has to be a
route the server actually serves, every state the Processing screen lists has to be
a state the pipeline can be in, and every screen a button can jump to has to be
registered. Each of those is a mismatch that would show up only as a dead click at
runtime.

`tests/test_server.py` covers the routes themselves from the server's side.
"""

from __future__ import annotations

import inspect
import re

import pytest

from censorflow import config, jobs
from censorflow.server import create_app

API_FILE = config.WEB_DIR / "api.js"
UI_FILE = config.WEB_DIR / "ui.js"
APP_FILE = config.WEB_DIR / "app.js"
BOARD_FILE = config.WEB_DIR / "flipdisc.js"
INDEX_FILE = config.WEB_DIR / "index.html"

STYLES = (
    "ui.js",
    "app.js",
    "screens.js",
    "session.js",
    "review.js",
    "review-dom.js",
    "stems.js",
    "model.js",
    "board-paint.js",
    "board-controls.js",
    "board-field.js",
)
REVIEW_FILE = config.WEB_DIR / "review.js"
# The flow used to live in app.js. Painters are screens.js; clicks are session.js.
FLOW_FILES = ("app.js", "screens.js", "session.js")
REVIEW_FILES = ("review.js", "review-dom.js")


def _read(name: str) -> str:
    return (config.WEB_DIR / name).read_text(encoding="utf-8")


def _flow() -> str:
    """app.js plus the two modules it was split into, in import order."""
    return "\n".join(_read(name) for name in FLOW_FILES)


def _review() -> str:
    """review.js plus the HTML builders it was split into."""
    return "\n".join(_read(name) for name in REVIEW_FILES)


@pytest.fixture(scope="module")
def routes() -> set[str]:
    """Every path the FastAPI app serves, with the `{...}` placeholders kept."""
    paths = create_app().openapi()["paths"]
    return set(paths)


# --- the API client only asks for routes that exist --------------------------


def _calls(text: str) -> set[str]:
    """Every server path the client mentions, with ids already templated."""
    # Interpolated paths are written `/api/jobs/${id}/clip`, so the `${...}` is
    # swapped for the server's own placeholder before the path is read off.
    text = re.sub(r"\$\{[^}]*\}", "{job_id}", text)
    return set(re.findall(r"['\"`](/api/[A-Za-z0-9/{}._-]*)", text))


def test_every_path_the_client_asks_for_is_a_route() -> None:
    served = {
        "/api/health",
        "/api/upload",
        "/api/jobs",
        "/api/jobs/{job_id}",
        "/api/jobs/{job_id}/events",
        "/api/jobs/{job_id}/review",
        "/api/jobs/{job_id}/clip",
        "/api/jobs/{job_id}/output",
        "/api/jobs/{job_id}/original",
        "/api/models/asr",
    }
    used = _calls(_read("api.js"))
    assert used, "no paths found in api.js at all"
    assert used == served


def test_the_openapi_schema_and_the_client_agree(routes: set[str]) -> None:
    used = _calls(_read("api.js"))
    assert used <= routes, f"client asks for paths the server does not serve: {used - routes}"


def test_the_client_awaits_the_request_before_reading_it() -> None:
    body = _read("api.js").split("async function json(", 1)[1]
    # Without the await, `response` is a Promise, `.ok` is undefined and every
    # call rejects with "request failed (undefined)".
    assert "await request" in body
    assert "const response = await request;" in body


def test_the_event_stream_is_closed_when_the_job_ends() -> None:
    text = _read("api.js")
    assert "new EventSource(" in text
    assert "source.close()" in text
    assert "payload.event === 'done'" in text


def test_an_upload_uses_xmlhttprequest_because_fetch_cannot_report_progress() -> None:
    text = _read("api.js")
    assert "new XMLHttpRequest()" in text
    assert "upload.addEventListener('progress'" in text


# --- the screens agree with the pipeline -------------------------------------


def _listed_stages() -> list[str]:
    text = _read("screens.js")
    listed = re.search(r"const STAGES = \[([^\]]*)\]", text)
    assert listed is not None, "screens.js no longer declares STAGES"
    return [item.strip().strip("\"'") for item in listed.group(1).split(",") if item.strip()]


def _pipeline_stages() -> list[str]:
    """The stages pipeline.run_censor announces, in the order it announces them."""
    from censorflow import pipeline

    source = inspect.getsource(pipeline.run_censor)
    return re.findall(r'_stage\(on_stage, "(\w+)"\)', source)


def test_every_stage_the_processing_screen_lists_is_a_real_state() -> None:
    stages = _listed_stages()
    assert stages, "STAGES is empty"
    for stage in stages:
        assert stage in {state.value for state in jobs.State}, stage


def test_the_stages_are_listed_in_the_order_they_run() -> None:
    # `rendering` happens after the review pause, which is its own screen, so the
    # processing screen lists everything up to the pause and nothing after it.
    order = _pipeline_stages()
    assert "rendering" in order
    assert _listed_stages() == [stage for stage in order if stage != "rendering"]


# Screens are registered and shown from several modules: screens.js owns the flow,
# session.js shows a screen when a job event arrives, review.js owns the review
# and render screens, and stems.js owns the skeleton.
SCREEN_MODULES = ("app.js", "screens.js", "session.js", "review.js", "stems.js")

# A screen that nothing can reach is dead code that still looks finished.
PENDING_SCREENS: dict[str, str] = {}


def test_every_screen_a_button_can_reach_is_registered() -> None:
    sources = "".join(_read(name) for name in SCREEN_MODULES)
    registered = set(re.findall(r"ui\.register\('([a-z]+)'", sources))
    shown = set(re.findall(r"ui\.show\('([a-z]+)'", sources))
    assert registered, "no screens registered"
    assert shown <= registered, f"shown but never registered: {shown - registered}"
    unreachable = registered - shown
    assert unreachable == set(PENDING_SCREENS), f"registered but never shown: {unreachable}"


def test_the_stems_mode_opens_a_screen_and_does_not_request() -> None:
    # The stem routes answer 501. The button opens the skeleton screen.
    body = _read("app.js").split("const stemsMode = board.button({", 1)[1]
    body = body.split("\n});", 1)[0]
    assert "ui.show('stems')" in body
    assert "api." not in body
    screen = _read("stems.js")
    assert "setEnabled(false)" in screen
    assert "COMING SOON" in screen
    assert "api." not in screen
    checklist = (config.PROJECT_DIR / "docs" / "STEMS_TODO.md").read_text(encoding="utf-8")
    for line in (
        "0-200 %",
        "mute and isolate",
        "Keys 1-4",
        "Waveform scrubber",
        "Snippet mode",
        "Fast and Pro",
        "Batch folder",
        "Independent stem download",
    ):
        assert line in checklist


def test_the_mode_screen_colours_the_title_censor_stems_and_back() -> None:
    app = _read("app.js")
    censor = app.split("const censorMode = board.button({", 1)[1].split("\n});", 1)[0]
    assert "TONE_GO" not in censor
    stems = app.split("const stemsMode = board.button({", 1)[1].split("\n});", 1)[0]
    assert "knockout: true" in stems
    back = app.split("const cancelMode = board.button({", 1)[1].split("\n});", 1)[0]
    assert "PREVIOUS PAGE" in back
    assert "TONE_INFO" in back
    mode = _read("screens.js").split("ui.register('mode'", 1)[1].split("ui.register('processing'", 1)[0]
    assert "tone: TONE_GO" in mode
    assert "qualityFast.knockout" in mode


def test_the_processing_screen_lights_the_stage_the_job_is_in() -> None:
    body = _read("screens.js").split("ui.register('processing'", 1)[1].split("\n});", 1)[0]
    assert "snapshot.state === stage" in body
    assert "TONE_GO" in body


def test_a_status_line_is_cut_within_the_window_it_has() -> None:
    ui = _read("ui.js")
    assert "function fitLine(text, maxCols)" in ui
    # The ellipsis has to be counted in the width test, or adding it afterwards
    # grows the label past the width it was just fitted to.
    body = ui.split("function fitLine", 1)[1].split("\n}", 1)[0]
    assert body.index("...`") < body.index("kept = kept.slice")
    notice = ui.split("    notice(text, tone", 1)[1].split("\n    },", 1)[0]
    assert "fitLine(" in notice
    assert "board.rows - NOTICE_ROWS - 2" in notice, "the sign must not sit on the window edge"


def test_an_empty_status_line_draws_no_sign() -> None:
    body = _read("ui.js").split("notice(text, tone", 1)[1]
    assert "if (!spoken) return 0;" in body


# --- nothing may end up under the status line or off the window ---------------
#
# Both failures look the same to a user: a button that is drawn but cannot be
# clicked. Reproduced in headless Chrome at a 1000x420 window, where every screen's
# block is taller than the space available.


def test_a_button_row_is_clamped_above_the_status_line() -> None:
    ui = _read("ui.js")
    assert "bottom: () => Math.max(0, board.rows - NOTICE_ROWS - 2)" in ui
    body = ui.split("buttonRow(handles, row", 1)[1].split("\n    },", 1)[0]
    # The clamp has to be on the row that is placed, not on the cursor.
    assert "const at = Math.max(helpers.origin(), Math.min(row, helpers.bottom() - height));" in body
    assert "handle.place(cursor, at)" in body


def test_buttons_are_centred_from_their_own_width_and_not_guessed() -> None:
    ui = _read("ui.js")
    assert "centre(handles, { gap = 2 } = {})" in ui
    body = ui.split("centre(handles, { gap", 1)[1].split("\n    },", 1)[0]
    assert "handle.width" in body
    assert "handle.label" not in body, "the label length is not the button width"
    # No screen may go back to guessing a column from the half-width of its label.
    for name in ("app.js", "screens.js", "review.js", "stems.js"):
        assert "h.cols() / 2" not in _read(name), name


def test_every_button_row_is_centred_through_the_helper() -> None:
    for name in ("screens.js", "review.js", "stems.js"):
        calls = re.findall(r"h\.buttonRow\(.*?\);", _read(name), re.DOTALL)
        assert calls, f"{name} places no button rows"
        for call in calls:
            assert "h.centre(" in call, f"{name}: {call}"


def test_a_row_too_wide_for_the_window_says_so_rather_than_looking_dead() -> None:
    ui = _read("ui.js")
    # A button hanging off the right edge cannot be clicked and looks like it is
    # not there. Saying the window is too narrow is the only honest answer.
    assert "narrow = width > board.cols;" in ui
    assert "const spoken = narrow ? 'this window is too narrow - make it wider' : text;" in ui


def test_a_tight_window_drops_rows_rather_than_stacking_controls() -> None:
    # Two rows clamped onto the same space overlap, and only the first one drawn is
    # ever hit - so a screen that cannot fit must show fewer controls, not the same
    # controls closer together.
    ui = _read("ui.js")
    assert "tight(tall)" in ui
    assert "board.rows - NOTICE_ROWS - bannerRows() - tall < MIN_USABLE_ROWS" in ui
    assert "const MIN_USABLE_ROWS = 60;" in ui
    screens = _read("screens.js")
    assert screens.count("h.tight(") >= 3
    # Every screen with more than one row of controls asks.
    assert "h.tight(BLOCK.mode)" in screens
    assert "h.tight(BLOCK.awaiting)" in screens
    assert "h.tight(BLOCK.result)" in screens


def test_the_title_scrolls_and_other_signs_keep_one_size() -> None:
    # The title used to sit in the middle and grow with the window. Scale 3 drew
    # a 4x bitmap on a 3x stride, so a subtitle came out as overlapping noise.
    ui = _read("ui.js")
    assert "startMarquee(" in ui
    assert "BANNER_TEXT = 'CENSORFLOW'" in ui
    assert "BANNER_GAP = 40" in ui
    assert "const SIGN_SCALE = 2" in ui
    assert "fitText" not in ui
    welcome = _read("screens.js").split("ui.register('welcome'", 1)[1].split("ui.register('mode'", 1)[0]
    assert "h.sign('CENSORFLOW'" not in welcome
    assert "scale: 3" not in _read("review.js")


def test_the_install_is_checked_before_the_user_picks_a_song() -> None:
    # ffmpeg is a hard requirement and the model is a large download; both are
    # cheaper to find here than three stages into a job.
    app = _flow()
    body = app.split("async function checkInstall()", 1)[1].split("\n}", 1)[0]
    assert "api.health()" in body
    assert "report.reason" in body
    assert "TONE_STOP" in body
    assert "checkInstall()" in app


def test_an_unreachable_server_is_not_reported_as_a_broken_install() -> None:
    body = _flow().split("async function checkInstall()", 1)[1].split("\n}", 1)[0]
    assert "catch" in body
    assert body.index("catch") < body.index("report.reason")


def test_a_toned_sign_tints_its_lettering_and_not_only_its_border() -> None:
    # plate() takes the tone twice: `tone` paints the hairline, `ink` the dots.
    # Passing only one gives a red border with amber letters, which reads as two
    # opinions rather than one warning.
    ui = _read("ui.js")
    assert "function toneInk(tone, colours)" in ui
    for name in ("sign", "notice"):
        body = ui.split(f"    {name}(", 1)[1].split("\n    },", 1)[0]
        assert "ink: toneInk(tone, board.colours)" in body, name
    board = _read("board-controls.js")
    progress = board.split("function progress(", 1)[1].split("\n  }", 1)[0]
    assert "ink:" in progress


def test_a_button_is_created_once_and_placed_by_the_painter() -> None:
    # Creating a handle inside a painter leaks one per redraw, which is how the
    # buttons stopped responding once already.
    app = _flow()
    handles = re.findall(r"const (\w+) = board\.button\(\{", app)
    assert handles, "no buttons declared"
    assert len(handles) == len(set(handles)), "a button handle is declared twice"
    assert app.count("board.button({") == len(handles), "a button is created somewhere else"
    # Every handle is placed by a painter, in a buttonRow list.
    painters = app.split("ui.register", 1)[1]
    rows = [group for group in re.findall(r"buttonRow\(\[([^\]]*)\]", painters)]
    placed = {item.strip() for group in rows for item in group.split(",") if item.strip()}
    assert set(handles) == placed, f"never placed: {set(handles) - placed}"


def test_every_screen_that_draws_buttons_places_them_all() -> None:
    # A screen that forgets to place a button shows nothing rather than failing
    # loudly, so the button list of each painter is compared with the module list.
    app = _flow()
    handles = set(re.findall(r"const (\w+) = board\.button\(\{", app))
    for name in re.findall(r"ui\.register\('([a-z]+)'", app):
        body = app.split(f"ui.register('{name}'", 1)[1].split("\nui.register", 1)[0]
        used = set(re.findall(r"buttonRow\(\[([^\]]*)\]", body))
        flat = {item.strip() for group in used for item in group.split(",")}
        unknown = {item for item in flat if item and item not in handles}
        assert not unknown, f"screen {name} places unknown buttons {unknown}"


def test_the_ui_hides_the_previous_screen_s_buttons() -> None:
    ui = _read("ui.js")
    assert "clearButtons()" in ui
    assert "handle.hide()" in ui
    assert ui.index("clearButtons") < ui.index("show(name)")


# --- imports line up with exports --------------------------------------------


def test_every_name_app_js_imports_is_actually_exported() -> None:
    app = _read("app.js")
    imported: set[str] = set()
    for names, _module in re.findall(r"import \{([^}]*)\} from '\./(\w+\.js)'", app):
        for name in names.split(","):
            imported.add(name.strip())
    exported: set[str] = set()
    for name in (
        "api.js",
        "ui.js",
        "flipdisc.js",
        "review.js",
        "stems.js",
        "model.js",
        "screens.js",
        "session.js",
        "atmosphere.js",
        "welcome-scene.js",
    ):
        exported |= set(re.findall(r"export (?:async )?function (\w+)", _read(name)))
        exported |= set(re.findall(r"export class (\w+)", _read(name)))
        exported |= set(re.findall(r"export const (\w+)", _read(name)))
    # The API is a namespace import in the module that actually calls it.
    assert "import * as api from './api.js'" in _read("session.js")
    missing = {name for name in imported if name} - exported
    assert not missing, f"app.js imports names nothing exports: {missing}"


def test_the_ui_module_owns_the_state_the_screens_read() -> None:
    # review.js needs the same job and the same upload as app.js, so two copies of
    # "which song is this" would mean previewing the wrong one.
    ui = _read("ui.js")
    assert "export const state = {" in ui
    assert "export function createUi" in ui


def test_the_tones_the_screens_use_come_from_the_board() -> None:
    board = _read("flipdisc.js")
    for tone in ("TONE_GO", "TONE_PLAIN", "TONE_STOP", "TONE_INFO"):
        assert f"export const {tone}" in board or f"export {{ {tone}" in board, tone


# --- index.html --------------------------------------------------------------


def test_the_page_wires_up_the_canvas_the_overlay_and_the_file_input() -> None:
    html = _read("index.html")
    for element in ('id="board"', 'id="overlay"', 'id="file"', 'id="live"'):
        assert element in html
    assert '<script type="module" src="./app.js">' in html
    assert 'accept="audio/*' in html


def test_the_file_input_is_hidden_but_not_unreachable() -> None:
    html = _read("index.html")
    assert 'class="sr-only"' in html
    # ... and something actually clicks it.
    assert "fileInput.click()" in _read("app.js")


# --- the board's rules still hold --------------------------------------------


def test_the_board_has_no_animation_loop() -> None:
    for name in ("flipdisc.js", "board-paint.js", "board-controls.js", "board-field.js"):
        board = _read(name)
        assert "requestAnimationFrame" not in board, name
        assert "setInterval" not in board, name


def test_hovering_a_button_does_not_repaint_the_whole_board() -> None:
    # Hover used to call env.redraw(), which painted every disc while the banner
    # was already moving. The button now paints only its own plate.
    controls = _read("board-controls.js")
    assert "handle.repaint = () => env.redraw()" not in controls
    body = controls.split("handle.repaint =", 1)[1]
    assert "if (env.drawing) return;" in body
    assert "handle.draw();" in body
    paint = _read("board-paint.js")
    plate = paint.split("function plate(", 1)[1].split("function panelAt", 1)[0]
    assert "other.col === col" in plate
    assert "other.row === row" in plate
    assert "key," in plate.split("const record =", 1)[1].split("const existing", 1)[0]


def test_the_glow_is_a_few_elements_and_not_a_canvas_loop() -> None:
    # A requestAnimationFrame over the board would repaint every dot, on a
    # fanless laptop, to move a halo. The halo is HTML and only its opacity moves.
    text = _read("atmosphere.js")
    assert "requestAnimationFrame" not in text
    assert "shadowBlur" not in text
    assert "setInterval" not in text
    assert "spark" not in text
    style = (config.WEB_DIR / "style.css").read_text(encoding="utf-8")
    assert "glow-breathe" in style
    assert "animation: none !important" in style


def test_the_welcome_scene_moves_words_without_repainting_the_board() -> None:
    # The n-word block in the word list must not appear, even masked.
    text = _read("welcome-scene.js").lower()
    assert "requestanimationframe" not in text
    assert "setinterval" not in text
    assert "settimeout" in text
    assert "nigg" not in text
    assert "f**k" in text


def test_the_screens_do_not_animate_either() -> None:
    for name in STYLES:
        text = _read(name)
        assert "requestAnimationFrame" not in text, name
        assert "setInterval" not in text, name
        assert ".style.opacity" not in text, name


def test_no_debug_output_was_left_in_the_web_sources() -> None:
    for name in (
        "api.js",
        "ui.js",
        "app.js",
        "screens.js",
        "session.js",
        "review.js",
        "review-dom.js",
        "flipdisc.js",
        "board-paint.js",
        "board-controls.js",
        "board-field.js",
    ):
        text = _read(name)
        assert "console.log" not in text, name
        assert "debugger" not in text, name


def test_the_board_still_offers_a_hit_test_and_a_sounding_surface() -> None:
    board = _read("flipdisc.js")
    assert "handles()" in board
    assert "allButtons()" in board
    assert "shown" in board


# --- the resume path ---------------------------------------------------------


def test_a_job_can_be_picked_back_up_from_the_query_string() -> None:
    app = _flow()
    assert "new URLSearchParams(window.location.search).get('job')" in app
    assert "api.getJob(id)" in app
    # A job that is waiting for review is picked up at the review screen, not at
    # the stage list it no longer has any stages left to show.
    assert "review.open(id)" in app


def test_a_refresh_does_not_throw_away_a_finished_render() -> None:
    """The whole point of coming back to `?job=` is to reach the file you already made."""
    app = _flow()
    assert "state_ === 'done'" in app
    assert "state.render = state.snapshot.render || state.render;" in app
    assert "ui.show('result')" in app.split("state_ === 'done'", 1)[1].split("awaiting_review", 1)[0]
    # A failed job is not a finished one: it has no render figures to show.
    assert "state_ === 'error'" in app


def test_the_ab_comparison_falls_back_to_the_served_original() -> None:
    """After a reload the browser's own copy of the upload is gone, not the song."""
    app = _flow()
    body = app.split("function playSource(kind)", 1)[1].split("\n}", 1)[0]
    assert "state.objectUrl || api.originalUrl(state.job.id)" in body
    assert "/api/jobs/${id}/original" in _read("api.js")


def test_the_download_says_the_name_the_file_will_have() -> None:
    app = _flow()
    body = app.split("function saveOutput()", 1)[1].split("\n}", 1)[0]
    assert "anchor.download = name || ''" in body
    assert "SAVED" in body
    assert "state.render?.filename" in body


def test_starting_again_releases_the_object_url_and_the_stream() -> None:
    body = _flow().split("function startUpload()", 1)[1].split("\n}", 1)[0]
    assert "URL.revokeObjectURL" in body
    assert "state.stopFollowing()" in body
    assert "review.reset()" in body
    assert "ui.show('welcome')" in body


# --- the review screen --------------------------------------------------------


def test_the_review_screen_is_asked_for_and_shown_from_app_js() -> None:
    app = _read("app.js")
    assert "import { registerReview } from './review.js'" in app
    # The job reaching `awaiting_review` goes straight to the review screen; there
    # is no "press a button to start reviewing" step in between. One call is the
    # button, the other is picking a job back up.
    assert _flow().count("review.open(") >= 2


def test_the_transcript_can_add_a_missed_flag_by_clicking_a_word() -> None:
    review = _review()
    # Every word is a button, so a word the model did not hear is one click away
    # from being censored.
    assert "span.className = 'w'" in review
    assert "flags.push({" in review
    assert "word_index: index" in review
    assert re.search(r"function toggleWord\(index, flag\)", review)


def test_an_existing_flag_is_switched_rather_than_duplicated() -> None:
    body = _review().split("function toggleWord(index, flag)", 1)[1]
    body = body.split("} else {", 1)[0]
    assert "flag.censor = !flag.censor" in body
    assert "flags.push(" not in body


def test_a_flag_row_can_switch_censor_edit_the_word_and_nudge_both_ends() -> None:
    review = _review()
    assert "box.addEventListener('change'" in review
    assert "field.addEventListener('change'" in review
    assert "flag[edge] = Math.max(0" in review
    # Nudging an edge must never invert the window; the server would reject it.
    assert "if (flag.end <= flag.start) flag.end = flag.start + NUDGE_S;" in review
    assert "const NUDGE_S = 0.01;" in review


def test_editing_a_word_never_moves_its_timing() -> None:
    body = _review().split("field.addEventListener('change'", 1)[1]
    body = body.split("\n    });", 1)[0]
    assert "flag.text = text;" in body
    assert "flag.start" not in body
    assert "flag.end" not in body


def test_a_flag_row_offers_both_previews_and_asks_for_padded_audio() -> None:
    review = _review()
    assert "preview('original', flag)" in review
    assert "preview('censored', flag)" in review
    assert "api.clipUrl(" in review
    assert "flag.start - PREVIEW_PAD_S" in review
    assert "const PREVIEW_PAD_S = 1.5;" in review


def test_a_lyrics_only_flag_says_where_it_came_from_and_to_verify_it() -> None:
    review = _review()
    assert "const BADGES = { asr: 'ASR', lyrics: 'LYRICS', both: 'BOTH' }" in review
    assert "if (flag.approx)" in review
    assert "verify.textContent = 'VERIFY'" in review


def test_the_censor_switch_is_sent_exactly_as_the_user_left_it() -> None:
    # The server recomputes whether a word is profane and honours the switch as
    # sent; the client must not second-guess either.
    review = _read("review.js")
    body = review.split("SENT.map", 1)[0].rsplit("api.postReview", 1)[0]
    assert "flags: flags.map((flag) => Object.fromEntries(SENT.map" in review
    assert "'censor'" in review.split("const SENT = ", 1)[1].split("]", 1)[0]
    assert body is not None


def test_the_review_panel_is_built_once_and_taken_down_when_leaving() -> None:
    review = _read("review.js")
    enter = review.split("enter() {", 1)[1].split("\n    },", 1)[0]
    leave = review.split("leave() {", 1)[1].split("\n    },", 1)[0]
    # A panel built in the painter would throw away the scroll position and every
    # checkbox's focus on every hover of a button.
    assert "if (!panel)" in enter
    assert "paint(h)" not in enter
    assert "panel?.remove()" in leave


def test_a_rebuild_keeps_the_row_the_user_is_working_on() -> None:
    body = _read("review.js").split("function refresh()", 1)[1].split("\n  }", 1)[0]
    assert "const top = panel.scrollTop;" in body
    assert "panel.scrollTop = top;" in body


def test_the_panel_is_sized_to_the_gap_between_the_signs_and_the_buttons() -> None:
    # The HTML sits over the board, so it must not cover the hit-tested buttons or
    # the title. Both edges are measured in whole dots from the board's own geometry.
    review = _read("review.js")
    body = review.split("ui.register('review'", 1)[1].split("\n  });", 1)[0]
    assert "const buttonRow = h.rows() - NOTICE_ROWS - renderButton.height - 3;" in body
    assert "panel.style.top = `${(row + 4) * h.pitch()}px`;" in body
    assert "panel.style.bottom" in body


def test_the_board_buttons_of_the_review_screen_are_made_once() -> None:
    review = _read("review.js")
    made = re.findall(r"board\.button\(\{", review)
    assert len(made) == 2, "review.js should make exactly two board buttons, once each"
    placed = re.findall(r"h\.buttonRow\(\[([^\]]*)\]", review)
    assert any("renderButton" in row and "overButton" in row for row in placed)


def test_rendering_is_a_screen_and_nothing_moves_until_it_is_over() -> None:
    review = _read("review.js")
    assert "ui.register('rendering'" in review
    assert "'the clean copy is being written" in review
    submit = review.split("async function submit()", 1)[1].split("\n  }", 1)[0]
    # The screen goes up before the request and the result screen only after it.
    assert submit.index("ui.show('rendering')") < submit.index("await api.postReview")
    assert submit.index("await api.postReview") < submit.index("ui.show('result')")


def test_a_failed_render_puts_the_user_back_on_the_review_they_were_editing() -> None:
    submit = _read("review.js").split("async function submit()", 1)[1].split("\n  }", 1)[0]
    assert "catch (error)" in submit
    assert "say(error.message, TONE_STOP)" in submit
    assert "ui.show('review')" in submit
    # ... and the edited flags are still there, because nothing was reset.
    assert "flags = []" not in submit