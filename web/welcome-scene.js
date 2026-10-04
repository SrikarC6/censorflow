/**
 * Dot scene in the welcome screen's empty band.
 *
 * A figure lays an asterisked swear (never the n-word) into a trash can sized
 * to the figure; the timeline lives in `welcome-layup.js`. The basket and can
 * are static; a timer repaints only the moving dots.
 */
import { layoutTiny } from './font3x5.js';
import { ON, ORANGE } from './flipdisc.js';
import { layupPose, planLayup, stillFrame } from './welcome-layup.js';

/** Thrown words, one per layup. The font is uppercase-only. */
const TAGS = ['F*CK', 'SH*T', 'F**K', 'B*TCH', 'A**', 'C**T', 'WH*RE', 'P*SSY'];

const TICK_MS = 90;
const GAP = 6;
/** Trash can size as a fraction of the figure's height (head to feet). */
const CAN_TALL = 0.5;
const CAN_WIDE = 0.45;

let board = null;
let timer = 0;
let active = false;
let frame = 0;
let cycle = 0;
let geomKey = '';
let staticCells = [];
let staticSet = new Set();
let court = null;
let movers = [];
const bits = new Map();

function reducedMotion() {
  if (typeof window.matchMedia !== 'function') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function key(x, y) {
  return `${x},${y}`;
}

function wordBits(text) {
  let found = bits.get(text);
  if (!found) {
    found = layoutTiny(text);
    bits.set(text, found);
  }
  return found;
}

function outline(add, x0, y0, x1, y1) {
  for (let y = y0; y <= y1; y += 1) {
    add(x0, y);
    add(x1, y);
  }
  for (let x = x0; x <= x1; x += 1) add(x, y1);
}

function build(band) {
  const { col, row, cols, rows } = band;
  if (cols < 120) return null;
  bits.clear();
  const wide = TAGS.map(wordBits).reduce((a, b) => (b.cols > a.cols ? b : a));
  const halfW = Math.ceil(wide.cols / 2);
  const halfH = Math.ceil(wide.rows / 2);
  const body = Math.min(24, Math.max(18, Math.floor(rows * 0.22)));
  const top = row + GAP + halfH;
  const floor = row + rows - 3;
  const px = col + 14;
  const cells = [];
  const set = new Set();
  const add = (x, y) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    const id = key(x, y);
    if (set.has(id)) return;
    cells.push([x, y]);
    set.add(id);
  };
  const held = { x: px + 12 + halfW, y: floor - halfH - 1 };
  outline(add, held.x - halfW - 2, held.y - halfH, held.x + halfW + 2, floor);

  const canR = col + cols - 5;
  const canL = canR - Math.round(body * CAN_WIDE);
  const mouth = floor - Math.round(body * CAN_TALL);
  outline(add, canL, mouth, canR, floor);
  add(canL - 2, mouth);
  add(canL - 1, mouth);
  add(canR + 1, mouth);
  add(canR + 2, mouth);
  for (let s = 1; s <= 2; s += 1) {
    const x = canL + Math.round(((canR - canL) * s) / 3);
    for (let y = mouth + 2; y < floor; y += 2) add(x, y);
  }

  const arrive = { x: Math.round((canL + canR) / 2), y: mouth - halfH };
  return {
    cells,
    set,
    court: {
      box: band,
      base: { px, floor, body, top, arrive, mouth, canL, basket: held },
      plans: new Map(),
    },
  };
}

function planFor(text) {
  let plan = court.plans.get(text);
  if (!plan) {
    plan = planLayup(court.base, wordBits(text));
    court.plans.set(text, plan);
  }
  return plan;
}

function currentPlan() {
  return planFor(TAGS[cycle % TAGS.length]);
}

function paintMovers(mutate) {
  const plan = currentPlan();
  const f = reducedMotion() ? stillFrame(plan) : frame % plan.total;
  const { figure, word, trail, clip } = layupPose(plan, f);
  const { glyph } = plan;
  const { col, row, cols, rows } = court.box;
  const next = [];
  const draw = (x, y, state, over) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    if (board.isProtected(x, y) || (!over && staticSet.has(key(x, y)))) return;
    mutate(x, y, state);
    next.push([x, y]);
  };
  figure.forEach(([x, y]) => draw(x, y, ON, false));
  trail.forEach(([x, y]) => draw(x, y, ON, false));
  if (word) {
    const x0 = Math.round(word.x - glyph.cols / 2);
    const y0 = Math.round(word.y - glyph.rows / 2);
    glyph.cells.forEach((dot) => {
      if (y0 + dot.y < clip) draw(x0 + dot.x, y0 + dot.y, ORANGE, true);
    });
  }
  movers = next;
}

function stamp() {
  staticCells.forEach(([x, y]) => board.put(x, y, ON));
  paintMovers(board.put);
}

function tick() {
  if (!active) return;
  movers.forEach(([x, y]) => board.cell(x, y, staticSet.has(key(x, y)) ? ON : 0));
  frame += 1;
  if (frame >= currentPlan().total) {
    frame = 0;
    cycle += 1;
  }
  paintMovers(board.cell);
  timer = window.setTimeout(tick, TICK_MS);
}

export function mountScene(next) {
  board = next;
}

/** Place the scene in `band` (board cells). No-op when the band is too small. */
export function syncScene(band) {
  if (!board || band.rows < 40 || band.cols < 110) {
    hideScene();
    return;
  }
  const keyNow = `${band.col}:${band.row}:${band.cols}:${band.rows}`;
  if (keyNow !== geomKey) {
    const built = build(band);
    if (!built) {
      hideScene();
      return;
    }
    geomKey = keyNow;
    staticCells = built.cells;
    staticSet = built.set;
    court = built.court;
  }
  active = true;
  stamp();
  if (reducedMotion() || timer) return;
  timer = window.setTimeout(tick, TICK_MS);
}

export function hideScene() {
  active = false;
  if (timer) {
    window.clearTimeout(timer);
    timer = 0;
  }
  geomKey = '';
}
