/**
 * Dunk timeline for the processing-screen court.
 *
 * The figure is the welcome layup's stick figure. He dribbles in, jumps to the
 * rim, stuffs an orange basketball, and hangs. Positions are board cells
 * (y grows downward); frames count timer ticks within one cycle.
 */
import { DIM, ON, ORANGE } from './flipdisc.js';
import { figureDots } from './welcome-layup.js';

export const TICK_MS = 90;
/** Ticks on the rim. 36 × 90 ms is a little over three seconds. */
export const HANG = 36;
const RISE = 10;
const STUFF = 8;
const DROP = 12;
const LAND = 6;
const DRIBBLE = 6;
const DRIBBLE_DROP = 7;
const RUN_STEP = 3;
const BACK_STEP = 4;
const BALL_R = 4;
/** Cells of arm between the rim and the top of the head while he hangs. */
const HANG_GAP = 10;

function key(x, y) {
  return `${x},${y}`;
}

function lerp(a, b, t) {
  const u = Math.max(0, Math.min(1, t));
  return { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
}

function line(add, x0, y0, x1, y1, state = ON) {
  const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1);
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    add(Math.round(x0 + (x1 - x0) * t), Math.round(y0 + (y1 - y0) * t), state);
  }
}

/** Filled orange ball with a gap cross, so the seams read at this size. */
export function ballCells(cx, cy) {
  const dots = [];
  const x0 = Math.round(cx);
  const y0 = Math.round(cy);
  for (let y = -BALL_R; y <= BALL_R; y += 1) {
    for (let x = -BALL_R; x <= BALL_R; x += 1) {
      if (x * x + y * y > BALL_R * BALL_R) continue;
      if ((x === 0 || y === 0) && Math.abs(x) + Math.abs(y) > 0) continue;
      dots.push([x0 + x, y0 + y]);
    }
  }
  return dots;
}

export function buildHoop(band) {
  const { col, row, cols, rows } = band;
  if (cols < 96 || rows < 52) return null;
  const body = Math.min(24, Math.max(16, Math.floor(rows * 0.2)));
  let jump = Math.round(body * 1.7);
  const backOver = Math.round(body * 0.5);
  let sceneRows = body + jump + backOver + HANG_GAP + 6;
  const limit = rows - 2;
  if (sceneRows > limit) {
    jump -= sceneRows - limit;
    sceneRows = limit;
  }
  if (jump < Math.round(body * 0.8)) return null;
  const floor = row + sceneRows - 2 + Math.floor((rows - sceneRows) * 0.28);
  const rimY = floor - body - jump - HANG_GAP;
  const backR = col + cols - 3;
  const backW = 11;
  const backL = backR - backW + 1;
  const backTop = rimY - backOver;
  const backBot = rimY + Math.round(body * 0.42);
  const rimW = Math.max(22, Math.round(body * 0.95));
  const rimR = backL;
  const rimL = rimR - rimW;
  const rimBot = rimY + 3;
  // He hangs on the near edge. The ball goes through further along the rim.
  const hangX = rimL + 6;
  const dunkX = rimL + Math.round(rimW * 0.62);
  if (rimL < col + 40 || backTop < row + 1) return null;

  const cells = [];
  const set = new Map();
  const add = (x, y, state = ON) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    const id = key(x, y);
    if (set.has(id)) return;
    cells.push([x, y, state]);
    set.set(id, state);
  };

  for (let x = col + 2; x <= backR; x += 1) add(x, floor);
  line(add, backL, backTop, backR, backTop);
  line(add, backL, backBot, backR, backBot);
  line(add, backL, backTop, backL, backBot);
  line(add, backR, backTop, backR, backBot);
  const box = 4;
  const bx = backL + Math.round((backW - box) / 2);
  const by = rimY - Math.round(box / 2);
  line(add, bx, by, bx + box, by);
  line(add, bx, by + box, bx + box, by + box);
  line(add, bx, by, bx, by + box);
  line(add, bx + box, by, bx + box, by + box);
  for (let x = rimL; x <= rimR; x += 1) {
    add(x, rimY, ORANGE);
    add(x, rimBot, ORANGE);
  }
  for (let y = 1; y <= 2; y += 1) add(rimL, rimY + y, ORANGE);
  // Dim, and only behind the ball, so the amber figure is not part of the net.
  const netBottom = rimBot + Math.max(8, Math.round(body * 0.34));
  const netL = hangX + 8;
  for (let i = 0; i <= 3; i += 1) {
    const x0 = netL + ((rimR - netL) * i) / 3;
    const x1 = dunkX + (x0 - dunkX) * 0.5;
    line(add, x0, rimBot, x1, netBottom, DIM);
  }
  for (let y = backBot; y <= floor; y += 1) {
    add(backR - 1, y);
    add(backR, y);
  }

  const gripL = { x: hangX - 6, y: rimY };
  const gripR = { x: hangX + 6, y: rimY };
  const px = col + 14;
  const takeoff = hangX - 8;
  const cycles = Math.max(2, Math.min(6, Math.ceil((takeoff - px) / RUN_STEP / DRIBBLE)));
  const approach = DRIBBLE * cycles;
  const rise = approach + RISE;
  const stuff = rise + STUFF;
  const hang = stuff + HANG;
  const fall = hang + DROP;
  const settle = fall + LAND;
  const total = settle + Math.max(1, Math.ceil((hangX - px) / BACK_STEP));
  return {
    cells,
    set,
    plan: {
      base: { floor, body },
      px,
      takeoff,
      gripL,
      gripR,
      hangX,
      dunkX,
      rimY,
      netBottom,
      floor,
      jump,
      approach,
      rise,
      stuff,
      hang,
      fall,
      settle,
      total,
    },
  };
}

