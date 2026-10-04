/**
 * Board animation, opt-in.
 *
 * Ported from `lib/flip-motion.ts` and `FlipAllButton.tsx` in the flip-disc
 * portfolio prototype. This is a separate module from `flipdisc.js` on purpose:
 * the board itself has no animation at all, so a progress bar moves the instant
 * its event arrives, and `flipdisc.js` can be asserted to contain no
 * `requestAnimationFrame`. Anything that wants to move dots asks for it here.
 */

import { playRowFlip } from './flip-sound.js';
import { layoutFlipCells } from './font5x7.js';

/** Times for the full-board wipe, in milliseconds. */
const WAVE_MS = 1500;
const WAVE_JITTER_MS = 260;
const HOLD_MS = 350;
const FADE_MS = 2000;

/** How long to wait after the wipe before redrawing the real layout. */
const SETTLE_MS = 500;

const between = (min, max) => min + Math.random() * (max - min);

/**
 * Schedules the flips for one disc starting at `at` ms. A disc that has to
 * change sometimes stutters (flip, flip back, flip again); one that doesn't
 * occasionally twitches. Odd toggle counts change state, even ones don't.
 */
export function scheduleDisc(out, index, at, change, stutter = 0.22, twitch = 0.06) {
  if (change) {
    out.push({ at, index });
    if (Math.random() < stutter) {
      const back = at + between(60, 180);
      out.push({ at: back, index }, { at: back + between(60, 220), index });
    }
  } else if (Math.random() < twitch) {
    out.push({ at, index }, { at: at + between(60, 180), index });
  }
}

/**
 * Plays toggles against the clock. Returns a cancel function.
 * `onFrame` receives how many discs flipped this frame, which is what
 * `playRowFlip` uses to decide its level.
 */
export function runToggles(events, flip, onFrame, done) {
  events.sort((a, b) => a.at - b.at);
  const start = performance.now();
  let next = 0;
  let raf = 0;
  const frame = (now) => {
    const elapsed = now - start;
    let flipped = 0;
    while (next < events.length && events[next].at <= elapsed) {
      flip(events[next].index);
      next += 1;
      flipped += 1;
    }
    if (flipped) onFrame(flipped);
    if (next < events.length) raf = requestAnimationFrame(frame);
    else done?.();
  };
  raf = requestAnimationFrame(frame);
  return () => cancelAnimationFrame(raf);
}

export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * The whole board dances: a wave of light travels from the top-left corner to
 * the bottom-right, the board holds fully lit, then every disc drops out at
 * random until the real layout is redrawn over it.
 *
 * Returns a cancel function, or null if the user prefers reduced motion.
 */
export function fullWipe(board) {
  if (prefersReducedMotion()) return null;
  const { cols, rows } = board;
  const at = (col, row) => col * rows + row;
  const light = (index) => board.cell(index % cols, Math.floor(index / cols), 1);

  const wave = [];
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const diagonal = (col / cols + row / rows) / 2;
      scheduleDisc(wave, at(col, row), diagonal * WAVE_MS + Math.random() * WAVE_JITTER_MS, true, 0.15, 0);
    }
  }

  const cancels = [];
  let wipeTimer = 0;
  let settleTimer = 0;

  cancels.push(
    runToggles(
      wave,
      light,
      (flipped) => playRowFlip(flipped, true),
      () => {
        wipeTimer = window.setTimeout(() => {
          const scatter = [];
          for (let index = 0; index < cols * rows; index += 1) {
            scheduleDisc(scatter, index, Math.pow(Math.random(), 0.75) * FADE_MS, true, 0.2, 0);
          }
          cancels.push(
            runToggles(
              scatter,
              (index) => board.cell(index % cols, Math.floor(index / cols), 0),
              (flipped) => playRowFlip(flipped, true),
              () => {
                settleTimer = window.setTimeout(() => board.redraw(), SETTLE_MS);
              },
            ),
          );
        }, HOLD_MS);
      },
    ),
  );

  return () => {
    cancels.forEach((cancel) => cancel());
    window.clearTimeout(wipeTimer);
    window.clearTimeout(settleTimer);
    board.redraw();
  };
}

/**
 * Background "aliveness": the occasional single disc flipping over in a part of
 * the board with nothing on it.
 *
 * Two rules keep this from being annoying, which is the whole brief:
 *   - it never touches a protected cell, so it cannot flicker the words;
 *   - it never touches more than a couple of discs at once, and never within
 *     `settle` of the last one.
 * Returns a stop function.
 */
