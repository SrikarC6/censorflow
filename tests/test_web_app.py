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

STYLES = ("ui.js", "app.js")


def _read(name: str) -> str:
    return (config.WEB_DIR / name).read_text(encoding="utf-8")


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
    text = _read("app.js")
    listed = re.search(r"const STAGES = \[([^\]]*)\]", text)
    assert listed is not None, "app.js no longer declares STAGES"
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


# A screen that nothing can reach is dead code that still looks finished. `result`
# is the one exception until 4c: the render figures only exist in the review
# response, so nothing can show that screen yet.
PENDING_SCREENS = {"result": "4c renders after the review POST"}


def test_every_screen_a_button_can_reach_is_registered() -> None:
    app = _read("app.js")
    registered = set(re.findall(r"ui\.register\('([a-z]+)'", app))
    shown = set(re.findall(r"ui\.show\('([a-z]+)'", app))
    assert registered, "no screens registered"
    assert shown <= registered, f"shown but never registered: {shown - registered}"
    unreachable = registered - shown
    assert unreachable == set(PENDING_SCREENS), f"registered but never shown: {unreachable}"


def test_the_stems_mode_is_a_notice_and_not_a_request() -> None:
    # The stem routes answer 501; the button must not pretend otherwise.
    body = _read("app.js").split("const stemsMode = board.button({", 1)[1]
    body = body.split("\n});", 1)[0]
    assert "TONE_STOP" in body
    assert "api." not in body


def test_the_processing_screen_lights_the_stage_the_job_is_in() -> None:
    body = _read("app.js").split("ui.register('processing'", 1)[1].split("\n});", 1)[0]
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
    assert "if (!text) return 0;" in body


def test_the_install_is_checked_before_the_user_picks_a_song() -> None:
    # ffmpeg is a hard requirement and the model is a large download; both are
    # cheaper to find here than three stages into a job.
    app = _read("app.js")
    body = app.split("async function checkInstall()", 1)[1].split("\n}", 1)[0]
    assert "api.health()" in body
    assert "report.reason" in body
    assert "TONE_STOP" in body
    assert "checkInstall()" in app


def test_an_unreachable_server_is_not_reported_as_a_broken_install() -> None:
    body = _read("app.js").split("async function checkInstall()", 1)[1].split("\n}", 1)[0]
    assert "catch" in body
    assert body.index("catch") < body.index("report.reason")


def test_a_toned_sign_tints_its_lettering_and_not_only_its_border() -> None:
    # plate() takes the tone twice: `tone` paints the hairline, `ink` the dots.
    # Passing only one gives a red border with amber letters, which reads as two
    # opinions rather than one warning.
    ui = _read("ui.js")
    assert "function toneInk(tone)" in ui
    for name in ("sign", "notice"):
        body = ui.split(f"    {name}(", 1)[1].split("\n    },", 1)[0]
        assert "ink: toneInk(tone)" in body, name
    board = _read("flipdisc.js")
    progress = board.split("function progress(", 1)[1].split("\n  }", 1)[0]
    assert "ink:" in progress


def test_a_button_is_created_once_and_placed_by_the_painter() -> None:
    # Creating a handle inside a painter leaks one per redraw, which is how the
    # buttons stopped responding once already.
    app = _read("app.js")
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
    app = _read("app.js")
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
    for name in ("api.js", "ui.js", "flipdisc.js"):
        exported |= set(re.findall(r"export (?:async )?function (\w+)", _read(name)))
        exported |= set(re.findall(r"export class (\w+)", _read(name)))
        exported |= set(re.findall(r"export const (\w+)", _read(name)))
    # `api` is a namespace import, checked separately.
    assert "api" in app
    missing = {name for name in imported if name} - exported
    assert not missing, f"app.js imports names nothing exports: {missing}"


def test_the_ui_module_owns_the_state_the_screens_read() -> None:
    # review.js arrives in 4c and needs the same job, so two copies of state would
    # mean previewing the wrong song.
    ui = _read("ui.js")
    assert "export const state = {" in ui
    assert "export function createUi" in ui


def test_the_tones_the_screens_use_come_from_the_board() -> None:
    board = _read("flipdisc.js")
    for tone in ("TONE_GO", "TONE_PLAIN", "TONE_STOP"):
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
    board = _read("flipdisc.js")
    assert "requestAnimationFrame" not in board
    assert "setInterval" not in board


def test_the_screens_do_not_animate_either() -> None:
    for name in STYLES:
        text = _read(name)
        assert "requestAnimationFrame" not in text, name
        assert "setInterval" not in text, name
        assert ".style.opacity" not in text, name


def test_no_debug_output_was_left_in_the_web_sources() -> None:
    for name in ("api.js", "ui.js", "app.js", "flipdisc.js"):
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
    app = _read("app.js")
    assert "new URLSearchParams(window.location.search).get('job')" in app
    assert "api.getJob(id)" in app
    # A finished job cannot be re-entered: the render figures only exist in the
    # review response, which is phase 4c's business.
    assert "state_ === 'done' || state_ === 'error'" in app


def test_starting_again_releases_the_object_url_and_the_stream() -> None:
    body = _read("app.js").split("function startUpload()", 1)[1].split("\n}", 1)[0]
    assert "URL.revokeObjectURL" in body
    assert "state.stopFollowing()" in body
    assert "ui.show('welcome')" in body