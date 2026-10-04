/**
 * Screen plumbing for the dot board.
 *
 * A screen is an object with a `paint` function and optional `enter`/`leave`.
 * `paint` draws the whole screen through the helpers here; nothing is animated,
 * so switching screens is a redraw.
 *
 * The one rule the board imposes: a button must be *created* once and *placed*
 * again on every paint. Creating one inside a painter leaks a handle into the
 * hit-test list on every redraw, which is how the first version of this page
 * ended up with buttons that stopped responding.
 */
import { createBoard, pitchFromLocation, TONE_GO, TONE_PLAIN, TONE_STOP } from './flipdisc.js';
import { getFont, textCols, wrapText } from './font5x7.js';

/**
 * The lettering colour for a toned sign.
 *
 * `plate` takes the tone twice over: `tone` paints the hairline and `ink` paints
 * the dots inside. A sign that passed only `tone` came out with a red border and
 * amber letters, which reads as two different opinions rather than one warning.
 */
function toneInk(tone) {
  return tone === TONE_PLAIN ? null : tone;
}

/**
 * The largest scale at which `text` wraps into at most `maxLines` lines.
 *
 * `pickScale` in the font module only asks whether the text wraps at all, so it
 * happily returns scale 4 for a line that then needs three rows of display - which
 * is how a subtitle ends up taller than the space left for the button under it.
 */
function fitText(text, maxCols, maxLines) {
  for (const scale of SCALES) {
    const wrapped = wrapText(text, maxCols, scale);
    if (wrapped !== null && wrapped.split('\n').length <= maxLines) return { scale, text: wrapped };
  }
  return { scale: 1, text: wrapText(text, maxCols, 1) ?? String(text) };
}

/** The scales a sign may use, largest first. */
const SCALES = [4, 3, 2, 1];

/**
 * `text` cut to fit `maxCols` at scale 1, with an ellipsis if anything was lost.
 *
 * The ellipsis is counted before the cut, not after: adding it afterwards grows
 * the label past the width it was just fitted to, and the sign then clips its own
 * last glyphs instead of saying less.
 */
function fitLine(text, maxCols) {
  const cost = (value) => textCols(`${value}...`, 1);
  if (cost(text) <= maxCols) return text;
  let kept = text;
  while (kept.length > 1 && cost(kept) > maxCols) kept = kept.slice(0, -1);
  // A window too narrow for even one letter plus an ellipsis gets the letters.
  if (cost(kept) > maxCols) {
    while (kept.length > 1 && textCols(kept, 1) > maxCols) kept = kept.slice(0, -1);
    return kept;
  }
  return `${kept}...`;
}

/**
 * Dots reserved at the bottom of the window for the status line.
 *
 * Exported because review.js has to place its buttons clear of it: it draws a
 * dense HTML panel between the signs and the buttons, and if either edge of that
 * panel guessed at this number the two would overlap.
 */
export const NOTICE_ROWS = 13;

const MARGIN = 4;

/**
 * Dots a screen needs before its controls are worth splitting across rows.
 *
 * Below this the rows would be closer together than the tallest button is high,
 * so two of them cannot both be reached.
 */
const MIN_USABLE_ROWS = 60;

/**
 * Everything the screens read, in one object, owned here rather than in app.js:
 * the review screen (review.js) is a separate module and needs the same job, the
 * same upload and the same transport. Two copies of "which job am I on" is how a
 * review screen ends up previewing the wrong song.
 */
export const state = {
  file: null,
  objectUrl: null,
  upload: null,
  job: null,
  snapshot: null,
  render: null,
  stopFollowing: null,
  player: null,
  quality: 'fast',
  // `present` starts true so the download button does not flash before /api/health.
  model: { present: true, state: 'idle', pct: 0, message: '' },
};

