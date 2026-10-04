/**
 * Discs, and a standalone field for the font specimen.
 *
 * The full-window board paints through `attachPaint`. This is the shared disc
 * and the one-off canvas `font-test.html` uses, which has no cell buffer.
 */
import { DISC_FILL } from './flipdisc.js';

export function readColours() {
  const style = getComputedStyle(document.documentElement);
  const pick = (name, fallback) => (style.getPropertyValue(name) || fallback).trim();
  return {
    on: pick('--on', '#FFB800'),
    off: pick('--off', '#1C2030'),
    bg: pick('--bg', '#05080D'),
    hi: pick('--on-hi', 'rgba(255,230,140,0.42)'),
    dim: pick('--on-dim', '#6B5620'),
    plateBg: pick('--plate-bg', '') || pick('--bg', '#05080D'),
    plateLine: pick('--plate-line', '') || pick('--line', '#222836'),
    go: pick('--go', '#2FBF71'),
    stop: pick('--stop', '#E5484D'),
  };
}

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
  { pitch, cols, rows, lit = [], colours = readColours(), paintField = true, ink = null },
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
    // Wipe the cell first: with a field underneath, the unlit disc has to be
    // erased before the lit one lands. The fill is the background colour, never
    // the lit colour - a lit cell is a disc, never a square.
    if (paintField) {
      ctx.fillStyle = colours.bg;
      ctx.fillRect(x, y, pitch, pitch);
    }
    // `ink` lets a caller draw the same specimen in a semantic colour, which is
    // how an HTML chip and a canvas button end up with the same lettering.
    drawDisc(ctx, x + pitch / 2, y + pitch / 2, radius, ink ?? colours.on);
    if (!ink) drawHighlight(ctx, x + pitch / 2, y + pitch / 2, radius, colours.hi);
  }
}

/**
 * A lit disc: a filled circle, plus a smaller offset highlight so it reads as
 * a physical flap catching the light rather than a flat pixel.
 */
export function drawDisc(ctx, cx, cy, radius, on) {
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = on;
  ctx.fill();
}

export function drawHighlight(ctx, cx, cy, radius, colour) {
  ctx.beginPath();
  ctx.arc(cx - radius * 0.22, cy - radius * 0.22, radius * 0.32, 0, Math.PI * 2);
  ctx.fillStyle = colour;
  ctx.fill();
}
