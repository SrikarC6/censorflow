/**
 * The flip-disc board: one dot grid covering the whole browser window, drawn
 * on a single canvas.
 *
 * Ported from `lib/discs.ts` and the layout half of `components/FlipText.tsx`
 * in the flip-disc portfolio prototype, minus the DOM measuring: that version
 * had to walk the DOM to work out where to snap each per-label canvas onto a
 * grid it did not own. Here the grid is the unit of account, so text is laid
 * out directly in integer column/row indices.
 *
 * There is deliberately no animation. Every state change is one `put` and one
 * `paint`, so a progress bar moves the instant its event arrives. The split
 * between `put` (mutate) and `paint` (draw) is the seam for adding animation
 * later: a scheduler would sit between them and callers would not change.
 */

import { layoutFlipCells, textCols, getFont } from './font5x7.js';

/**
 * Dot diameter as a fraction of the pitch. Small on purpose: the user asked for
 * dots that read as "basically periods but a little larger". Above ~0.6 the
 * diameter approaches the pitch, the unlit gaps close up, and a dense grid
 * stops looking like a field of dots and starts looking like a sheet of squares.
 */
export const DISC_FILL = 0.55;

/**
 * Default and permitted grid pitch, in CSS pixels. `?pitch=` overrides within
 * the clamp. The default is deliberately tight so that a glyph can afford more
 * dots without also getting bigger.
 */
export const DEFAULT_PITCH = 4;
export const MIN_PITCH = 3;
export const MAX_PITCH = 12;

/** Cell values. Inverted is how a hovered or pressed button reads. */
export const OFF = 0;
export const ON = 1;
export const INV = 2;
export const DIM = 3;

/**
 * How much wider an inverted flap is drawn than a lit one, as a fraction of the
 * disc radius. Big enough to cover the lit flap underneath it and to close up into
 * a readable letter: an inverted cell has to be a hole in the dots that still
 * traces the word, not a dot on top of dots.
 */
const INV_OVERDRAW = 1.16;

/**
 * Thickness of a plate's border, in CSS pixels.
 *
 * One hairline, continuous, exactly like the `.chip` outline in the stylesheet.
 * It was a row of dots before, and the dots read as a beaded frame rather than as
 * the edge of a panel: the whole point of the plate look is that the border is
 * drawn, not made of the same material as the letters inside it.
 */
const PLATE_LINE = 1;

/** The semantic tones a plate border can carry. */
export const TONE_GO = 'go';
export const TONE_STOP = 'stop';
export const TONE_PLAIN = 'plain';

const RESIZE_DEBOUNCE_MS = 80;

function readColours() {
  const style = getComputedStyle(document.documentElement);
  const pick = (name, fallback) => (style.getPropertyValue(name) || fallback).trim();
  return {
    on: pick('--on', '#FFB800'),
    off: pick('--off', '#1C2030'),
    bg: pick('--bg', '#05080D'),
    hi: pick('--on-hi', 'rgba(255,230,140,0.42)'),
    dim: pick('--on-dim', '#6B5620'),
    // The plate, read from the same variables the HTML `.chip` uses, so the
    // canvas signs and the HTML specimens cannot drift apart.
    plateBg: pick('--plate-bg', '') || pick('--bg', '#05080D'),
    plateLine: pick('--plate-line', '') || pick('--line', '#222836'),
    go: pick('--go', '#2FBF71'),
    stop: pick('--stop', '#E5484D'),
  };
}

/** `?pitch=` in the URL, clamped. Anything unparseable falls back to the default. */
export function pitchFromLocation(search = window.location.search) {
  const raw = new URLSearchParams(search).get('pitch');
  if (raw === null) return DEFAULT_PITCH;
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value)) return DEFAULT_PITCH;
  return Math.min(MAX_PITCH, Math.max(MIN_PITCH, value));
}

