/**
 * Dot scene in the welcome screen's empty band.
 *
 * A figure throws an orange basketball into a trash can. A short asterisked
 * swear from the F**K family (not the n-word) rides on the ball, the width of
 * the ball, and goes in with it. Flight is a parabola: up, crest under Choose
 * a Song, then down into the can, with a dotted trail. A timer repaints only
 * the moving dots.
 */
import { layoutFlipCells } from './font5x7.js';
import { ON, ORANGE } from './flipdisc.js';

/** Two-glyph labels for F**K, SH*T, B*TCH, C**T, A** and WH*RE. Ball-width. */
const TAGS = ['F*', 'S*', 'B*', 'C*', 'A*', 'W*'];

const TICK_MS = 90;
const REACH = 12;
const LIFT = 10;
const SINK = 8;
const BACK = 10;
const BALL_R = 5;
const GAP = 6;

let board = null;
let timer = 0;
let active = false;
let frame = 0;
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
    const laid = layoutFlipCells(text, 1);
    found = { cells: laid.cells, cols: laid.cols, rows: laid.rows };
    bits.set(text, found);
  }
  return found;
}

function segment(x0, y0, x1, y1) {
  const pts = [];
  const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1);
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    pts.push([Math.round(x0 + (x1 - x0) * t), Math.round(y0 + (y1 - y0) * t)]);
  }
  return pts;
}

function lerp(a, b, t) {
  const u = Math.max(0, Math.min(1, t));
  return { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
}

function outline(add, x0, y0, x1, y1) {
  for (let y = y0; y <= y1; y += 1) {
    add(x0, y);
    add(x1, y);
  }
  for (let x = x0; x <= x1; x += 1) add(x, y1);
}

/** Loftiest parabola that still crests at or below `top` (y grows downward). */
function solveShot(x0, y0, x1, y1, top) {
  const T = 32;
  const dx = x1 - x0;
  const a = (y1 - y0) / T;
  const b = 0.5 * T;
  let lo = 0.08;
  let hi = 1.4;
  let g = lo;
  for (let n = 0; n < 12; n += 1) {
    const mid = (lo + hi) / 2;
    const vy = a - b * mid;
    const tA = vy < 0 ? -vy / mid : 0;
    const yA = y0 + vy * tA + 0.5 * mid * tA * tA;
    if (vy < 0 && yA >= top) {
      g = mid;
      lo = mid;
    } else hi = mid;
  }
  return { vx: dx / T, vy: a - b * g, g, T };
}

function flight(t) {
  const { release, shot } = court;
  return {
    x: release.x + shot.vx * t,
    y: release.y + shot.vy * t + 0.5 * shot.g * t * t,
  };
}

function ballDots(cx, cy) {
  const pts = [];
  const r2 = BALL_R * BALL_R + BALL_R * 0.35;
  for (let y = -BALL_R; y <= BALL_R; y += 1) {
    for (let x = -BALL_R; x <= BALL_R; x += 1) {
      if (x * x + y * y > r2 || x === 0 || y === 0) continue;
      pts.push([cx + x, cy + y]);
    }
  }
  return pts;
}

function build(band) {
  const { col, row, cols, rows } = band;
  if (cols < 120) return null;
  bits.clear();
  const wide = wordBits(TAGS[0]);
  const body = Math.min(24, Math.max(18, Math.floor(rows * 0.22)));
  const top = row + GAP + wide.rows + 1 + BALL_R;
  const floor = row + rows - 3;
  const px = col + 14;
  const headR = 5;
  const headY = floor - body + headR;
  const shoulderY = headY + headR + 2;
  const hipY = floor - Math.round(body * 0.36);
  const cells = [];
  const set = new Set();
  const add = (x, y) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    const id = key(x, y);
    if (set.has(id)) return;
    cells.push([x, y]);
    set.add(id);
  };
  for (let y = -headR; y <= headR; y += 1) {
    for (let x = -headR; x <= headR; x += 1) {
      if (x * x + y * y <= headR * headR) add(px + x, headY + y);
    }
  }
  for (let y = shoulderY; y <= hipY; y += 1) add(px, y);
  segment(px - 2, shoulderY, px - 6, hipY).forEach(([x, y]) => add(x, y));
  segment(px, hipY, px - 4, floor).forEach(([x, y]) => add(x, y));
  segment(px, hipY, px + 4, floor).forEach(([x, y]) => add(x, y));

  const held = { x: px + 12 + BALL_R, y: floor - BALL_R - 1 };
  const basketL = held.x - BALL_R - 2;
  const basketR = held.x + BALL_R + 2;
  outline(add, basketL, held.y - BALL_R, basketR, floor);

  const canR = col + cols - 3;
  const canL = canR - (BALL_R * 2 + 10);
  const mouth = Math.round(top + (floor - top) * 0.48);
  outline(add, canL, mouth, canR, floor);
  add(canL - 2, mouth);
  add(canL - 1, mouth);
  add(canR + 1, mouth);
  add(canR + 2, mouth);
  for (let s = 1; s <= 2; s += 1) {
    const x = canL + Math.round(((canR - canL) * s) / 3);
    for (let y = mouth + 2; y < floor; y += 2) add(x, y);
  }

  const release = { x: px + headR + BALL_R + 2, y: Math.max(top + 12, headY) };
  const arrive = { x: Math.round((canL + canR) / 2), y: mouth + BALL_R + 2 };
  const shot = solveShot(release.x, release.y, arrive.x, arrive.y, top);
  return {
    cells,
    set,
    court: {
      box: band,
      shoulder: { x: px + 1, y: shoulderY },
      rest: { x: px + 4, y: hipY },
      basket: held,
      release,
      follow: { x: px + headR + 10, y: headY - headR },
      arrive,
      mouth,
      shot,
    },
  };
}

