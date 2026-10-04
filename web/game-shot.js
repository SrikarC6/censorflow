/**
 * 2v2 timeline for the result screen.
 *
 * Four copies of the welcome stick figure, amber against blue, one orange
 * basketball, and a hoop at each end. The finish (two, three, layup, hang)
 * lives in `game-variants.js`. Positions are board cells (y grows downward).
 */
import { BLUE, DIM, ON, ORANGE } from './flipdisc.js';
import { figureDots } from './welcome-layup.js';
import {
  PASS_AT,
  PASS_N,
  RESET_N,
  SCORE_AT,
  SHOT_AT,
  SHOT_N,
  finish,
  locate,
  marksOf,
  playKind,
} from './game-variants.js';

const BALL_R = 4;
const DRIBBLE = 6;
const DRIBBLE_DROP = 7;

function key(x, y) {
  return `${x},${y}`;
}

function lerp(a, b, t) {
  const u = Math.max(0, Math.min(1, t));
  return a + (b - a) * u;
}

function mix(a, b, t) {
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

function along(plan, dir, frac) {
  const u = Math.max(0, Math.min(1, frac));
  const { spotL, spotR } = plan;
  return dir > 0 ? spotL + (spotR - spotL) * u : spotR - (spotR - spotL) * u;
}

/** A hoop at the left (`dir` -1) or right (`dir` 1) end of the court. */
function addHoop(add, dir, box) {
  const { col, cols, floor, rimY, body } = box;
  const backW = 8;
  const rimW = Math.max(14, Math.round(body * 0.75));
  const edge = dir > 0 ? col + cols - 2 : col + 1;
  const backFar = edge;
  const backNear = edge - dir * (backW - 1);
  const backL = Math.min(backFar, backNear);
  const backR = Math.max(backFar, backNear);
  const backTop = rimY - box.backOver;
  const backBot = rimY + Math.round(body * 0.3);
  line(add, backL, backTop, backR, backTop);
  line(add, backL, backBot, backR, backBot);
  line(add, backL, backTop, backL, backBot);
  line(add, backR, backTop, backR, backBot);
  const mark = 3;
  const bx = backL + Math.floor((backW - mark) / 2);
  const by = rimY - 1;
  line(add, bx, by, bx + mark, by);
  line(add, bx, by + mark, bx + mark, by + mark);
  line(add, bx, by, bx, by + mark);
  line(add, bx + mark, by, bx + mark, by + mark);
  const rimNear = (dir > 0 ? backL : backR) - dir * rimW;
  const rimFar = dir > 0 ? backL : backR;
  const rimL = Math.min(rimNear, rimFar);
  const rimR = Math.max(rimNear, rimFar);
  const rimBot = rimY + 3;
  for (let x = rimL; x <= rimR; x += 1) {
    add(x, rimY, ORANGE);
    add(x, rimBot, ORANGE);
  }
  const cap = dir > 0 ? rimL : rimR;
  add(cap, rimY + 1, ORANGE);
  add(cap, rimY + 2, ORANGE);
  const mouth = Math.round(rimL + (rimR - rimL) * (dir > 0 ? 0.42 : 0.58));
  const hangX = dir > 0 ? rimL + 6 : rimR - 6;
  const netBottom = rimBot + Math.max(6, Math.round(body * 0.28));
  const netL = dir > 0 ? mouth - 1 : rimL + 2;
  const netR = dir > 0 ? rimR - 1 : mouth + 1;
  for (let i = 0; i <= 3; i += 1) {
    const x0 = netL + ((netR - netL) * i) / 3;
    const x1 = mouth + (x0 - mouth) * 0.45;
    line(add, x0, rimBot, x1, netBottom, DIM);
  }
  for (let y = backBot; y <= floor; y += 1) {
    add(edge, y);
    add(edge - dir, y);
  }
  return { mouth, rimY, netBottom, hangX, dunkX: mouth, spot: mouth - dir * (body + 4) };
}

export function buildGame(band) {
  const { col, row, cols, rows } = band;
  if (cols < 150 || rows < 36) return null;
  const floor = row + rows - 2;
  let body = Math.min(18, Math.max(14, Math.floor(rows * 0.3)));
  let jump = Math.round(body * 0.6);
  let extra = Math.round(body * 0.5);
  let backOver = Math.round(body * 0.42);
  const fits = () => body + jump + extra + backOver + 8 <= rows;
  while (!fits() && jump > 6) jump -= 1;
  while (!fits() && backOver > 4) backOver -= 1;
  while (!fits() && extra > 0) extra -= 1;
  if (!fits()) return null;
  const rimY = floor - body - jump - extra - 4;
  const cells = [];
  const set = new Map();
  const add = (x, y, state = ON) => {
    if (x < col || x >= col + cols || y < row || y >= row + rows) return;
    const id = key(x, y);
    if (set.has(id)) return;
    cells.push([x, y, state]);
    set.set(id, state);
  };
  const left = addHoop(add, -1, { col, cols, floor, rimY, body, backOver });
  const right = addHoop(add, 1, { col, cols, floor, rimY, body, backOver });
  const spotL = left.spot;
  const spotR = right.spot;
  if (spotR - spotL < 80) return null;
  for (let x = col + 2; x < col + cols - 2; x += 1) add(x, floor);
  const mid = Math.round((spotL + spotR) / 2);
  for (let i = -2; i <= 2; i += 1) add(mid + i, floor);
  for (let i = 1; i <= 3; i += 1) add(mid, floor - i);
  return {
    cells,
    set,
    plan: {
      base: { floor, body }, floor, body, jump, extra, rimY, spotL, spotR, left, right, col, row, cols, rows,
    },
  };
}

function xAt(plan, dir, kind, role, f) {
  const step = marksOf(kind, f);
  if (!step) return along(plan, dir, 0.5);
  return along(plan, dir, lerp(step[0][role], step[1][role], step[2]));
}

function dribbleBall(x, f, floor, dir) {
  const bounce = Math.abs(Math.cos((Math.PI * (f % DRIBBLE)) / DRIBBLE));
  const held = floor - BALL_R - DRIBBLE_DROP;
  const ground = floor - BALL_R;
  const ball = { x: x + dir * 7, y: ground + (held - ground) * bounce };
  return { ball, hand: { x: ball.x, y: ball.y - BALL_R } };
}

function shotLift(f, jump) {
  if (f < SHOT_AT || f >= SCORE_AT) return 0;
  const u = (f - SHOT_AT) / SHOT_N;
  return jump * Math.sin(u * Math.PI);
}

function player(plan, x, lift, face, ink, hand, stride, f, grip = null, legs = null) {
  const { floor, body } = plan;
  const hip = floor - Math.round(body * 0.36) - lift;
  const held = hand || { x: x + face * 4, y: hip };
  const pose = legs || (lift > plan.jump * 0.7 ? 'tuck' : stride ? (Math.floor(f / 2) % 2 ? 'strideA' : 'strideB') : 'stand');
  return {
    ink,
    dots: figureDots(plan.base, Math.round(x), Math.round(lift), pose, held, grip, face),
  };
}

function place(plan, dir, f, kind) {
  const offense = dir > 0 ? ON : BLUE;
  const defense = dir > 0 ? BLUE : ON;
  const jump = shotLift(f, plan.jump);
  const running = f < PASS_AT;
  const at = (role) => xAt(plan, dir, kind, role, f);
  const handler = at('handler');
  const wing = at('wing');
  const chaser = at('chaser');
  const helper = at('helper');
  const handlerP = player(plan, handler, 0, dir, offense, null, running, f);
  const wingP = player(plan, wing, jump, dir, offense, null, running || f < SHOT_AT, f);
  const chaserP = player(plan, chaser, 0, -dir, defense, null, running, f);
  const helperP = player(plan, helper, jump * 0.4, -dir, defense, null, running, f);
  // Same four people every trip: amber A/B, then blue A/B.
  const players = dir > 0
    ? [handlerP, wingP, chaserP, helperP]
    : [chaserP, helperP, handlerP, wingP];
  return { handler, wing, players, handlerAt: dir > 0 ? 0 : 2, wingAt: dir > 0 ? 1 : 3 };
}

function applyWing(plan, dir, f, kind, posed) {
  const fin = finish(kind, f, plan, dir, (role, frame) => xAt(plan, dir, kind, role, frame));
  if (fin.wing) {
    const w = fin.wing;
    const ink = posed.players[posed.wingAt].ink;
    posed.players[posed.wingAt] = player(
      plan, w.x, w.lift, dir, ink, w.hand, false, f, w.grip, w.legs,
    );
  }
  return fin.ball;
}

function resetPose(plan, dir, f, kind, resetAt, nextKind) {
  const u = (f - resetAt) / RESET_N;
  const from = place(plan, dir, resetAt - 1, kind);
  applyWing(plan, dir, resetAt - 1, kind, from);
  const to = place(plan, -dir, 0, nextKind);
  const players = from.players.map((person, index) => {
    const ax = person.dots.reduce((sum, dot) => sum + dot[0], 0) / person.dots.length;
    const bx = to.players[index].dots.reduce((sum, dot) => sum + dot[0], 0) / person.dots.length;
    // Rise first, then cross, so heads are on different levels while the paths meet.
    const move = u < 0.25 ? 0 : Math.min(1, (u - 0.25) / 0.6);
    const x = lerp(ax, bx, move);
    const hop = [0, 22, 44, 66][index] * Math.sin(Math.PI * u);
    return player(plan, x, hop, x < bx ? 1 : -1, person.ink, null, true, f);
  });
  const hoop = dir > 0 ? plan.right : plan.left;
  const next = dribbleBall(to.handler, 0, plan.floor, -dir);
  const ball = mix({ x: hoop.mouth, y: plan.floor - BALL_R }, next.ball, u);
  return { players, ball };
}

/** Players and the ball centre for one frame of the game. */
export function gamePose(plan, frame) {
  const { kind, dir, f, resetAt, index } = locate(frame);
  if (f >= resetAt) return resetPose(plan, dir, f, kind, resetAt, playKind(index + 1));
  const posed = place(plan, dir, f, kind);
  const { floor } = plan;
  let ball;
  if (f < PASS_AT) {
    let hand;
    ({ ball, hand } = dribbleBall(posed.handler, f, floor, dir));
    const holder = posed.players[posed.handlerAt];
    posed.players[posed.handlerAt] = player(plan, posed.handler, 0, dir, holder.ink, hand, true, f);
  } else if (f < SHOT_AT) {
    const u = (f - PASS_AT) / PASS_N;
    const from = dribbleBall(posed.handler, PASS_AT, floor, dir).ball;
    const to = { x: posed.wing + dir * 6, y: floor - plan.body * 0.55 };
    ball = mix(from, to, u);
    ball.y -= Math.sin(u * Math.PI) * 8;
  } else {
    ball = applyWing(plan, dir, f, kind, posed);
  }
  return { players: posed.players, ball };
}

export function gameStill() {
  return SHOT_AT + 8;
}
