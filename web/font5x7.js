/**
 * 5x7 flip-disc glyphs. Each row is a 5-bit mask and the MSB is the leftmost
 * column, so 0b10001 is a row with only its two edges lit.
 *
 * Ported from the `lib/flip-font.ts` of the flip-disc portfolio prototype.
 * Added there: < > _ = ; @ $ ÷ and the four arrows.
 *
 * The set is deliberately uppercase-only: transit and LED signage never sets
 * lowercase, and 5x7 lowercase is unreadable on a dot board. `glyphFor`
 * uppercases its input, so "abc" renders as "ABC".
 */

export const GLYPH_COLS = 5;
export const GLYPH_ROWS = 7;

/** One dot column of breathing room, in font pixels, so it scales with the glyph. */
export const LETTER_GAP = 1;
/** Two dot columns between words. */
export const WORD_GAP = 2;

/** Written in binary so a wrong bit is visible when reading the source. */
const FONT = {
  A: [0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
  B: [0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110],
  C: [0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110],
  D: [0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110],
  E: [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111],
  F: [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000],
  G: [0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110],
  H: [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
  I: [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b11111],
  J: [0b00111, 0b00010, 0b00010, 0b00010, 0b00010, 0b10010, 0b01100],
  K: [0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001],
  L: [0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111],
  M: [0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001],
  N: [0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001],
  O: [0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
  P: [0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000],
  Q: [0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101],
  R: [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
  S: [0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110],
  T: [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
  U: [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
  V: [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100],
  W: [0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010],
  X: [0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001],
  Y: [0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100],
  Z: [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111],

  0: [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
  1: [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
  2: [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
  3: [0b11111, 0b00010, 0b00100, 0b00010, 0b00001, 0b10001, 0b01110],
  4: [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
  5: [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
  6: [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
  7: [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
  8: [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
  9: [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],

  ' ': [0, 0, 0, 0, 0, 0, 0],

  // Punctuation and symbols.
  '.': [0, 0, 0, 0, 0, 0, 0b00100],
  ',': [0, 0, 0, 0, 0, 0b00100, 0b01000],
  ':': [0, 0b00100, 0, 0, 0b00100, 0, 0],
  ';': [0, 0, 0b00100, 0, 0b00100, 0, 0b01000],
  '/': [0b00001, 0b00010, 0b00010, 0b00100, 0b01000, 0b01000, 0b10000],
  '\\': [0b10000, 0b01000, 0b01000, 0b00100, 0b00010, 0b00010, 0b00001],
  '-': [0, 0, 0, 0b11111, 0, 0, 0],
  '_': [0, 0, 0, 0, 0, 0, 0b11111],
  '+': [0, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0],
  '=': [0, 0, 0b11111, 0, 0b11111, 0, 0],
  '<': [0b00010, 0b00100, 0b01000, 0b10000, 0b01000, 0b00100, 0b00010],
  '>': [0b01000, 0b00100, 0b00010, 0b00001, 0b00010, 0b00100, 0b01000],
  '!': [0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0, 0b00100],
  '?': [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0, 0b00100],
  '&': [0b01100, 0b10010, 0b10100, 0b01000, 0b10101, 0b10010, 0b01101],
  '#': [0b01010, 0b01010, 0b11111, 0b01010, 0b11111, 0b01010, 0b01010],
  '%': [0b11001, 0b11010, 0b00010, 0b00100, 0b01000, 0b01011, 0b10011],
  $: [0b00100, 0b01111, 0b10100, 0b01110, 0b00101, 0b11110, 0b00100],
  '@': [0b01110, 0b10001, 0b10111, 0b10101, 0b10111, 0b10000, 0b01110],
  "'": [0b00100, 0b00100, 0, 0, 0, 0, 0],
  '"': [0b01010, 0b01010, 0, 0, 0, 0, 0],
  '*': [0b00100, 0b10101, 0b01110, 0b00100, 0b01110, 0b10101, 0b00100],
  '(': [0b00100, 0b01000, 0b10000, 0b10000, 0b10000, 0b01000, 0b00100],
  ')': [0b00100, 0b00010, 0b00001, 0b00001, 0b00001, 0b00010, 0b00100],
  '[': [0b00110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00110],
  ']': [0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01100],
  '{': [0b00010, 0b00100, 0b00100, 0b01000, 0b00100, 0b00100, 0b00010],
  '}': [0b01000, 0b00100, 0b00100, 0b00010, 0b00100, 0b00100, 0b01000],
  '·': [0, 0, 0, 0b00100, 0, 0, 0],
  '–': [0, 0, 0, 0b11111, 0, 0, 0], // en dash
  '—': [0, 0, 0b11111, 0b11111, 0b11111, 0, 0], // em dash
  '|': [0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
  // A plain "x" means multiply here, so it gets the same glyph as the times sign.
  x: [0, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0],
  '×': [0, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0], // times sign
  '÷': [0, 0b00100, 0, 0b11111, 0, 0b00100, 0], // divide

  // Arrows, for stage transitions and A/B playback controls.
  '→': [0, 0b00100, 0b00010, 0b11111, 0b00010, 0b00100, 0], // right arrow
  '←': [0, 0b00100, 0b01000, 0b11111, 0b01000, 0b00100, 0], // left arrow
  '↑': [0b00100, 0b01110, 0b10101, 0b00100, 0b00100, 0b00100, 0b00100], // up arrow
  '↓': [0b00100, 0b00100, 0b00100, 0b00100, 0b10101, 0b01110, 0b00100], // down arrow
  '▶': [0b01000, 0b01100, 0b01110, 0b01111, 0b01110, 0b01100, 0b01000], // play
  '■': [0, 0b01110, 0b01110, 0b01110, 0b01110, 0b01110, 0], // stop
  '•': [0, 0, 0b01110, 0b01110, 0b01110, 0, 0], // bullet
};

const QUESTION = FONT['?'];

/**
 * Rows of a glyph, uppercased, with `?` for anything the set does not carry.
 *
 * The literal character is tried first, then its uppercase form. That order is
 * what makes the one deliberate lowercase key work: `x` is a multiplication
 * sign here, and uppercasing first would quietly turn every "x" into "X".
 */
export function glyphFor(char) {
  const key = String(char);
  return FONT[key] ?? FONT[key.toUpperCase()] ?? QUESTION;
}

/** True when the set has a real glyph for `char` (so callers can warn). */
export function hasGlyph(char) {
  const key = String(char);
  return Object.hasOwn(FONT, key) || Object.hasOwn(FONT, key.toUpperCase());
}

/** Every glyph in the set, in declaration order. */
export function glyphKeys() {
  return Object.keys(FONT);
}

/**
 * Scale2x (EPX): doubles resolution while rounding diagonals instead of
 * stair-stepping them, so "A" at 4x still reads as an "A" rather than a
 * staircase. Applied repeatedly, which is why only powers of two come out
 * exact; `pickScale` only ever hands it 1, 2 or 4.
 */
function scale2x(src) {
  const h = src.length;
  const w = src[0]?.length ?? 0;
  const at = (r, c) => (r >= 0 && r < h && c >= 0 && c < w ? src[r][c] : false);
  const out = Array.from({ length: h * 2 }, () => new Array(w * 2).fill(false));
  for (let r = 0; r < h; r += 1) {
    for (let c = 0; c < w; c += 1) {
      const p = src[r][c];
      const up = at(r - 1, c);
      const right = at(r, c + 1);
      const left = at(r, c - 1);
      const down = at(r + 1, c);
      out[r * 2][c * 2] = left === up && left !== down && up !== right ? up : p;
      out[r * 2][c * 2 + 1] = up === right && up !== left && right !== down ? right : p;
      out[r * 2 + 1][c * 2] = down === left && down !== right && left !== up ? left : p;
      out[r * 2 + 1][c * 2 + 1] = right === down && right !== up && down !== left ? down : p;
    }
  }
  return out;
}

const bitmapCache = new Map();

/** Glyph at `scale` discs per font pixel. `scale` must be a power of two. */
export function glyphBitmap(char, scale = 1) {
  // Keyed on the raw character, not its uppercase form: "x" and "X" are
  // different glyphs here and must not share a cache entry.
  const key = `${String(char)}@${scale}`;
  const cached = bitmapCache.get(key);
  if (cached) return cached;
  let bitmap = glyphFor(char).map((bits) =>
    Array.from({ length: GLYPH_COLS }, (_, col) => ((bits >> (GLYPH_COLS - 1 - col)) & 1) === 1),
  );
  for (let s = 1; s < scale; s *= 2) bitmap = scale2x(bitmap);
  bitmapCache.set(key, bitmap);
  return bitmap;
}

/**
 * Width and height of `text` in grid columns and rows.
 * Gaps are counted in font pixels so they grow with the scale and the
 * proportions hold at every size.
 */
export function measureFlipText(
  text,
  scale = 1,
  letterGap = LETTER_GAP,
  wordGap = WORD_GAP,
) {
  const glyphCols = GLYPH_COLS * scale;
  const glyphRows = GLYPH_ROWS * scale;
  const lines = String(text).split('\n');
  const widths = lines.map((line) => {
    let cols = 0;
    for (const ch of line) {
      cols += ch === ' ' ? wordGap * scale : glyphCols + letterGap * scale;
    }
    return Math.max(0, cols - letterGap * scale);
  });
  return {
    lines,
    widths,
    cols: Math.max(0, ...widths),
    rows: lines.length * glyphRows + Math.max(0, lines.length - 1) * scale,
  };
}

/** How many grid columns `text` needs at `scale`. */
export function textCols(text, scale = 1, letterGap = LETTER_GAP, wordGap = WORD_GAP) {
  return measureFlipText(text, scale, letterGap, wordGap).cols;
}

/**
 * Greedy word wrap against a known column count.
 * Returns null if any single word is wider than `maxCols`, which is the
 * caller's cue to drop to a smaller scale instead of overflowing the board.
 */
export function wrapText(
  text,
  maxCols,
  scale = 1,
  letterGap = LETTER_GAP,
  wordGap = WORD_GAP,
) {
  const out = [];
  for (const line of String(text).split('\n')) {
    let current = '';
    for (const word of line.split(' ')) {
      if (textCols(word, scale, letterGap, wordGap) > maxCols) return null;
      const next = current ? `${current} ${word}` : word;
      if (textCols(next, scale, letterGap, wordGap) <= maxCols) {
        current = next;
      } else {
        out.push(current);
        current = word;
      }
    }
    out.push(current);
  }
  return out.join('\n');
}

/**
 * First scale from `scales` at which `text` wraps inside `maxCols`.
 * Falls back to the smallest scale with the text unwrapped, so a single
 * over-long word still renders rather than vanishing.
 */
export function pickScale(text, maxCols, scales = [4, 2, 1]) {
  for (const scale of scales) {
    const wrapped = wrapText(text, maxCols, scale);
    if (wrapped !== null) return { scale, text: wrapped };
  }
  return { scale: scales[scales.length - 1], text: String(text) };
}

/**
 * One entry per dot the text lights, positioned in grid coordinates.
 * `x` and `y` are whole column/row indices rather than pixels, so the caller
 * can blit straight into a grid buffer.
 */
export function layoutFlipCells(
  text,
  scale = 1,
  { letterGap = LETTER_GAP, wordGap = WORD_GAP, center = false } = {},
) {
  const glyphCols = GLYPH_COLS * scale;
  const glyphRows = GLYPH_ROWS * scale;
  const { lines, widths, cols, rows } = measureFlipText(text, scale, letterGap, wordGap);
  const cells = [];
  lines.forEach((line, lineIndex) => {
    let cursor = center ? Math.floor((cols - widths[lineIndex]) / 2) : 0;
    const y0 = lineIndex * (glyphRows + scale);
    for (const ch of line) {
      if (ch === ' ') {
        cursor += wordGap * scale;
        continue;
      }
      const bitmap = glyphBitmap(ch, scale);
      for (let row = 0; row < glyphRows; row += 1) {
        for (let col = 0; col < glyphCols; col += 1) {
          if (bitmap[row][col]) cells.push({ x: cursor + col, y: y0 + row });
        }
      }
      cursor += glyphCols + letterGap * scale;
    }
  });
  return { cells, cols, rows };
}