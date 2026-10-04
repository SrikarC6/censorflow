/**
 * Flip-disc glyphs. Each row is a bit mask and the MSB is the leftmost column,
 * so in a 5-wide set 0b10001 is a row with only its two edges lit, and in a
 * 7-wide set 0b1000001 is the same idea.
 *
 * Two sets live here:
 *
 *   serif - 7x9, the default. Serifs need room: a 1-dot flare at the top and
 *           foot of every vertical stem, and one extra column of width for the
 *           bowl letters to open out into. At the board's default pitch of 4
 *           that is a 28x36 CSS-pixel cell, about the size the 5x7 sans used to
 *           be at pitch 6.
 *   sans  - 5x7, the original transit-style set, kept so the two can be compared
 *           side by side on the font test page.
 *
 * The serif set was hand-authored for this project. The sans set was ported from
 * the `lib/flip-font.ts` of the flip-disc portfolio prototype, with < > _ = ; @ $
 * ÷ and the four arrows added there.
 *
 * Both sets are deliberately uppercase-only: transit and LED signage never sets
 * lowercase, and lowercase this small is unreadable on a dot board. `glyphFor`
 * uppercases its input, so "abc" renders as "ABC".
 */

export const LETTER_GAP = 1;
/** Two dot columns between words. */
export const WORD_GAP = 2;

/** One dot column of breathing room, in font pixels, so it scales with the glyph. */

