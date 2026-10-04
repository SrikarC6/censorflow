/**
 * Layup timeline for the welcome scene.
 *
 * The figure picks the word out of its basket, runs at the can, jumps, lays
 * the word in off a short arc, lands, and jogs back. All positions are board
 * cells (y grows downward); frames count timer ticks within one cycle.
 */

const REACH = 8;
const LIFT = 5;
const RUN_STEP = 3;
/** Ticks per dribble, hand to floor and back. The run is a whole number of these. */
const DRIBBLE = 6;
/** Rows between the word's carry height and the floor; the dribble's drop. */
const DRIBBLE_DROP = 7;
const JUMP_UP = 5;
const FLY = 10;
const LAND = 5;
const SINK = 8;
const BACK_STEP = 4;
export const HEAD_R = 5;
/** Hand distance ahead of the body while carrying and at release. */
const ARM = 5;
/** Forward drift while airborne. */
const DRIFT = 4;
/** Clear columns between the word's right edge and the can's left wall at release. */
const RIM_GAP = 2;
/** Arc height above the release point. */
const LOFT = 6;
const JUMP_FRAC = 0.3;

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

/** Loftiest parabola over `T` ticks that still crests at or below `top`. */
function solveShot(x0, y0, x1, y1, top, T) {
  const a = (y1 - y0) / T;
  const b = 0.5 * T;
  let lo = 0.08;
  let hi = 3;
  let g = lo;
  for (let n = 0; n < 14; n += 1) {
    const mid = (lo + hi) / 2;
    const vy = a - b * mid;
    const yA = vy < 0 ? y0 - (vy * vy) / (2 * mid) : y0;
    if (vy < 0 && yA >= top) {
      g = mid;
      lo = mid;
    } else hi = mid;
  }
  return { vx: (x1 - x0) / T, vy: a - b * g, g };
}

function flight(plan, t) {
  const { release, shot } = plan;
  return { x: release.x + shot.vx * t, y: release.y + shot.vy * t + 0.5 * shot.g * t * t };
}

/** Per-word plan: takeoff, release point, arc, and phase start frames. */
export function planLayup(base, glyph) {
  const halfW = Math.ceil(glyph.cols / 2);
  const halfH = Math.ceil(glyph.rows / 2);
  const { px, floor, body, top, arrive, canL } = base;
  const jump = Math.round(body * JUMP_FRAC);
  const takeoff = canL - RIM_GAP - 2 * halfW - ARM - DRIFT;
  const land = takeoff + DRIFT;
  const apexTop = floor - body - jump;
  const release = { x: land + ARM + halfW, y: Math.max(top + 1, apexTop + 1 - halfH) };
  const shot = solveShot(release.x, release.y, arrive.x, arrive.y, Math.max(top, release.y - LOFT), FLY);
  const lift = REACH;
  const run = lift + LIFT;
  const up = run + DRIBBLE * Math.max(1, Math.ceil((takeoff - px) / RUN_STEP / DRIBBLE));
  const fly = up + JUMP_UP;
  const sink = fly + FLY;
  const back = sink + SINK;
  const total = back + Math.max(1, Math.ceil((land - px) / BACK_STEP));
  return { base, glyph, halfW, halfH, jump, takeoff, land, release, shot, lift, run, up, fly, sink, back, total };
}

/**
 * Stick figure at column `x`, raised `lift` cells, legs in `legs` pose.
 *
 * `hand` is the forward hand, in board cells. `grip`, when passed, is the other
 * hand — the rim hold uses it so both arms stay on a fixed point while the body
 * swings. `face` is 1 toward the right and -1 toward the left. The layup leaves
 * both empty and keeps the pose's usual back arm.
 */
export function figureDots(base, x, lift, legs, hand, grip = null, face = 1) {
  const { floor, body } = base;
  const s = face < 0 ? -1 : 1;
  const headY = floor - body + HEAD_R - lift;
  const shoulderY = headY + HEAD_R + 2;
  const hipY = floor - Math.round(body * 0.36) - lift;
  const foot = floor - lift;
  const pts = [];
  for (let y = -HEAD_R; y <= HEAD_R; y += 1) {
    for (let dx = -HEAD_R; dx <= HEAD_R; dx += 1) {
      if (dx * dx + y * y <= HEAD_R * HEAD_R) pts.push([x + dx, headY + y]);
    }
  }
  for (let y = shoulderY; y <= hipY; y += 1) pts.push([x, y]);
  const feet = {
    stand: [[x - 4 * s, foot], [x + 4 * s, foot]],
    strideA: [[x + 5 * s, foot], [x - 4 * s, foot - 2]],
    strideB: [[x - 3 * s, foot], [x + 3 * s, foot - 2]],
    tuck: [[x - 1 * s, foot], [x + 5 * s, foot - 4]],
    hangA: [[x - 2 * s, foot - 1], [x + 3 * s, foot]],
    hangB: [[x - 3 * s, foot], [x + 2 * s, foot - 1]],
  }[legs];
  const backHand = grip
    ? [Math.round(grip.x), Math.round(grip.y)]
    : {
        stand: [x - 6 * s, hipY],
        strideA: [x - 6 * s, shoulderY + 3],
        strideB: [x - 4 * s, hipY + 1],
        tuck: [x - 6 * s, shoulderY - 2],
        hangA: [x - 5 * s, shoulderY - 12],
        hangB: [x - 4 * s, shoulderY - 12],
      }[legs];
  pts.push(...segment(x - 2 * s, shoulderY, backHand[0], backHand[1]));
  feet.forEach(([fx, fy]) => pts.push(...segment(x, hipY, fx, fy)));
  pts.push(...segment(x + s, shoulderY, Math.round(hand.x), Math.round(hand.y)));
  return pts;
}