export function startIdleFlips(board, { minGapMs = 1400, maxGapMs = 3400 } = {}) {
  let timer = 0;
  let stop = false;

  function flipOne() {
    const { cols, rows } = board;
    // Try a handful of times to find a free cell; give up rather than stall the
    // timer if the board is unusually full.
    for (let attempt = 0; attempt < 12; attempt += 1) {
      const col = Math.floor(Math.random() * cols);
      const row = Math.floor(Math.random() * rows);
      if (board.isProtected(col, row)) continue;
      const target = { col, row };
      board.cell(col, row, 1);
      playRowFlip(1, false);
      window.setTimeout(() => {
        board.cell(target.col, target.row, 0);
        playRowFlip(1, false);
      }, between(90, 190));
      return true;
    }
    return false;
  }

  function schedule() {
    if (stop) return;
    timer = window.setTimeout(() => {
      if (prefersReducedMotion()) {
        schedule();
        return;
      }
      flipOne();
      // Occasionally two at once, far apart, so it does not feel metronomic.
      if (Math.random() < 0.18) {
        window.setTimeout(() => {
          if (!stop) flipOne();
        }, between(220, 520));
      }
      schedule();
    }, between(minGapMs, maxGapMs));
  }

  schedule();
  return () => {
    stop = true;
    window.clearTimeout(timer);
  };
}

/**
 * A plate whose caption scrolls: text travelling right to left across a sign.
 *
 * This is the one piece of motion the design brief ruled out - "no scrolling
 * marquee" - and it is here because it was asked for by name once the plates
 * existed. It earns its place the way a departure board does: a line of dots
 * wider than its sign has to either scroll or truncate, and scrolling keeps the
 * whole sentence readable instead of its first few words.
 *
 * How it stays cheap, and why it never shows a seam:
 *   - the caption is laid out once into a plain array of lit cells, left-aligned
 *     in its own space, and never measured again;
 *   - scrolling is an offset into that array, not a re-layout, so a tick is one
 *     comparison per lit cell;
 *   - each cell is offered at two horizontal positions, one repeat apart, and
 *     whichever lands inside the sign is drawn. That is what makes the text
 *     continuous: the strip is treated as periodic, so the moment the offset
 *     passes the end of the caption the next repeat is already in place and
 *     there is nothing to reset to;
 *   - `gap` columns of air separate one repeat from the next, because the two are
 *     the same sentence and without a gap they read as one run-on word.
 *
 * Dots move one column per `stepMs` on a timer rather than on a frame callback:
 * at one column a tick there is nothing to interpolate, and a timer cannot spin
 * a CPU on a machine with nothing else to do.
 *
 * Honours `prefersReducedMotion` by drawing the first screenful and stopping.
 * Returns a stop function.
 */
export function startMarquee(
  board,
  { col, row, cols, text, scale = 1, font, stepMs = 45, gap = 14, sound = false } = {},
) {
  const one = layoutCells(text, scale, font, gap);
  const visible = cols - 4;
  if (one.width === 0 || visible <= 0) return () => {};

  const interior = { col: col + 2, row: row + 2, cols: visible, rows: one.height };
  // A whole number of repeats, so offset and offset + span look identical and the
  // wrap is invisible.
  const span = one.width * Math.max(1, Math.ceil(visible / one.width));

  function draw(offset) {
    board.plate({ col, row, cols, rows: one.height + 4, key: 'marquee' });
    board.fill(interior.col, interior.row, interior.cols, interior.rows, 0);
    const start = ((offset % span) + span) % span;
    for (const cell of one.cells) {
      for (let repeat = 0; repeat < 2; repeat += 1) {
        const x = cell.x + repeat * one.width - start;
        if (x < 0 || x >= interior.cols) continue;
        board.cell(interior.col + x, interior.row + cell.y, 1);
      }
    }
  }

  let offset = 0;
  draw(offset);

  if (prefersReducedMotion()) return () => {};

  let timer = 0;
  let stop = false;
  function step() {
    if (stop) return;
    offset += 1;
    draw(offset);
    if (sound && Math.random() < 0.12) playRowFlip(1, false);
    timer = window.setTimeout(step, stepMs);
  }
  timer = window.setTimeout(step, stepMs);

  return () => {
    stop = true;
    window.clearTimeout(timer);
  };
}

/**
 * Lay a caption out once, in its own coordinate space, and report how big it is.
 * `layoutFlipCells` centres on a column and returns coordinates relative to that
 * centre; the marquee wants a plain left-aligned bitmap starting at the origin.
 */
function layoutCells(text, scale, font, gap) {
  const cells = layoutFlipCells(text, scale, { font }).cells;
  if (cells.length === 0) return { cells: [], width: 0, height: 0 };
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const cell of cells) {
    if (cell.x < minX) minX = cell.x;
    if (cell.y < minY) minY = cell.y;
    if (cell.x > maxX) maxX = cell.x;
    if (cell.y > maxY) maxY = cell.y;
  }
  return {
    cells: cells.map((cell) => ({ x: cell.x - minX, y: cell.y - minY })),
    // The gap after the caption, in dots. Generous on purpose: the repeats are the
    // same sentence, so a small gap reads as a typo rather than as a pause.
    width: maxX - minX + 1 + gap,
    height: maxY - minY + 1,
  };
}
