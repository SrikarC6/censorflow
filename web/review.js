/**
 * The review screen: the transcript, the table of flags, and the Render button.
 *
 * The HTML of the transcript and the table is built in review-dom.js. This
 * module owns the flags, talks to the server, and draws the board buttons.
 */
import * as api from './api.js';
import { TONE_GO, TONE_PLAIN, TONE_STOP } from './flipdisc.js';
import { createReviewDom } from './review-dom.js';
import { NOTICE_ROWS, state } from './ui.js';

/**
 * Audio either side of a word when previewing it, in seconds.
 *
 * The server has its own `PREVIEW_PAD_S` and pads again when it renders a
 * previewed region; this is only how much the browser asks for.
 */
const PREVIEW_PAD_S = 1.5;

/** The fields the server reads from a flag, in the order it validates them. */
const SENT = ['word_index', 'text', 'start', 'end', 'source', 'confidence', 'approx', 'censor'];

/**
 * Wire the review screens into `ui`.
 *
 * `ui.board` only exists once `createUi` has run, so the buttons cannot be made at
 * module level the way app.js makes its own: they are created once here and placed
 * by the painter, which is the rule the board imposes.
 */
export function registerReview(ui, { say, startUpload, status }) {
  const board = ui.board;

  /** The flags as the user has left them. Rebuilt from the server on every open. */
  let flags = [];
  /** The server's payload: the transcript the flags point into. */
  let data = null;
  /** The HTML box, once built. */
  let panel = null;
  /** One shared element for previews, so two clicks cannot play over each other. */
  let previewer = null;

  const renderButton = board.button({
    label: 'RENDER',
    scale: 2,
    tone: TONE_GO,
    onClick: () => submit(),
  });
  const overButton = board.button({
    label: 'START OVER',
    scale: 1,
    onClick: () => startUpload(),
  });

  const dom = createReviewDom({
    get flags() {
      return flags;
    },
    get data() {
      return data;
    },
    say,
    ui,
    refresh() {
      refresh();
    },
    preview(kind, flag) {
      preview(kind, flag);
    },
  });


  /**
   * Rebuild the HTML, then redraw the board.
   *
   * Scroll position is kept because the table is often taller than the window and
   * a rebuild that jumped to the top would lose the row being worked on.
   */
  function refresh() {
    if (!panel) return;
    const top = panel.scrollTop;
    panel.replaceChildren(dom.buildHead(), dom.buildTranscript(), dom.buildTable());
    panel.scrollTop = top;
    ui.refresh();
  }

  /** Ask the server for `PREVIEW_PAD_S` of audio either side of one flag. */
  function preview(kind, flag) {
    if (!state.job) return;
    if (!previewer) {
      previewer = new Audio();
      previewer.preload = 'auto';
    }
    previewer.pause();
    previewer.src = api.clipUrl(
      state.job.id,
      kind,
      Math.max(0, flag.start - PREVIEW_PAD_S),
      flag.end + PREVIEW_PAD_S,
    );
    const spoken = kind === 'original' ? 'the original' : 'the censored version';
    previewer.play().then(
      () => say(`playing ${spoken}`),
      () => say('the browser would not play that clip', TONE_STOP),
    );
  }

  /** Send the flags as the user left them, then show the render. */
  async function submit() {
    if (!state.job) return;
    say(`rendering ${flags.filter((flag) => flag.censor).length} windows`);
    ui.show('rendering');
    let payload;
    try {
      payload = await api.postReview(state.job.id, {
        flags: flags.map((flag) => Object.fromEntries(SENT.map((key) => [key, flag[key]]))),
      });
    } catch (error) {
      say(error.message, TONE_STOP);
      ui.show('review');
      return;
    }
    state.render = payload.render;
    const censored = payload.render.words_censored;
    say(censored === 1 ? 'one word censored' : `${censored} words censored`);
    ui.show('result');
  }

  /** Forget a finished review, so a new song cannot inherit the old song's flags. */
  function reset() {
    flags = [];
    data = null;
    panel = null;
    if (previewer) previewer.pause();
  }

  /** Open the review screen on a job that has finished analysing. */
  async function open(id) {
    say('loading the review');
    ui.show('awaiting');
    let payload;
    try {
      payload = await api.getReview(id);
    } catch (error) {
      say(error.message, TONE_STOP);
      ui.show('welcome');
      return;
    }
    data = payload;
    // Work on a copy: the payload is what the server said, and the table is what
    // the user has done to it.
    flags = payload.flags.map((flag) => ({ ...flag }));
    flags.sort((a, b) => a.start - b.start);
    panel = document.createElement('div');
    panel.className = 'review';
    ui.show('review');
    refresh();
    // The status line is a question, not a report: the user now has to decide.
    say(
      flags.length === 0
        ? 'nothing was flagged - render to write the clean copy anyway'
        : `check the ${flags.length} flagged words, then render`,
    );
  }

  ui.register('rendering', {
    paint(h) {
      h.sign('RENDERING', { row: h.top(60) });
      h.notice('the clean copy is being written. this takes a moment', TONE_PLAIN);
    },
  });

  ui.register('review', {
    enter() {
      // Created here, not in the painter: a panel built on every redraw would throw
      // away the scroll position and every checkbox's focus on every hover.
      if (!panel) {
        panel = document.createElement('div');
        panel.className = 'review';
        panel.setAttribute('role', 'region');
        panel.setAttribute('aria-label', 'transcript and flags');
      }
      document.getElementById('overlay').append(panel);
    },
    leave() {
      panel?.remove();
    },
    paint(h) {
      const on = flags.filter((flag) => flag.censor).length;
      let row = h.sign('REVIEW', { row: 1, centre: false, scale: 3 });
      row = h.sign(`${on} OF ${flags.length} FLAGS ON`, { row: row + 2, centre: false });
      // The panel is sized to the gap between the last sign and the buttons, so the
      // dense HTML can never sit on top of the board's own hit-tested buttons.
      const buttonRow = h.rows() - NOTICE_ROWS - renderButton.height - 3;
      if (panel) {
        panel.style.top = `${(row + 4) * h.pitch()}px`;
        panel.style.bottom = `${(h.rows() - buttonRow) * h.pitch()}px`;
      }
      h.buttonRow([renderButton, overButton], buttonRow, {
        col: h.centre([renderButton, overButton]),
      });
      h.notice(status().text, status().tone);
    },
  });

  return { open, reset };
}