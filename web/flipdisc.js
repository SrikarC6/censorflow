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
 * Frame colours. A control is told apart from a label by its border, not by its
 * text: green means it does something, red means it stops something or is off.
 * They are cell states rather than paint options because `plate` and `stroke`
 * take a state, and one more state is cheaper than a parallel colour channel.
 */
export const GO = 4;
export const STOP = 5;

/**
 * How much wider an inverted flap is drawn than a lit one, as a fraction of the
 * disc radius. Just enough to cover the lit flap underneath it: an inverted cell
 * has to be a hole in the dots, not a dot on top of dots.
 */
const INV_OVERDRAW = 1.08;

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
    go: pick('--on-go', '#2FBF71'),
    stop: pick('--on-stop', '#E5484D'),
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
  { pitch, cols, rows, lit = [], colours = readColours(), paintField = true },
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
    drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, colours.on);
    drawHighlight(ctx, x + pitch / 2, y + pitch / 2, radius, colours.hi);
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
    // Every cell is erased to the background, then whatever the state calls for
    // is drawn as a disc. Nothing on this board is ever a filled square: the
    // dots are the design, so a lit cell is a round flap and the gaps between
    // flaps stay background.
    ctx.fillStyle = colours.bg;
    ctx.fillRect(x, y, pitch, pitch);
    if (state === OFF) {
      // The board is deliberately bare. An always-on grid of unlit discs is noise
      // behind every label: the eye reads the field, not the text. Dots are ink,
      // drawn only where something is actually written, which is what makes the
      // plates read as physical signs sitting on an empty board.
      return;
    }
    if (state === DIM) {
      drawDisc(ctx, cx, cy, radius, colours.dim);
      return;
    }
    if (state === GO) {
      drawDisc(ctx, cx, cy, radius, colours.go);
      return;
    }
    if (state === STOP) {
      drawDisc(ctx, cx, cy, radius, colours.stop);
      return;
    }
    if (state === INV) {
      // Inverted: a flap flipped to its dark side. It is drawn a hair wider than
      // a lit disc so it fully covers the flap underneath it, which is what a
      // knocked-out letter on a lit plate is - a gap in the dots, not a new dot.
      drawDisc(ctx, cx, cy, radius * INV_OVERDRAW, colours.bg);
      return;
    }
    drawDisc(ctx, cx, cy, radius, colours.on);
    drawHighlight(ctx, cx, cy, radius, colours.hi);
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
   * A sign: a rectangle of cells with a one-dot frame.
   *
   * This is the only container the UI uses. Because the board no longer paints a
   * field, an unlit region is already the background colour, so a plate is exactly
   * `fill` plus a frame - which is what `button` and `progress` already do. It is
   * spelled out as its own call so screens can put a caption on a sign without
   * inventing a button.
   *
   * `body` is the interior. At rest it is OFF, which means bare board, so the
   * label floats on black. Hovering a button sets it to ON, which lights every
   * interior flap: the plate fills with amber dots and the label is then stamped
   * INV, knocking holes in those dots. Still dots everywhere - the sign inverts,
   * it never turns into a solid block.
   */
  function plate({ col, row, cols: width, rows: height, body = OFF, frame = ON } = {}) {
    fill(col, row, width, height, body);
    stroke(col, row, width, height, frame);
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) {
        if (inside(c, r)) guard[index(c, r)] = 1;
      }
    }
    return { col, row, cols: width, rows: height };
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
 * Border state for each tone. `label` is the plain amber frame a caption gets;
 * `go` and `stop` are how a control says what it is before you read it.
 */
const TONES = { label: ON, go: GO, stop: STOP };

/**
   * A dot-drawn rectangle with a label, hit-tested in grid coordinates.
   * Hover and press swap the two colours, which is why cell state carries a
   * third value: the interior has to read as a hole in a lit field.
   *
   * `tone` picks the border: `go` for a control that acts, `stop` for one that
   * halts or is unavailable, `label` for the plain amber frame.
   */
  function button({ col, row, label, scale = 1, font, tone = 'label', onClick }) {
    const handle = {
      col,
      row,
      label,
      scale,
      tone: TONES[tone] === undefined ? 'label' : tone,
      onClick,
      enabled: true,
      hovered: false,
      pressed: false,
      width: 0,
      height: 0,
    };

    handle.place = (nextCol, nextRow) => {
      handle.col = nextCol;
      handle.row = nextRow;
      layout();
      return handle;
    };

    handle.setLabel = (next) => {
      handle.label = next;
      layout();
      return handle;
    };

    function layout() {
      handle.width = textCols(handle.label, handle.scale, undefined, undefined, font) + 4;
      handle.height = getFont(font).rows * handle.scale + 4;
      render();
    }

    function render() {
      // A button is a sign: board-coloured inside, a toned frame at rest, and the
      // interior plus the label swap the moment you touch it - the inside fills
      // with lit flaps and the label knocks out as dark holes in them. The frame
      // keeps its own colour while hovered on purpose: that border is how you know
      // what the control does, and it should not disappear under your cursor.
      // A disabled button keeps its shape and label, just dimmed - a bare outline
      // reads as a rendering bug rather than as "not available yet".
      const active = handle.hovered || handle.pressed;
      const lit = active && handle.enabled;
      const body = lit ? ON : OFF;
      const ink = !handle.enabled ? DIM : lit ? INV : ON;
      plate({
        col: handle.col,
        row: handle.row,
        cols: handle.width,
        rows: handle.height,
        body,
        frame: handle.enabled ? TONES[handle.tone] : DIM,
      });
      stampText(handle.label, handle.col + 2, handle.row + 2, {
        scale: handle.scale,
        state: ink,
        font,
      });
    }

    handle.setEnabled = (value) => {
      handle.enabled = value;
      render();
      return handle;
    };

    /** Swap the border colour, e.g. a toggle that goes from stop to go. */
    handle.setTone = (value) => {
      handle.tone = TONES[value] === undefined ? 'label' : value;
      render();
      return handle;
    };

    /** Repaint this button's own rectangle, without touching the rest of the grid. */
    handle.repaint = render;
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
  function progress({ col, row, width, label, scale = 1, font, pct = 0 }) {
    const captionRows = label === undefined ? 0 : getFont(font).rows * scale;
    const barRow = row + (captionRows ? captionRows + 3 : 2);
    const total = Math.max(3, width);
    // One row of air under the bar, so it reads as a bar inside the frame rather
    // than as a thick bottom border.
    plate({ col, row, cols: total, rows: barRow + 3 - row });
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
    for (const painter of painters) painter(board);
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
      return buttons.map(({ col, row, width, height, label, enabled }) => ({
        col,
        row,
        width,
        height,
        label,
        enabled,
      }));
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