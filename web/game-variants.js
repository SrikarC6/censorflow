/**
 * Finish for one possession of the result-screen game.
 *
 * The kind is an affine hash of the possession index, so painting the same
 * frame twice cannot reshuffle the trip. Every 20 possessions: 8 twos, 8
 * threes, 3 layups, 1 rim hang. Y grows downward.
 */

const CYCLE = 20;
// Permuted by (index * 7 + 3) % 20. That order is two, three, layup, hang, …
const MIX = [
  'two', 'three', 'three', 'two', 'hang',
  'two', 'two', 'three', 'layup', 'two',
  'three', 'two', 'three', 'three', 'two',
  'two', 'three', 'layup', 'three', 'layup',
];

export const DRIBBLE_N = 28;
export const PASS_N = 10;
export const SHOT_N = 12;
export const SCORE_N = 14;
export const RESET_N = 14;
export const RISE_N = 8;
export const HANG_N = 36;
export const DROP_N = 8;

export const PASS_AT = DRIBBLE_N;
export const SHOT_AT = PASS_AT + PASS_N;
export const SCORE_AT = SHOT_AT + SHOT_N;
export const RESET_AT = SCORE_AT + SCORE_N;
export const POSSESSION = RESET_AT + RESET_N;

export const HANG_HOLD = SHOT_AT + RISE_N;
export const HANG_END = HANG_HOLD + HANG_N;
export const HANG_DROP = HANG_END + DROP_N;

const BALL_R = 4;
const LOFT = { two: 8, three: 16, layup: 4 };

function pack(handler, wing, chaser, helper) {
  return { handler, wing, chaser, helper };
}

const STARTS = {
  two: pack(0.14, 0.38, 0.26, 0.74),
  three: pack(0.14, 0.4, 0.26, 0.72),
  layup: pack(0.14, 0.52, 0.26, 0.38),
  hang: pack(0.14, 0.58, 0.26, 0.4),
};

// pushed, passed, shot. The same order at both ends of a phase keeps bodies
// from running through each other. A three stays deep; a layup wing leads.
const PATH = {
  two: [pack(0.4, 0.6, 0.5, 0.78), pack(0.42, 0.64, 0.52, 0.8), pack(0.44, 0.7, 0.54, 0.84)],
  three: [pack(0.28, 0.48, 0.36, 0.7), pack(0.3, 0.5, 0.4, 0.7), pack(0.32, 0.5, 0.42, 0.68)],
  layup: [pack(0.42, 0.76, 0.54, 0.66), pack(0.48, 0.86, 0.6, 0.74), pack(0.54, 0.94, 0.66, 0.78)],
  hang: [pack(0.38, 0.74, 0.5, 0.62), pack(0.44, 0.8, 0.56, 0.66), pack(0.48, 0.86, 0.6, 0.72)],
};

export function playKind(index) {
  const n = ((index % CYCLE) + CYCLE) % CYCLE;
  return MIX[(n * 7 + 3) % CYCLE];
}

export function marksOf(kind, f) {
  const [pushed, passed, shot] = PATH[kind] || PATH.two;
  const start = STARTS[kind] || STARTS.two;
  if (f < PASS_AT) return [start, pushed, f / DRIBBLE_N];
  if (f < SHOT_AT) return [pushed, passed, (f - PASS_AT) / PASS_N];
  const rising = kind === 'hang' ? f < HANG_HOLD : f < SCORE_AT;
  const span = kind === 'hang' ? RISE_N : SHOT_N;
  if (rising) return [passed, shot, (f - SHOT_AT) / span];
  return [shot, shot, 1];
}

const lengths = Array.from({ length: CYCLE }, (_, i) => (
  playKind(i) === 'hang' ? HANG_DROP + RESET_N : POSSESSION
));
const starts = [];
let cursor = 0;
lengths.forEach((len) => {
  starts.push(cursor);
  cursor += len;
});
export const CYCLE_TICKS = cursor;

export function locate(frame) {
  const loop = ((frame % CYCLE_TICKS) + CYCLE_TICKS) % CYCLE_TICKS;
  let index = 0;
  while (index < CYCLE - 1 && starts[index + 1] <= loop) index += 1;
  const kind = playKind(index);
  return {
    index,
    kind,
    dir: index % 2 === 0 ? 1 : -1,
    f: loop - starts[index],
    resetAt: kind === 'hang' ? HANG_DROP : RESET_AT,
  };
}

