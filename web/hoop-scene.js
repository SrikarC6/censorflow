/**
 * Dot scene on the processing screen's empty side.
 *
 * The court and the dunk live in `hoop-shot.js`. This module stamps the hoop
 * and repaints only the moving dots on a timer.
 */
import { ON, ORANGE } from './flipdisc.js';
import { ballCells, buildHoop, hoopPose, stillFrame, TICK_MS } from './hoop-shot.js';

let board = null;
let timer = 0;
let active = false;
let frame = 0;
let geomKey = '';
let staticCells = [];
let staticSet = new Map();
let court = null;
let movers = [];

function reducedMotion() {
  if (typeof window.matchMedia !== 'function') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function key(x, y) {
  return `${x},${y}`;
}

function paintMovers(mutate) {
  const plan = court.plan;
  const f = reducedMotion() ? stillFrame(plan) : frame % plan.total;
  const { figure, ball } = hoopPose(plan, f);
  const { col, row, cols, rows } = court.box;
  const next = [];
  const draw = (x, y, state) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    if (board.isProtected(x, y)) return;
    mutate(x, y, state);
    next.push([x, y]);
  };
  figure.forEach(([px, py]) => draw(px, py, ON));
  if (ball) ballCells(ball.x, ball.y).forEach(([px, py]) => draw(px, py, ORANGE));
  movers = next;
}

function stamp() {
  staticCells.forEach(([x, y, state]) => board.put(x, y, state));
  paintMovers(board.put);
}

function tick() {
  if (!active || !court) return;
  movers.forEach(([x, y]) => {
    const kept = staticSet.get(key(x, y));
    board.cell(x, y, kept === undefined ? 0 : kept);
  });
  frame += 1;
  if (frame >= court.plan.total) frame = 0;
  paintMovers(board.cell);
  timer = window.setTimeout(tick, TICK_MS);
}

export function mountHoop(next) {
  board = next;
}

/** Place the court in `band` (board cells). No-op when the band is too small. */
export function syncHoop(band) {
  if (!board || band.rows < 52 || band.cols < 96) {
    hideHoop();
    return;
  }
  const keyNow = `${band.col}:${band.row}:${band.cols}:${band.rows}`;
  if (keyNow !== geomKey) {
    const built = buildHoop(band);
    if (!built) {
      hideHoop();
      return;
    }
    geomKey = keyNow;
    staticCells = built.cells;
    staticSet = built.set;
    court = { box: band, plan: built.plan };
    frame = 0;
  }
  active = true;
  stamp();
  if (reducedMotion() || timer) return;
  timer = window.setTimeout(tick, TICK_MS);
}

export function hideHoop() {
  active = false;
  if (timer) {
    window.clearTimeout(timer);
    timer = 0;
  }
  geomKey = '';
  court = null;
  movers = [];
}
