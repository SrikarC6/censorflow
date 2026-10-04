/**
 * The flip-disc board: one dot grid on a canvas. Painting lives in
 * board-paint.js and buttons in board-controls.js. There is no animation:
 * a state change is one redraw.
 */

import { readColours, renderField } from './board-field.js';
import { attachControls } from './board-controls.js';
import { attachPaint } from './board-paint.js';

export { renderField };

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
/** Orange disc used for the basketball. */
export const ORANGE = 4;
/** Blue disc for the second team on the result-screen game. */
export const BLUE = 5;

/** The semantic tones a plate border can carry. */
export const TONE_GO = 'go';
export const TONE_STOP = 'stop';
export const TONE_PLAIN = 'plain';
export const TONE_INFO = 'info';

const RESIZE_DEBOUNCE_MS = 80;

/** `?pitch=` in the URL, clamped. Anything unparseable falls back to the default. */
export function pitchFromLocation(search = window.location.search) {
  const raw = new URLSearchParams(search).get('pitch');
  if (raw === null) return DEFAULT_PITCH;
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value)) return DEFAULT_PITCH;
  return Math.min(MAX_PITCH, Math.max(MIN_PITCH, value));
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
  // Paint calls that change a button (tone, enabled) ask for another redraw.
  // Doing that from inside a painter would recurse until the stack dies, so a
  // nested request is dropped: the pass already in flight draws the buttons
  // after the painters, and it reads the new tone.
  let drawing = false;

  function index(col, row) {
    return row * cols + col;
  }

  function inside(col, row) {
    return col >= 0 && row >= 0 && col < cols && row < rows;
  }

  const env = {
    ctx,
    colours,
    pitch,
    radius,
    panels,
    buttons,
    get cols() {
      return cols;
    },
    get rows() {
      return rows;
    },
    get cells() {
      return cells;
    },
    get guard() {
      return guard;
    },
    index,
    inside,
    get drawing() {
      return drawing;
    },
    redraw() {
      redraw();
    },
  };
  const surface = attachPaint(env);
  const controls = attachControls(env, surface);
  const { paint, repaintAll, put, set, fill, stroke, plate, stampText } = surface;
  const { button, buttonAt, progress } = controls;

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
    if (drawing) return;
    drawing = true;
    try {
      paintFrame();
    } finally {
      drawing = false;
    }
  }

  function paintFrame() {
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