/**
 * Paint a standalone rectangle of the field onto any canvas, lighting the given
 * cells. The full-window board does not use this - it holds its own buffer so
 * state changes are one cell rather than a whole repaint - but `font-test.html`
 * does, to show the font without the board underneath it.
 */
/**
 * Paint a standalone rectangle of the field onto any canvas, lighting the given
 * cells. The full-window board does not use this - it holds its own buffer so
 * state changes are one cell rather than a whole repaint - but `font-test.html`
 * does, to show the font as text laid over the one board.
 *
 * `paintField: false` draws only the lit dots and leaves everything else
 * transparent. That is the only correct way to lay text over the board: a tile
 * that painted its own unlit dots would put a second, differently-phased field
 * behind the words, which reads as two layers of dots rather than one.
 */
export function renderField(
  canvas,
  { pitch, cols, rows, lit = [], colours = readColours(), paintField = true, ink = null },
) {
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const width = cols * pitch;
  const height = rows * pitch;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const radius = (pitch * DISC_FILL) / 2;
  if (paintField) {
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const x = col * pitch;
        const y = row * pitch;
        ctx.fillStyle = colours.bg;
        ctx.fillRect(x, y, pitch, pitch);
        drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, colours.off);
      }
    }
  }
  for (const [col, row] of lit) {
    if (col < 0 || row < 0 || col >= cols || row >= rows) continue;
    const x = col * pitch;
    const y = row * pitch;
    // Wipe the cell first: with a field underneath, the unlit disc has to be
    // erased before the lit one lands. The fill is the background colour, never
    // the lit colour - a lit cell is a disc, never a square.
    if (paintField) {
      ctx.fillStyle = colours.bg;
      ctx.fillRect(x, y, pitch, pitch);
    }
    // `ink` lets a caller draw the same specimen in a semantic colour, which is
    // how an HTML chip and a canvas button end up with the same lettering.
    drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, ink ?? colours.on);
    if (!ink) drawHighlight(ctx, x + pitch / 2, y + pitch / 2, radius, colours.hi);
  }
}

/**
 * A lit disc: a filled circle, plus a smaller offset highlight so it reads as
 * a physical flap catching the light rather than a flat pixel.
 */
function drawDisc(ctx, cx, cy, radius, on) {
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = on;
  ctx.fill();
}

function drawHighlight(ctx, cx, cy, radius, colour) {
  ctx.beginPath();
  ctx.arc(cx - radius * 0.22, cy - radius * 0.22, radius * 0.32, 0, Math.PI * 2);
  ctx.fillStyle = colour;
  ctx.fill();
}

