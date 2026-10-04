/**
 * Compact 3x5 dot glyphs for the welcome scene's thrown words, which sit next
 * to a figure only ~20 dots tall. Covers just the letters those words use.
 * Each row is a bit mask with the MSB as the leftmost column.
 */

const GLYPHS = {
  A: [0b010, 0b101, 0b111, 0b101, 0b101],
  B: [0b110, 0b101, 0b110, 0b101, 0b110],
  C: [0b011, 0b100, 0b100, 0b100, 0b011],
  E: [0b111, 0b100, 0b110, 0b100, 0b111],
  F: [0b111, 0b100, 0b110, 0b100, 0b100],
  H: [0b101, 0b101, 0b111, 0b101, 0b101],
  K: [0b101, 0b101, 0b110, 0b101, 0b101],
  P: [0b110, 0b101, 0b110, 0b100, 0b100],
  R: [0b110, 0b101, 0b110, 0b101, 0b101],
  S: [0b011, 0b100, 0b010, 0b001, 0b110],
  T: [0b111, 0b010, 0b010, 0b010, 0b010],
  U: [0b101, 0b101, 0b101, 0b101, 0b111],
  W: [0b101, 0b101, 0b101, 0b111, 0b101],
  Y: [0b101, 0b101, 0b010, 0b010, 0b010],
  '*': [0b000, 0b101, 0b010, 0b101, 0b000],
};

const COLS = 3;
const ROWS = 5;

/** Lit cells for `text` (uppercased), one blank column between glyphs. */
export function layoutTiny(text) {
  const cells = [];
  const chars = [...text.toUpperCase()];
  chars.forEach((ch, i) => {
    const rows = GLYPHS[ch];
    if (!rows) return;
    rows.forEach((mask, y) => {
      for (let c = 0; c < COLS; c += 1) {
        if (mask & (1 << (COLS - 1 - c))) cells.push({ x: i * (COLS + 1) + c, y });
      }
    });
  });
  return { cells, cols: Math.max(0, chars.length * (COLS + 1) - 1), rows: ROWS };
}