export function createUi({ canvas, overlay }) {
  const board = createBoard(canvas, { pitch: pitchFromLocation(window.location.search) });
  const screens = new Map();
  let currentName = null;
  let currentScreen = null;
  // Set by the last `buttonRow` that could not fit the window, read by `notice`.
  let narrow = false;
  // One painter, forever: it forwards to whichever screen is showing. Registering
  // a painter per screen instead would stack them up across a hundred redraws.
  // Helpers first, because that is all a screen needs; the board itself is on
  // `ui.board` for the rare case that needs a raw primitive.
  board.onDraw(() => {
    if (currentScreen) currentScreen.paint(helpers);
  });

  const helpers = {
    pitch: () => board.pitch,
    cols: () => board.cols,
    rows: () => board.rows,
    /**
     * The first row the status notice may occupy.
     *
     * Nothing else may be drawn at or below it. On a short window a screen's block
     * is taller than the space available, and whatever overflows last is what ends
     * up under the notice - which is how a button ends up painted over by a plate
     * and looks like it is not there at all.
     */
    bottom: () => Math.max(0, board.rows - NOTICE_ROWS - 2),
    /**
     * Is this window too short for a screen's full set of controls?
     *
     * `buttonRow` clamps a row that will not fit up above the status line, which
     * stops a button being drawn where it cannot be clicked - but two rows clamped
     * onto the same space end up on top of each other, and only the first one drawn
     * is ever hit. A screen asks this and drops to a single row rather than
     * stacking controls that cannot all be reached.
     */
    tight(tall) {
      return board.rows - NOTICE_ROWS - tall < MIN_USABLE_ROWS;
    },
    /**
     * The first row of a block `tall` dots high, centred in the space above the
     * status line. Screens declare their own size rather than guessing a fraction
     * of the window, which is how a button ends up underneath the notice.
     */
    top(tall) {
      return Math.max(2, Math.floor((board.rows - NOTICE_ROWS - tall) / 2));
    },
    /**
     * The column that centres a row of buttons, measured from the handles themselves.
     *
     * Screens used to write `cols() / 2 - 13` and guess the half-width of the label.
     * A guess is wrong the moment the label is long or the window is narrow, and a
     * button pushed off the right edge cannot be clicked at all.
     */
    centre(handles, { gap = 2 } = {}) {
      const width = handles.reduce((total, handle) => total + handle.width, 0);
      const spaces = Math.max(0, handles.length - 1) * gap;
      return Math.max(MARGIN, Math.floor((board.cols - width - spaces) / 2));
    },
    /**
     * A sign of text, wrapped and scaled to fit the window. Returns the first row
     * below it.
     *
     * `pickScale` answers with a scale *and* the wrapped lines, and the scale alone
     * is not enough: picking the largest scale at which the text wraps and then
     * stamping the original string is how a subtitle ends up running off both edges
     * of the display.
     */
    sign(
      text,
      { row = 0, scale = null, tone = TONE_PLAIN, centre = true, gap = 2, maxLines = 2 } = {},
    ) {
      const maxCols = Math.max(8, board.cols - MARGIN * 2);
      const fit = scale === null ? fitText(text, maxCols, maxLines) : { scale, text: String(text) };
      const lines = fit.text.split('\n');
      const lineRows = getFont().rows * fit.scale;
      const width =
        Math.max(...lines.map((line) => textCols(line, fit.scale)), 1) + 4;
      const height = lines.length * lineRows + (lines.length - 1) * gap + 4;
      const col = centre ? Math.max(0, Math.floor((board.cols - width) / 2)) : MARGIN;
      board.plate({ col, row, cols: width, rows: height, tone, ink: toneInk(tone) });
      lines.forEach((line, index) => {
        board.stampText(line, col + 2, row + 2 + index * (lineRows + gap), {
          scale: fit.scale,
        });
      });
      return row + height;
    },
    /** A sign with a progress bar under it. Returns the row below it. */
    meter(text, pct, { row = 0, width = null, tone = TONE_PLAIN } = {}) {
      const span = width ?? Math.min(board.cols - MARGIN * 2, 120);
      const sign = board.progress({ col: MARGIN, row, width: span, label: text, pct, tone });
      return row + sign.rows;
    },
    /** Buttons already created, laid out left to right from a cursor. */
    buttonRow(handles, row, { col = MARGIN, gap = 2 } = {}) {
      // A button drawn at or below the notice cannot be clicked, and one drawn past
      // the last row is off the window entirely. Both happen on a short window,
      // where the signs above have already used up the space, so the buttons get
      // the last word: they move up into the gap rather than under the notice.
      const height = Math.max(...handles.map((handle) => handle.height));
      const at = Math.min(row, Math.max(2, helpers.bottom() - height));
      const width = handles.reduce((total, handle) => total + handle.width, 0);
      // Pulled left far enough that the row still fits, rather than hanging off the
      // right edge where half of it cannot be clicked.
      const start = Math.max(0, Math.min(col, board.cols - width));
      // A row that cannot fit however it is placed means the window is too narrow
      // for these controls. Recording that lets the status line say so, instead of
      // leaving the user looking at a button that does nothing.
      narrow = width > board.cols;
      let cursor = start;
      for (const handle of handles) {
        handle.place(cursor, at);
        cursor += handle.width + gap;
      }
      return cursor;
    },
    /** A button whose label is the current value of `text`, e.g. FORMAT: FLAC. */
    toggle(handle, text) {
      handle.setLabel(text);
      return handle;
    },
    notice(text, tone = TONE_PLAIN) {
      // A row of controls that will not fit the window is worth saying out loud:
      // those buttons are on screen but off the edge, and a dead button with no
      // explanation is the one failure this board cannot show the user.
      const spoken = narrow ? 'this window is too narrow - make it wider' : text;
      // Nothing to say means no sign: an empty plate is a box on the display
      // saying nothing, which is worse than saying nothing.
      if (!spoken) return 0;
      // Two dots of air under the sign, so it does not sit on the window edge.
      const height = getFont().rows + 4;
      const row = Math.max(0, board.rows - NOTICE_ROWS - 2);
      // A status line can be arbitrarily long - a server message, a file name -
      // so it is cut to the width the window actually has rather than allowed to
      // run off the edge. Shortening by one character at a time keeps the cut on a
      // glyph boundary, which slicing to a character count would not.
      const maxCols = Math.max(8, board.cols - 8);
      const label = fitLine(String(spoken), maxCols);
      const width = Math.min(board.cols - 2, textCols(label, 1) + 4);
      board.plate({ col: 1, row, cols: width, rows: height, tone, ink: toneInk(tone) });
      board.stampText(label, 3, row + 2, { scale: 1 });
      return row;
    },
  };

  // Named, because `show` and `refresh` reach back into it to hide the previous
  // screen's buttons before the next painter runs.
  const ui = {
    board,
    helpers,
    get screen() {
      return currentName;
    },
    /** Register a screen. `paint` may assume the board is empty. */
    register(name, screen) {
      screens.set(name, screen);
      return screen;
    },
    /** Hide every button, so the next screen starts from a clean display. */
    clearButtons() {
      for (const handle of board.allButtons()) handle.hide();
    },
    /** Show a screen: run its `leave`, then its `enter`, then redraw. */
    show(name) {
      const next = screens.get(name);
      if (!next) throw new Error(`no such screen: ${name}`);
      if (currentScreen?.leave) currentScreen.leave();
      currentName = name;
      currentScreen = next;
      if (overlay) overlay.replaceChildren();
      ui.clearButtons();
      if (next.enter) next.enter(helpers);
      board.redraw();
      return next;
    },
    /** Redraw the current screen. Cheap: it is a state change, not a frame. */
    refresh() {
      ui.clearButtons();
      board.redraw();
    },
    tones: { go: TONE_GO, stop: TONE_STOP, plain: TONE_PLAIN },
  };
  return ui;
}