function carry(plan, x, lift) {
  return { x: x + ARM + plan.halfW, y: plan.base.floor - plan.halfH - DRIBBLE_DROP - lift };
}

function trailOf(plan, t, wordX) {
  const dots = [];
  let prev = null;
  for (let i = 0; i < t; i += 0.4) {
    const p = flight(plan, i);
    const x = Math.round(p.x);
    const y = Math.round(p.y);
    if (x >= wordX - plan.halfW - 1) continue;
    if (prev && Math.abs(prev[0] - x) + Math.abs(prev[1] - y) < 4) continue;
    dots.push([x, y]);
    prev = [x, y];
  }
  return dots;
}

/** Frame within the trailing reduced-motion still: mid-arc. */
export function stillFrame(plan) {
  return plan.fly + Math.floor(FLY * 0.4);
}

/** Everything that moves at frame `f`: figure dots, word centre, trail, clip row. */
export function layupPose(plan, f) {
  const { base, halfW, halfH, jump, takeoff, land, release } = plan;
  const { px, floor, body, basket, arrive, mouth } = base;
  const hipY = floor - Math.round(body * 0.36);
  const toHand = (w) => ({ x: w.x - halfW, y: w.y - halfH });
  const stride = Math.floor(f / 2) % 2 ? 'strideA' : 'strideB';
  let x = px;
  let lift = 0;
  let legs = 'stand';
  let word = null;
  let hand = { x: px + 4, y: hipY };
  let trail = [];
  if (f < plan.lift) {
    word = basket;
    hand = lerp(hand, toHand(basket), f / REACH);
  } else if (f < plan.run) {
    word = lerp(basket, carry(plan, px, 0), (f - plan.lift) / LIFT);
    hand = toHand(word);
  } else if (f < plan.up) {
    x = px + (takeoff - px) * ((f - plan.run) / (plan.up - plan.run));
    legs = stride;
    const held = carry(plan, x, 0);
    const bounce = Math.abs(Math.cos((Math.PI * ((f - plan.run) % DRIBBLE)) / DRIBBLE));
    const ground = floor - halfH;
    word = { x: held.x, y: ground + (held.y - ground) * bounce };
    hand = toHand({ x: held.x, y: held.y + (1 - bounce) * 2 });
  } else if (f < plan.fly) {
    const u = (f - plan.up) / JUMP_UP;
    x = takeoff + DRIFT * u;
    lift = jump * Math.sin((u * Math.PI) / 2);
    legs = 'tuck';
    word = lerp(carry(plan, x, lift), release, u);
    hand = toHand(word);
  } else if (f < plan.sink) {
    const t = f - plan.fly;
    x = land;
    lift = t < LAND ? jump * Math.cos(((t / LAND) * Math.PI) / 2) : 0;
    legs = t < LAND ? 'tuck' : 'stand';
    word = flight(plan, t);
    hand = lerp(toHand(release), { x: land + 4, y: hipY }, t / FLY);
    trail = trailOf(plan, t, word.x);
  } else if (f < plan.back) {
    x = land;
    const n = (f - plan.sink) / SINK;
    word = { x: arrive.x, y: arrive.y + n * (plan.glyph.rows + 1) };
    hand = { x: land + 4, y: hipY };
    trail = trailOf(plan, FLY, arrive.x);
  } else {
    x = land + (px - land) * ((f - plan.back) / (plan.total - plan.back));
    legs = stride;
    hand = { x: x + 4, y: hipY };
  }
  const rx = Math.round(x);
  const figure = figureDots(base, rx, Math.round(lift), legs, { x: hand.x - x + rx, y: hand.y });
  const clip = f >= plan.sink ? mouth : Infinity;
  return { figure, word, trail, clip };
}