export function createBoard(canvas, options = {}) {
  const pitch = options.pitch ?? pitchFromLocation();
  const colours = readColours();
  const ctx = canvas.getContext('2d', { alpha: false });
  if (!ctx) throw new Error('censorflow: this browser has no 2d canvas context');

  let cols = 0;
  let rows = 0;
  let dpr = 1;
  let cells = new Uint8Array(0);
  /**
   * Cells that carry meaning: text, a button, a progress bar. `redraw` clears
   * it and the text primitives set it. The board itself never reads it - it
   * exists so a caller that animates the field can skip these cells instead of
   * flickering the words, which is the whole point of a status display.
   */
  let guard = new Uint8Array(0);
  /**
   * Every plate currently on the board, in draw order. Rebuilt from scratch on
   * each `redraw`, because a plate is a box and a border rather than a run of
   * cells: it is remembered, and `paint` consults it for any cell inside one.
   */
  const panels = [];
  const radius = (pitch * DISC_FILL) / 2;

  const painters = [];
  const buttons = [];
  let hovered = null;

  function index(col, row) {
    return row * cols + col;
  }

  function inside(col, row) {
    return col >= 0 && row >= 0 && col < cols && row < rows;
  }

  /** Repaint one cell from its state. The only thing that touches the canvas. */
  function paint(col, row) {
    if (!inside(col, row)) return;
    const state = cells[index(col, row)];
    const x = col * pitch;
    const y = row * pitch;
    const cx = x + pitch / 2;
    const cy = y + pitch / 2;
    // A cell inside a plate is the plate's own colour, not the board's, and its
    // outermost ring carries the hairline. Outside a plate the cell is the board.
    const panel = panelAt(col, row);
    ctx.fillStyle = panel ? panel.fill : colours.bg;
    ctx.fillRect(x, y, pitch, pitch);
    if (panel) drawPanelEdges(panel, col, row, x, y);
    // Nothing on this board is ever a filled square: the dots are the design, so
    // a lit cell is a round flap and the gaps between flaps stay background.
    if (state === OFF) return;
    if (state === DIM) {
      drawDisc(ctx, cx, cy, radius, colours.dim);
      return;
    }
    if (state === INV) {
      // Inverted: a flap flipped to its dark side. Drawn in the plate's own
      // resting colour and a hair wider than a lit disc, so it fully covers the
      // flap underneath: a knocked-out letter is a gap in the dots, not a dot on
      // top of dots. The knock-out follows the letterforms, which is what keeps
      // the word readable while the plate behind it is lit.
      drawDisc(ctx, cx, cy, radius * INV_OVERDRAW, colours.plateBg);
      return;
    }
    // A plate may claim the ink for its own lettering, so a sign whose border is
    // green or red has dots of that same colour rather than amber dots inside a
    // green frame. The specular highlight belongs to the amber flaps only: on a
    // tinted disc it would read as a stray light dot.
    const ink = panel && panel.ink ? panel.ink : colours.on;
    drawDisc(ctx, cx, cy, radius, ink);
    if (ink === colours.on) drawHighlight(ctx, cx, cy, radius, colours.hi);
  }

  function repaintAll() {
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) paint(col, row);
    }
  }

  /** Mutate a cell without drawing. */
  function put(col, row, state) {
    if (!inside(col, row)) return;
    cells[index(col, row)] = state;
  }

  /** Mutate and draw one cell. */
  function set(col, row, state) {
    if (!inside(col, row)) return;
    cells[index(col, row)] = state;
    paint(col, row);
  }

  function fill(col, row, width, height, state) {
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) put(c, r, state);
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) paint(c, r);
    }
  }

  function stroke(col, row, width, height, state) {
    for (let c = col; c < col + width; c += 1) {
      put(c, row, state);
      put(c, row + height - 1, state);
    }
    for (let r = row; r < row + height; r += 1) {
      put(col, r, state);
      put(col + width - 1, r, state);
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) paint(c, r);
    }
  }