function mix(a, b, t) {
  const u = Math.max(0, Math.min(1, t));
  return { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
}

function arc(from, to, u, loft) {
  const ball = mix(from, to, u);
  ball.y -= Math.sin(Math.max(0, Math.min(1, u)) * Math.PI) * loft;
  return ball;
}

function shotLift(f, jump) {
  if (f < SHOT_AT || f >= SCORE_AT) return 0;
  return jump * Math.sin(((f - SHOT_AT) / SHOT_N) * Math.PI);
}

/** Short gather: a few cells ahead of the body and up, never out at the ball. */
function shotHand(x, face, plan, lift) {
  const hip = plan.floor - Math.round(plan.body * 0.36) - lift;
  return { x: x + face * 6, y: hip - 7 };
}

function releaseFrame(kind) {
  return kind === 'layup' ? SHOT_AT + SHOT_N - 4 : SHOT_AT + 3;
}

function releasePoint(kind, plan, dir, xAt) {
  const f = releaseFrame(kind);
  const hand = shotHand(xAt('wing', f), dir, plan, shotLift(f, plan.jump));
  return { x: hand.x, y: hand.y - BALL_R };
}

function jumpFinish(kind, f, plan, dir, hoop, xAt) {
  const lift = shotLift(f, plan.jump);
  const wingX = xAt('wing', f);
  const rel = releaseFrame(kind);
  if (f < rel) {
    const hand = shotHand(wingX, dir, plan, lift);
    return {
      ball: { x: hand.x, y: hand.y - BALL_R },
      wing: { x: wingX, lift, hand, grip: null, legs: null },
    };
  }
  if (f < SCORE_AT) {
    const u = (f - rel) / (SCORE_AT - rel);
    const ball = arc(releasePoint(kind, plan, dir, xAt), {
      x: hoop.mouth,
      y: hoop.rimY - BALL_R,
    }, u, LOFT[kind]);
    return { ball, wing: null };
  }
  const u = (f - SCORE_AT) / SCORE_N;
  const ball = mix(
    { x: hoop.mouth, y: hoop.rimY + 2 },
    { x: hoop.mouth, y: plan.floor - BALL_R },
    u * u,
  );
  return { ball, wing: null };
}

function hangFinish(f, plan, dir, hoop, xAt) {
  const { hangX, rimY, dunkX } = hoop;
  const full = Math.max(8, plan.jump + plan.extra - 6);
  const riseU = Math.max(0, Math.min(1, (f - SHOT_AT) / RISE_N));
  const hold = f >= HANG_HOLD && f < HANG_END;
  const dropU = f >= HANG_END ? Math.min(1, (f - HANG_END) / DROP_N) : 0;
  const eased = Math.sin((riseU * Math.PI) / 2);
  const lift = full * (f >= HANG_END ? 1 - dropU * dropU : eased);
  const startX = xAt('wing', SHOT_AT);
  const sway = hold ? Math.round(Math.sin((f - HANG_HOLD) * 0.32) * 2) : 0;
  const x = f >= HANG_HOLD ? hangX + sway : startX + (hangX - startX) * eased;
  const hand = hold ? { x: hangX + 6, y: rimY } : shotHand(x, dir, plan, lift);
  const grip = hold ? { x: hangX - 6, y: rimY } : null;
  const legs = hold ? (Math.floor((f - HANG_HOLD) / 5) % 2 ? 'hangA' : 'hangB') : null;
  const rel = SHOT_AT + Math.round(RISE_N * 0.35);
  let ball;
  if (f < rel) {
    const held = shotHand(x, dir, plan, lift);
    ball = { x: held.x, y: held.y - BALL_R };
  } else if (f < HANG_HOLD) {
    const u = (f - rel) / (HANG_HOLD - rel);
    const at = SHOT_AT + Math.round(RISE_N * 0.35);
    const fromX = startX + (hangX - startX) * Math.sin((((at - SHOT_AT) / RISE_N) * Math.PI) / 2);
    const fromLift = full * Math.sin((((at - SHOT_AT) / RISE_N) * Math.PI) / 2);
    const from = shotHand(fromX, dir, plan, fromLift);
    ball = arc({ x: from.x, y: from.y - BALL_R }, { x: dunkX, y: rimY - BALL_R }, u, 4);
  } else {
    const u = Math.min(1, (f - HANG_HOLD) / (HANG_N * 0.55));
    ball = mix({ x: dunkX, y: rimY + 2 }, { x: dunkX, y: plan.floor - BALL_R }, u * u);
  }
  return { ball, wing: { x, lift, hand, grip, legs } };
}

/** Ball plus an optional wing override for the finish. The hand is never the ball. */
export function finish(kind, f, plan, dir, xAt) {
  const hoop = dir > 0 ? plan.right : plan.left;
  if (kind === 'hang') return hangFinish(f, plan, dir, hoop, xAt);
  return jumpFinish(kind, f, plan, dir, hoop, xAt);
}