function trailOf(t, ballX) {
  const dots = [];
  let prev = null;
  for (let i = 0; i < t; i += 0.4) {
    const p = flight(i);
    const x = Math.round(p.x);
    const y = Math.round(p.y);
    if (x >= ballX - BALL_R - 1) continue;
    if (prev && Math.abs(prev[0] - x) + Math.abs(prev[1] - y) < 5) continue;
    dots.push([x, y]);
    prev = [x, y];
  }
  return dots;
}

function pose(at) {
  const { shot } = court;
  const flyAt = REACH + LIFT;
  const sinkAt = flyAt + shot.T;
  const backAt = sinkAt + SINK;
  const total = backAt + BACK;
  const f = ((at % total) + total) % total;
  const glyph = wordBits(TAGS[Math.floor(at / total) % TAGS.length]);
  let ball = null;
  let hand;
  let trail = [];
  if (f < REACH) {
    ball = court.basket;
    hand = lerp(court.rest, { x: ball.x - BALL_R, y: ball.y }, f / REACH);
  } else if (f < flyAt) {
    ball = lerp(court.basket, court.release, (f - REACH) / LIFT);
    hand = { x: ball.x - BALL_R, y: ball.y };
  } else if (f < sinkAt) {
    const t = f - flyAt;
    ball = flight(t);
    hand = lerp({ x: court.release.x - BALL_R, y: court.release.y }, court.follow, Math.min(1, t / 6));
    trail = trailOf(t, ball.x);
  } else if (f < backAt) {
    const n = (f - sinkAt) / SINK;
    ball = { x: court.arrive.x, y: court.arrive.y + n * (BALL_R + 4) };
    hand = lerp(court.follow, court.rest, n * 0.5);
    trail = trailOf(shot.T, court.arrive.x);
  } else {
    hand = lerp(court.follow, court.rest, 0.5 + 0.5 * ((f - backAt) / BACK));
  }
  return { hand, ball, trail, glyph };
}

function paintMovers(mutate) {
  const mid = REACH + LIFT + Math.floor(court.shot.T * 0.42);
  const { hand, ball, trail, glyph } = pose(reducedMotion() ? mid : frame);
  const { col, row, cols, rows } = court.box;
  const next = [];
  const draw = (x, y, state, over) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    if (board.isProtected(x, y) || (!over && staticSet.has(key(x, y)))) return;
    mutate(x, y, state);
    next.push([x, y]);
  };
  segment(court.shoulder.x, court.shoulder.y, hand.x, hand.y).forEach(([x, y]) => {
    draw(x, y, ON, false);
  });
  trail.forEach(([x, y]) => draw(x, y, ON, false));
  if (ball) {
    ballDots(Math.round(ball.x), Math.round(ball.y)).forEach(([x, y]) => draw(x, y, ORANGE, true));
    const x0 = Math.round(ball.x - glyph.cols / 2);
    const y0 = Math.round(ball.y - BALL_R - glyph.rows - 1);
    glyph.cells.forEach((dot) => draw(x0 + dot.x, y0 + dot.y, ORANGE, true));
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