/**
   * A plate: an opaque panel the colour of the board with a hairline border.
   *
   * This is the only container the UI uses, and it is deliberately the same box
   * as the `.chip` specimens in the stylesheet - same background, same hairline,
   * same dot of air inside - so a sign drawn here and a specimen drawn in HTML
   * are the same object. `fill` is the panel colour, normally the board colour;
   * `tone` colours the border and is how a control says what it will do.
   *
   * The panel is remembered rather than baked into the cell buffer, so `redraw`
   * can rebuild it from scratch: clearing the buffer and re-running the painters
   * is enough, and `paint` re-draws the panel whenever it walks a cell inside
   * one. `repaintAll` therefore cannot erase a plate.
   *
   * `key` names the panel so a caller that redraws one plate many times a second -
   * the scrolling banner - replaces its record instead of appending a new one.
   */
  function plate({
    col,
    row,
    cols: width,
    rows: height,
    fill,
    tone = TONE_PLAIN,
    key = null,
    ink = null,
  } = {}) {
    const record = {
      col,
      row,
      cols: width,
      rows: height,
      fill: fill ?? colours.plateBg,
      border: tone === TONE_GO ? colours.go : tone === TONE_STOP ? colours.stop : colours.plateLine,
      // `ink` is the colour the plate's own lettering takes. Left null the plate
      // uses the standard amber; a toned plate passes its tone colour so the dots
      // match the hairline. The caller passes null again while it is lit, because
      // then the lettering is knocked out instead.
      ink: ink ?? null,
    };
    const existing = key === null ? -1 : panels.findIndex((other) => other.key === key);
    if (existing === -1) {
      record.key = key;
      panels.push(record);
    } else {
      panels[existing] = record;
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) {
        put(c, r, OFF);
        if (inside(c, r)) guard[index(c, r)] = 1;
      }
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) paint(c, r);
    }
    return { col, row, cols: width, rows: height, tone };
  }

  /** The plate covering a cell, if any. Panels are few, so this is a plain scan. */
  function panelAt(col, row) {
    for (const record of panels) {
      if (col < record.col || col >= record.col + record.cols) continue;
      if (row < record.row || row >= record.row + record.rows) continue;
      return record;
    }
    return null;
  }

  /**
   * The hairline, one cell edge at a time.
   *
   * Drawn per cell rather than as a single `strokeRect` so that the repaint of a
   * single cell - which is what hover, press and the marquee all do - keeps the
   * border intact. `PLATE_LINE` is a CSS pixel, so at a 2x display it lands as a
   * two-device-pixel line and stays crisp.
   */
  function drawPanelEdges(panel, col, row, x, y) {
    ctx.fillStyle = panel.border;
    if (col === panel.col) ctx.fillRect(x, y, PLATE_LINE, pitch);
    if (col === panel.col + panel.cols - 1) ctx.fillRect(x + pitch - PLATE_LINE, y, PLATE_LINE, pitch);
    if (row === panel.row) ctx.fillRect(x, y, pitch, PLATE_LINE);
    if (row === panel.row + panel.rows - 1) ctx.fillRect(x, y + pitch - PLATE_LINE, pitch, PLATE_LINE);
  }

  /** The fill colour a tone means, for a plate lit in that tone. */
  function toneColour(tone) {
    if (tone === TONE_GO) return colours.go;
    if (tone === TONE_STOP) return colours.stop;
    return colours.on;
  }

  /**
   * Light `text` into the grid and return its footprint.
   * `col`/`row` is the top-left corner; `center` instead treats them as the
   * horizontal centre of the first line.
   *
   * Marks every cell it touches as protected, so a caller that animates the
   * field (see the animation in `font-test.html`) can ask which cells carry
   * meaning and leave them alone.
   */
  function stampText(text, col, row, { scale = 1, center = false, state = ON, font } = {}) {
    const { cells: lit, cols: width, rows: height } = layoutFlipCells(text, scale, { center, font });
    const x0 = center ? col - Math.floor(width / 2) : col;
    for (let r = row; r < row + height; r += 1) {
      for (let c = x0; c < x0 + width; c += 1) {
        if (inside(c, r)) guard[index(c, r)] = 1;
      }
    }
    for (const cell of lit) put(x0 + cell.x, row + cell.y, state);
    for (let r = row; r < row + height; r += 1) {
      for (let c = x0; c < x0 + width; c += 1) paint(c, r);
    }
    return { x: x0, y: row, cols: width, rows: height };
  }

  /**
   * A plate with a label on it, hit-tested in grid coordinates.
   *
   * The border colour is the point of `tone`: a control says what it will do
   * before it is touched - green goes, red stops, plain for neither. Hover and
   * press light the panel in that same tone and knock the label out of it, which
   * is the instant inversion from before, just with a drawn border instead of a
   * beaded one. A disabled button keeps its plate and dims its label: an empty
   * outline reads as a rendering bug rather than as "not available yet".
   */
  function button({ col, row, label, scale = 1, font, tone = TONE_PLAIN, onClick }) {
    const handle = {
      col,
      row,
      label,
      scale,
      tone,
      onClick,
      enabled: true,
      hovered: false,
      pressed: false,
      // Only the buttons the current screen placed are drawn. Every button ever
      // created lives in one list, and drawing all of them leaves the previous
      // screen's buttons sitting on the display.
      shown: false,
      width: 0,
      height: 0,
    };

    handle.place = (nextCol, nextRow) => {
      handle.col = nextCol;
      handle.row = nextRow;
      handle.shown = true;
      layout();
      return handle;
    };

    /** Take this button off the display without destroying it. */
    handle.hide = () => {
      handle.shown = false;
      handle.hovered = false;
      handle.pressed = false;
      return handle;
    };

    handle.setLabel = (next) => {
      handle.label = next;
      layout();
      return handle;
    };

    handle.setTone = (next) => {
      handle.tone = next;
      handle.repaint();
      return handle;
    };

    handle.setEnabled = (value) => {
      handle.enabled = value;
      handle.repaint();
      return handle;
    };

    function layout() {
      handle.width = textCols(handle.label, handle.scale, undefined, undefined, font) + 4;
      handle.height = getFont(font).rows * handle.scale + 4;
    }

    /**
     * Draw this button's plate and label. Called from `redraw` rather than on its
     * own, because a plate is remembered on the board rather than baked into the
     * cell buffer: one pass over the whole grid is what keeps the remembered
     * plates and the pixels in agreement. Hovering therefore repaints the board.
     */
    function draw() {
      const active = handle.hovered || handle.pressed;
      const lit = active && handle.enabled;
      const ink = !handle.enabled ? DIM : lit ? INV : ON;
      // Resting: the dots are the tone's own colour, so the lettering and the
      // hairline are one colour and the button reads as a single sign. Lit: the
      // plate fills with the tone colour and the label is knocked out of it, which
      // is what keeps the word legible through the inversion.
      plate({
        col: handle.col,
        row: handle.row,
        cols: handle.width,
        rows: handle.height,
        fill: lit ? toneColour(handle.tone) : colours.plateBg,
        tone: lit ? TONE_PLAIN : handle.tone,
        ink: !lit && handle.enabled && handle.tone !== TONE_PLAIN ? toneColour(handle.tone) : null,
      });
      stampText(handle.label, handle.col + 2, handle.row + 2, {
        scale: handle.scale,
        state: ink,
        font,
      });
    }

    handle.draw = draw;
    /** Repaint the board. See `draw`. */
    handle.repaint = () => redraw();
    handle.contains = (col, row) =>
      col >= handle.col &&
      col < handle.col + handle.width &&
      row >= handle.row &&
      row < handle.row + handle.height;

    layout();
    buttons.push(handle);
    return handle;
  }

  function buttonAt(col, row) {
    for (const handle of buttons) {
      if (handle.enabled !== false && handle.contains(col, row)) return handle;
    }
    return null;
  }

  /**
   * A caption on a sign, with a bar underneath showing `pct`.
   *
   * The bar sits inside the frame, so the unfilled part still reads as part of
   * the sign instead of dissolving into the board - which is what happened when
   * the track was bare cells lying on a lit field.
   */
  function progress({ col, row, width, label, scale = 1, font, tone = TONE_PLAIN, pct = 0 }) {
    const captionRows = label === undefined ? 0 : getFont(font).rows * scale;
    const barRow = row + (captionRows ? captionRows + 3 : 2);
    const total = Math.max(3, width);
    // One row of air under the bar, so it reads as a bar inside the frame rather
    // than as a thick bottom border.
    plate({ col, row, cols: total, rows: barRow + 3 - row, tone, ink: tone === TONE_PLAIN ? null : tone });
    if (captionRows) stampText(label, col + 2, row + 2, { scale, font });
    const barCols = total - 4;
    const filled = Math.round(Math.max(0, Math.min(1, pct)) * barCols);
    for (let i = 0; i < filled; i += 1) set(col + 2 + i, barRow, ON);
    return { col, row, cols: total, rows: barRow + 3 - row };
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 3);
    cols = Math.max(1, Math.floor(window.innerWidth / pitch));
    rows = Math.max(1, Math.floor(window.innerHeight / pitch));
    const width = cols * pitch;
    const height = rows * pitch;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cells = new Uint8Array(cols * rows);
    guard = new Uint8Array(cols * rows);
    redraw();
  }

  /** Re-run every painter over a blank grid. Called on resize and on demand. */
  function redraw() {
    cells.fill(OFF);
    guard.fill(0);
    // Keyed plates outlive a redraw - the banner owns one and re-plates it on its
    // own tick - while everything else is rebuilt by the painters below.
    const persistent = panels.filter((record) => record.key !== null);
    panels.length = 0;
    panels.push(...persistent);
    for (const painter of painters) painter(board);
    // Buttons draw after the painters: a plate is remembered, and the remembered
    // plates have to be in the same order as the pixels, so they are all rebuilt
    // in one pass rather than patched in place.
    for (const handle of buttons) if (handle.shown) handle.draw();
    repaintAll();
  }

  let resizeTimer = 0;
  function onResize() {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(resize, RESIZE_DEBOUNCE_MS);
  }

  const board = {
    pitch,
    colours,
    get cols() {
      return cols;
    },
    get rows() {
      return rows;
    },
    cell: set,
    put,
    paint,
    fill,
    stroke,
    plate,
    stampText,
    button,
    progress,
    /** True when this cell holds text, a button or a bar, and so should not be animated. */
    isProtected(col, row) {
      return inside(col, row) ? guard[index(col, row)] === 1 : false;
    },
    /** Register a painter. It receives the board and is responsible for the whole layout. */
    onDraw(painter) {
      painters.push(painter);
      return () => {
        const at = painters.indexOf(painter);
        if (at >= 0) painters.splice(at, 1);
      };
    },
    redraw,
    /**
     * A snapshot of every registered button's grid rect. Screens need this to
     * drive a button from somewhere other than a click on it.
     */
    handles() {
      return buttons.map(({ col, row, width, height, label, enabled, shown }) => ({
        col,
        row,
        width,
        height,
        label,
        enabled,
        shown,
      }));
    },
    /**
     * The button objects themselves, for a screen that has to change them
     * (`handles` is a read-only snapshot: the review screen drives clicks through
     * it, while this is for placement and state).
     */
    allButtons() {
      return buttons;
    },
    /** The grid cell under a screen point, or null when it misses the board. */
    cellAt(clientX, clientY) {
      return cellFromPoint(clientX, clientY);
    },
  };

  // One listener for the whole board rather than one per button.
  function cellFromPoint(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const col = Math.floor((clientX - rect.left) / pitch);
    const row = Math.floor((clientY - rect.top) / pitch);
    return inside(col, row) ? { col, row } : null;
  }

  function cellFromEvent(event) {
    return cellFromPoint(event.clientX, event.clientY);
  }

  function updateHover(next) {
    if (hovered === next) return;
    const previous = hovered;
    if (previous) {
      previous.hovered = false;
      previous.repaint();
    }
    hovered = next;
    if (hovered) {
      hovered.hovered = true;
      hovered.repaint();
    }
  }

  canvas.addEventListener('pointermove', (event) => {
    const cell = cellFromEvent(event);
    updateHover(cell ? buttonAt(cell.col, cell.row) : null);
  });

  canvas.addEventListener('pointerleave', () => updateHover(null));

  canvas.addEventListener('pointerdown', (event) => {
    const cell = cellFromEvent(event);
    const target = cell ? buttonAt(cell.col, cell.row) : null;
    if (!target) return;
    target.pressed = true;
    target.repaint();
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener('pointerup', (event) => {
    const cell = cellFromEvent(event);
    const target = cell ? buttonAt(cell.col, cell.row) : null;
    if (!target || !target.pressed) return;
    target.pressed = false;
    target.repaint();
    target.onClick?.(target);
  });

  window.addEventListener('resize', onResize);
  if ('ResizeObserver' in window) new ResizeObserver(onResize).observe(document.documentElement);
  resize();
  return board;
}