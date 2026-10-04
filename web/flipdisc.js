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
    if (paintField) {
      ctx.fillStyle = colours.on;
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
    if (state === OFF) {
      ctx.fillStyle = colours.bg;
      ctx.fillRect(x, y, pitch, pitch);
      drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, colours.off);
      return;
    }
    if (state === DIM) {
      ctx.fillStyle = colours.bg;
      ctx.fillRect(x, y, pitch, pitch);
      drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, colours.dim);
      return;
    }
    ctx.fillStyle = state === ON ? colours.on : colours.bg;
    ctx.fillRect(x, y, pitch, pitch);
    if (state === ON) drawHighlight(ctx, x + pitch / 2, y + pitch / 2, radius, colours.hi);
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
   * A dot-drawn rectangle with a label, hit-tested in grid coordinates.
   * Hover and press swap the two colours, which is why cell state carries a
   * third value: the interior has to read as a hole in a lit field.
   */
  function button({ col, row, label, scale = 1, font, onClick }) {
    const handle = {
      col,
      row,
      label,
      scale,
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
      // A disabled button keeps its shape and label, just dimmed: OFF-on-OFF
      // would make it vanish into the field, which reads as a rendering bug
      // rather than as "not available yet".
      const active = handle.hovered || handle.pressed;
      const body = active && handle.enabled ? ON : OFF;
      const ink = !handle.enabled ? DIM : active ? INV : ON;
      fill(handle.col, handle.row, handle.width, handle.height, body);
      stroke(handle.col, handle.row, handle.width, handle.height, ink);
      for (let r = handle.row; r < handle.row + handle.height; r += 1) {
        for (let c = handle.col; c < handle.col + handle.width; c += 1) {
          if (inside(c, r)) guard[index(c, r)] = 1;
        }
      }
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

  /** A bar of `width` cells filled to `pct`, with an optional dot-matrix label above it. */
  function progress({ col, row, width, label, scale = 1, font, pct = 0 }) {
    if (label !== undefined) {
      const block = stampText(label, col, row, { scale, font });
      row += block.rows + 1;
    }
    const filled = Math.round(Math.max(0, Math.min(1, pct)) * width);
    for (let i = 0; i < width; i += 1) {
      set(col + i, row, i < filled ? ON : OFF);
      if (inside(col + i, row)) guard[index(col + i, row)] = 1;
    }
    return { x: col, y: row, cols: width, rows: 1 };
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
  };

  // One listener for the whole board rather than one per button.
  function cellFromEvent(event) {
    const rect = canvas.getBoundingClientRect();
    const col = Math.floor((event.clientX - rect.left) / pitch);
    const row = Math.floor((event.clientY - rect.top) / pitch);
    return inside(col, row) ? { col, row } : null;
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