function fallingBall(plan, t) {
  const { netBottom, floor, dunkX } = plan;
  const g = 0.55;
  const ground = floor - BALL_R;
  const y = netBottom + 0.5 * g * t * t;
  if (y <= ground) return { x: dunkX, y };
  const tHit = Math.sqrt((2 * (ground - netBottom)) / g);
  const after = t - tHit;
  const bounced = ground - (3.2 * after - 0.5 * g * after * after);
  return { x: dunkX, y: Math.min(ground, bounced) };
}

function dribble(x, f, floor) {
  const bounce = Math.abs(Math.cos((Math.PI * (f % DRIBBLE)) / DRIBBLE));
  const held = floor - BALL_R - DRIBBLE_DROP;
  const ground = floor - BALL_R;
  const ball = { x: x + 6, y: ground + (held - ground) * bounce };
  return { ball, hand: { x: ball.x, y: ball.y - BALL_R } };
}

/** Figure dots plus the ball centre at frame `f` of `plan`. */
export function hoopPose(plan, f) {
  const { base, px, takeoff, gripL, gripR, hangX, dunkX, rimY, floor, jump } = plan;
  const hip = floor - Math.round(base.body * 0.36);
  const stride = Math.floor(f / 2) % 2 ? 'strideA' : 'strideB';
  let x = px;
  let lift = 0;
  let legs = 'stand';
  let hand = { x: px + 4, y: hip };
  let grip = null;
  let ball = null;
  let absolute = false;

  if (f < plan.approach) {
    x = px + (takeoff - px) * (f / plan.approach);
    legs = stride;
    ({ ball, hand } = dribble(x, f, floor));
  } else if (f < plan.rise) {
    const u = (f - plan.approach) / RISE;
    const e = Math.sin((u * Math.PI) / 2);
    x = takeoff + (hangX - takeoff) * e;
    lift = jump * e;
    legs = 'tuck';
    const start = { x: takeoff + 8, y: floor - BALL_R - DRIBBLE_DROP };
    const end = { x: dunkX, y: rimY - BALL_R - 1 };
    ball = lerp(start, end, e);
    hand = { x: ball.x, y: ball.y + BALL_R * (2 * e - 1) };
  } else if (f < plan.stuff) {
    const u = (f - plan.rise) / STUFF;
    x = hangX;
    lift = jump;
    legs = 'tuck';
    absolute = true;
    hand = lerp({ x: dunkX, y: rimY - BALL_R }, gripR, u);
    grip = lerp({ x: hangX - 4, y: rimY + 8 }, gripL, u);
    const slam = Math.max(0, (u - 0.35) / 0.65);
    const top = rimY - BALL_R - 1;
    ball = { x: dunkX, y: top + slam * (plan.netBottom - top) };
  } else if (f < plan.hang) {
    const t = f - plan.stuff;
    x = hangX + Math.round(Math.sin(t * 0.32) * 2);
    lift = jump;
    legs = Math.floor(t / 5) % 2 ? 'hangA' : 'hangB';
    absolute = true;
    hand = gripR;
    grip = gripL;
    ball = fallingBall(plan, t);
  } else if (f < plan.fall) {
    const u = (f - plan.hang) / DROP;
    x = hangX;
    lift = jump * (1 - u * u);
    legs = u < 0.7 ? 'tuck' : 'stand';
    hand = lerp(gripR, { x: hangX + 4, y: hip }, u);
    ball = { x: dunkX, y: floor - BALL_R };
  } else if (f < plan.settle) {
    x = hangX;
    hand = { x: hangX + 4, y: hip };
    ball = { x: dunkX, y: floor - BALL_R };
  } else {
    const u = (f - plan.settle) / (plan.total - plan.settle);
    x = hangX + (px - hangX) * u;
    legs = stride;
    if (u < 0.22) {
      ball = lerp({ x: dunkX, y: floor - BALL_R }, { x: x + 6, y: floor - BALL_R }, u / 0.22);
      hand = { x: ball.x, y: ball.y - BALL_R };
    } else {
      ({ ball, hand } = dribble(x, f, floor));
    }
  }

  const rx = Math.round(x);
  const held = absolute ? hand : { x: hand.x - x + rx, y: hand.y };
  const figure = figureDots(base, rx, Math.round(lift), legs, held, grip);
  return { figure, ball };
}

export function stillFrame(plan) {
  return plan.stuff + Math.floor(HANG / 2);
}