/** Written in binary so a wrong bit is visible when reading the source. */
const SANS_GLYPHS = {
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

/**
 * The serif set: 7 columns by 9 rows, written in binary for the same reason.
 *
 * House style, so the letters look like one typeface:
 *   - a vertical stem is at column 1 or column 5;
 *   - it flares to three dots (`0110110`) at row 0 and at row 8, which is what
 *     actually reads as a serif at this size;
 *   - the crossbar of A, E, F, H, P and T sits on row 4, the middle row;
 *   - round letters open their corners into four-dot shoulders so they do not
 *     look like the sans versions scaled up.
 */
const SERIF_GLYPHS = {
  A: [0b0001000, 0b0001000, 0b0101010, 0b0101010, 0b0111110, 0b0101010, 0b0101010, 0b0101010, 0b1100011],
  B: [0b0111111, 0b0100010, 0b0100010, 0b0111110, 0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b0111111],
  C: [0b0011110, 0b0100010, 0b0110000, 0b0100000, 0b0100000, 0b0100000, 0b0110000, 0b0100010, 0b0011110],
  D: [0b0111110, 0b0110010, 0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b0110010, 0b0111110],
  E: [0b1111111, 0b0110000, 0b0100000, 0b0111110, 0b0100000, 0b0100000, 0b0100000, 0b0110000, 0b1111111],
  F: [0b1111111, 0b0110000, 0b0100000, 0b0111110, 0b0100000, 0b0100000, 0b0100000, 0b0110000, 0b1110000],
  G: [0b0011110, 0b0100011, 0b0110000, 0b0100000, 0b0101111, 0b0100010, 0b0100010, 0b0100011, 0b0011110],
  H: [0b0110110, 0b0100010, 0b0100010, 0b0100010, 0b0111110, 0b0100010, 0b0100010, 0b0100010, 0b0110110],
  I: [0b1111111, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b1111111],
  J: [0b0001111, 0b0000100, 0b0000100, 0b0000100, 0b0000100, 0b0000100, 0b0100100, 0b0100100, 0b0011000],
  K: [0b0110110, 0b0100010, 0b0100100, 0b0101000, 0b0110000, 0b0101000, 0b0100100, 0b0100010, 0b0110110],
  L: [0b0111100, 0b0100000, 0b0100000, 0b0100000, 0b0100000, 0b0100000, 0b0100000, 0b0110000, 0b1111111],
  M: [0b1000001, 0b1101011, 0b1101011, 0b1010101, 0b1010101, 0b1001001, 0b1001001, 0b1001001, 0b1100011],
  N: [0b1100011, 0b1100011, 0b1101011, 0b1011011, 0b1001111, 0b1001011, 0b1001011, 0b1001011, 0b1100111],
  O: [0b0011100, 0b0110110, 0b1100011, 0b1000001, 0b1000001, 0b1000001, 0b1100011, 0b0110110, 0b0011100],
  P: [0b0111110, 0b0100010, 0b0100010, 0b0111110, 0b0100000, 0b0100000, 0b0100000, 0b0100000, 0b0111100],
  Q: [0b0011100, 0b0110110, 0b1100011, 0b1000001, 0b1000001, 0b1001011, 0b1100110, 0b0110110, 0b0011111],
  R: [0b0111110, 0b0100010, 0b0100010, 0b0111110, 0b0101000, 0b0100100, 0b0100100, 0b0100010, 0b0110110],
  S: [0b0011111, 0b0110000, 0b0100000, 0b0011100, 0b0001100, 0b0001100, 0b0000011, 0b0110011, 0b1111100],
  T: [0b1111111, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0011100],
  U: [0b0110110, 0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b1100011, 0b1100011, 0b0011100],
  V: [0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b0100010, 0b0101010, 0b0010100, 0b0010100, 0b0001100],
  W: [0b1000001, 0b1000001, 0b1000001, 0b1010101, 0b1010101, 0b1010101, 0b1010101, 0b1100011, 0b1100011],
  X: [0b0110110, 0b0100010, 0b0010100, 0b0001000, 0b0001000, 0b0010100, 0b0100010, 0b0100010, 0b0110110],
  Y: [0b0100010, 0b0100010, 0b0010100, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0011100],
  Z: [0b1111111, 0b0000011, 0b0000110, 0b0001100, 0b0011000, 0b0110000, 0b1100000, 0b1100000, 0b1111111],

  0: [0b0011100, 0b0110110, 0b1100011, 0b1011001, 0b1001101, 0b1001101, 0b1011001, 0b1100011, 0b0011100],
  1: [0b0011000, 0b0011000, 0b0111000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b0001000, 0b1111111],
  2: [0b0011110, 0b0110110, 0b0100011, 0b0000011, 0b0000110, 0b0001100, 0b0011000, 0b0110000, 0b1111111],
  3: [0b0111110, 0b1100010, 0b0000010, 0b0000110, 0b0011100, 0b0000110, 0b0000010, 0b1100010, 0b0111110],
  4: [0b0001100, 0b0011100, 0b0011100, 0b0101100, 0b1001100, 0b1111111, 0b0001100, 0b0001100, 0b0011110],
  5: [0b1111111, 0b1100000, 0b1100000, 0b0111110, 0b0000010, 0b0000010, 0b0000010, 0b1100010, 0b0111110],
  6: [0b0011110, 0b0110000, 0b1100000, 0b1100000, 0b1111110, 0b1100010, 0b1100010, 0b1100010, 0b0111110],
  7: [0b1111111, 0b0000011, 0b0000110, 0b0001100, 0b0011000, 0b0010000, 0b0010000, 0b0010000, 0b0111100],
  8: [0b0011100, 0b0110110, 0b0100010, 0b0100010, 0b0011100, 0b0100010, 0b0100010, 0b0110110, 0b0011100],
  9: [0b0111110, 0b0100010, 0b0100010, 0b0100010, 0b0111111, 0b0000010, 0b0000010, 0b0000011, 0b0111110],

  ' ': [0, 0, 0, 0, 0, 0, 0, 0, 0],
  '.': [0, 0, 0, 0, 0, 0, 0, 0, 0b0011000],
  ',': [0, 0, 0, 0, 0, 0, 0, 0b0011000, 0b0100000],
  ':': [0, 0, 0, 0b0011000, 0, 0, 0b0011000, 0, 0],
  ';': [0, 0, 0, 0b0011000, 0, 0, 0b0011000, 0b0100000, 0],
  '·': [0, 0, 0, 0b0011000, 0b0011000, 0, 0, 0, 0], // middle dot
  '•': [0, 0, 0, 0b0111110, 0b0111110, 0b0111110, 0, 0, 0], // bullet
  '-': [0, 0, 0, 0, 0b0111110, 0, 0, 0, 0],
  '–': [0, 0, 0, 0, 0b0111110, 0, 0, 0, 0], // en dash
  '—': [0, 0, 0, 0, 0b1111111, 0, 0, 0, 0], // em dash
  _: [0, 0, 0, 0, 0, 0, 0, 0, 0b1111111],
  '=': [0, 0, 0, 0b0111110, 0, 0b0111110, 0, 0, 0],
  '+': [0, 0, 0b0001000, 0b0001000, 0b0111110, 0b0001000, 0b0001000, 0, 0],
  '/': [0b0000011, 0b0000110, 0b0001100, 0b0001100, 0b0011000, 0b0110000, 0b0110000, 0b1100000, 0b1100000],
  '\\': [0b1100000, 0b1100000, 0b0110000, 0b0110000, 0b0011000, 0b0001100, 0b0001100, 0b0000011, 0b0000011],
  '|': [0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000],
  '!': [0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0, 0b0011000, 0b0011000],
  '?': [0b0011100, 0b0110110, 0b0100011, 0b0000011, 0b0000110, 0b0001100, 0, 0b0001100, 0b0011000],
  '(': [0, 0b0001100, 0b0011000, 0b0011000, 0b0110000, 0b0011000, 0b0011000, 0b0011000, 0b0001100],
  ')': [0, 0b0011000, 0b0011000, 0b0011000, 0b0001100, 0b0011000, 0b0011000, 0b0011000, 0b0011000],
  '[': [0b0011110, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011110],
  ']': [0b0111100, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0111100],
  '<': [0, 0b0000110, 0b0001100, 0b0011000, 0b0110000, 0b1100000, 0b0011000, 0b0001100, 0b0000110],
  '>': [0, 0b0110000, 0b0011000, 0b0001100, 0b0000110, 0b0000011, 0b0000110, 0b0011000, 0b0110000],
  "'": [0b0011000, 0b0011000, 0b0001000, 0, 0, 0, 0, 0, 0],
  '"': [0b0101100, 0b0101100, 0b0010100, 0, 0, 0, 0, 0, 0],
  '*': [0, 0b1010101, 0b0111110, 0b0011100, 0b0111110, 0b1010101, 0, 0, 0],
  '&': [0b0011100, 0b0110010, 0b0110100, 0b0001000, 0b0010100, 0b0100010, 0b0110010, 0b0110010, 0b0011111],
  '#': [0, 0b0101010, 0b0101010, 0b1111111, 0b0101010, 0b1111111, 0b0101010, 0b0101010, 0],
  '@': [0b0011100, 0b0110110, 0b1100011, 0b1011101, 0b1011101, 0b1011101, 0b1100000, 0b0110110, 0b0011110],
  $: [0b0001000, 0b0011110, 0b0110010, 0b0111000, 0b0011000, 0b0001100, 0b0000110, 0b0110011, 0b0111110],
  '%': [0b1100011, 0b1100110, 0b0000110, 0b0001100, 0b0011000, 0b0110000, 0b0110011, 0b1100110, 0b1100011],
  x: [0, 0, 0b1000101, 0b0101010, 0b0010100, 0b0001000, 0b0010100, 0b0101010, 0b1000101],
  '×': [0, 0, 0b1000101, 0b0101010, 0b0010100, 0b0001000, 0b0010100, 0b0101010, 0b1000101], // multiplication sign
  '÷': [0, 0b0011000, 0, 0, 0b1111111, 0, 0, 0b0011000, 0], // division sign
  '→': [0, 0, 0, 0b0011100, 0b1111111, 0b0011100, 0, 0, 0], // right arrow
  '←': [0, 0, 0, 0b0111100, 0b1111111, 0b0111100, 0, 0, 0], // left arrow
  '↑': [0b0011000, 0b0011000, 0b0111110, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b1111111], // up arrow
  '↓': [0b1111111, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0011000, 0b0111110, 0b0011000, 0b0011000], // down arrow
  '▶': [0, 0b0011000, 0b0011100, 0b0011110, 0b0011111, 0b0011110, 0b0011100, 0b0011000, 0], // right triangle
  '■': [0, 0, 0b0111110, 0b0111110, 0b0111110, 0b0111110, 0b0111110, 0, 0], // filled square
};

const SANS = { name: 'sans', cols: 5, rows: 7, glyphs: SANS_GLYPHS };
const SERIF = { name: 'serif', cols: 7, rows: 9, glyphs: SERIF_GLYPHS };

/** Every set, by name. Serif is the default the app renders with. */
export const FONTS = { serif: SERIF, sans: SANS };
export const DEFAULT_FONT = 'serif';

let current = SERIF;

/** Switches the set used when a caller does not name one. Returns the set. */
export function setFont(name) {
  current = FONTS[name] ?? SERIF;
  return current;
}

/**
 * A set by name, or the current one when `font` is omitted. Accepts either
 * `"serif"` or a set object so callers can pass either without converting.
 */
export function getFont(font) {
  if (!font) return current;
  return typeof font === 'string' ? (FONTS[font] ?? current) : font;
}

/** The name of a set, for cache keys and the test page. */
export function fontName(font) {
  return getFont(font).name;
}

/** Grid size of one glyph in the given set, in font pixels. */
export function glyphSize(font) {
  const set = getFont(font);
  return { cols: set.cols, rows: set.rows };
}

const QUESTION = SERIF_GLYPHS['?'];

/**
 * Rows of a glyph, uppercased, with `?` for anything the set does not carry.
 *
 * The literal character is tried first, then its uppercase form. That order is
 * what makes the one deliberate lowercase key work: `x` is a multiplication
 * sign here, and uppercasing first would quietly turn every "x" into "X".
 */
export function glyphFor(char, font) {
  const glyphs = getFont(font).glyphs;
  const key = String(char);
  return glyphs[key] ?? glyphs[key.toUpperCase()] ?? QUESTION;
}

/** True when the set has a real glyph for `char` (so callers can warn). */
export function hasGlyph(char, font) {
  const glyphs = getFont(font).glyphs;
  const key = String(char);
  return Object.hasOwn(glyphs, key) || Object.hasOwn(glyphs, key.toUpperCase());
}

/** Every glyph in the set, in declaration order. */
export function glyphKeys(font) {
  return Object.keys(getFont(font).glyphs);
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
export function glyphBitmap(char, scale = 1, font) {
  const set = getFont(font);
  // Keyed on the raw character, not its uppercase form: "x" and "X" are
  // different glyphs here and must not share a cache entry. The set name is in
  // the key too, because the two sets have different widths.
  const key = `${set.name}@${String(char)}@${scale}`;
  const cached = bitmapCache.get(key);
  if (cached) return cached;
  let bitmap = glyphFor(char, set).map((bits) =>
    Array.from({ length: set.cols }, (_, col) => ((bits >> (set.cols - 1 - col)) & 1) === 1),
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
  font,
) {
  const set = getFont(font);
  const glyphCols = set.cols * scale;
  const glyphRows = set.rows * scale;
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
export function textCols(text, scale = 1, letterGap = LETTER_GAP, wordGap = WORD_GAP, font) {
  return measureFlipText(text, scale, letterGap, wordGap, font).cols;
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
  font,
) {
  const out = [];
  for (const line of String(text).split('\n')) {
    let current = '';
    for (const word of line.split(' ')) {
      if (textCols(word, scale, letterGap, wordGap, font) > maxCols) return null;
      const next = current ? `${current} ${word}` : word;
      if (textCols(next, scale, letterGap, wordGap, font) <= maxCols) {
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
export function pickScale(text, maxCols, scales = [4, 2, 1], font) {
  for (const scale of scales) {
    const wrapped = wrapText(text, maxCols, scale, LETTER_GAP, WORD_GAP, font);
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
  { letterGap = LETTER_GAP, wordGap = WORD_GAP, center = false, font } = {},
) {
  const set = getFont(font);
  const glyphCols = set.cols * scale;
  const glyphRows = set.rows * scale;
  const { lines, widths, cols, rows } = measureFlipText(text, scale, letterGap, wordGap, set);
  const cells = [];
  lines.forEach((line, lineIndex) => {
    let cursor = center ? Math.floor((cols - widths[lineIndex]) / 2) : 0;
    const y0 = lineIndex * (glyphRows + scale);
    for (const ch of line) {
      if (ch === ' ') {
        cursor += wordGap * scale;
        continue;
      }
      const bitmap = glyphBitmap(ch, scale, set);
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