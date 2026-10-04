/**
 * Buttons and progress bars on the flip-disc board.
 *
 * A button is a plate plus a label, hit-tested in grid cells. Drawing goes
 * through the surface from board-paint.js so a hover repaints the whole board
 * once, which is what keeps the plate and the letters in agreement.
 */
import { getFont, textCols } from './font5x7.js';
import { DIM, INV, ON, TONE_PLAIN } from './flipdisc.js';

export function attachControls(env, surface) {
  const { plate, stampText, set, toneColour } = surface;
  /**
   * A plate with a label on it, hit-tested in grid coordinates.
   *
   * The border colour is the point of `tone`: a control says what it will do
   * before it is touched - green goes, red stops, plain for neither. Hover and
   * press light the panel in that same tone and knock the label out of it, which
   * is the instant inversion from before, just with a drawn border instead of a
   * beaded one. A disabled button keeps its plate and dims its label: an empty
   * outline reads as a rendering bug rather than as "not available yet".
   */
  function button({ col, row, label, scale = 1, font, tone = TONE_PLAIN, onClick }) {
    const handle = {
      col,
      row,
      label,
      scale,
      tone,
      onClick,
      enabled: true,
      hovered: false,
      pressed: false,
      // Only the buttons the current screen placed are drawn. Every button ever
      // created lives in one list, and drawing all of them leaves the previous
      // screen's buttons sitting on the display.
      shown: false,
      width: 0,
      height: 0,
    };

    handle.place = (nextCol, nextRow) => {
      handle.col = nextCol;
      handle.row = nextRow;
      handle.shown = true;
      layout();
      return handle;
    };

    /** Take this button off the display without destroying it. */
    handle.hide = () => {
      handle.shown = false;
      handle.hovered = false;
      handle.pressed = false;
      return handle;
    };

    handle.setLabel = (next) => {
      handle.label = next;
      layout();
      return handle;
    };

    handle.setTone = (next) => {
      if (handle.tone === next) return handle;
      handle.tone = next;
      handle.repaint();
      return handle;
    };

    handle.setEnabled = (value) => {
      if (handle.enabled === value) return handle;
      handle.enabled = value;
      handle.repaint();
      return handle;
    };

    function layout() {
      handle.width = textCols(handle.label, handle.scale, undefined, undefined, font) + 4;
      handle.height = getFont(font).rows * handle.scale + 4;
    }

    /**
     * Draw this button's plate and label. Called from `redraw` rather than on its
     * own, because a plate is remembered on the board rather than baked into the
     * cell buffer: one pass over the whole grid is what keeps the remembered
     * plates and the pixels in agreement. Hovering therefore repaints the board.
     */
    function draw() {
      const active = handle.hovered || handle.pressed;
      const lit = active && handle.enabled;
      const ink = !handle.enabled ? DIM : lit ? INV : ON;
      // Resting: the dots are the tone's own colour, so the lettering and the
      // hairline are one colour and the button reads as a single sign. Lit: the
      // plate fills with the tone colour and the label is knocked out of it, which
      // is what keeps the word legible through the inversion.
      plate({
        col: handle.col,
        row: handle.row,
        cols: handle.width,
        rows: handle.height,
        fill: lit ? toneColour(handle.tone) : env.colours.plateBg,
        tone: lit ? TONE_PLAIN : handle.tone,
        ink: !lit && handle.enabled && handle.tone !== TONE_PLAIN ? toneColour(handle.tone) : null,
      });
      stampText(handle.label, handle.col + 2, handle.row + 2, {
        scale: handle.scale,
        state: ink,
        font,
      });
    }

    handle.draw = draw;
    /** Repaint the board. See `draw`. */
    handle.repaint = () => env.redraw();
    handle.contains = (col, row) =>
      col >= handle.col &&
      col < handle.col + handle.width &&
      row >= handle.row &&
      row < handle.row + handle.height;

    layout();
    env.buttons.push(handle);
    return handle;
  }

  function buttonAt(col, row) {
    // `shown` is the same gate `redraw` uses. Without it, a hidden button from
    // the previous screen (ANOTHER SONG on awaiting, CHOOSE ANOTHER on mode)
    // still owns its last grid rect and steals the click - which is how RENDER
    // on the review screen sent the user back to welcome.
    for (const handle of env.buttons) {
      if (!handle.shown || handle.enabled === false) continue;
      if (handle.contains(col, row)) return handle;
    }
    return null;
  }

  /**
   * A caption on a sign, with a bar underneath showing `pct`.
   *
   * The bar sits inside the frame, so the unfilled part still reads as part of
   * the sign instead of dissolving into the board - which is what happened when
   * the track was bare cells lying on a lit field.
   */
  function progress({ col, row, width, cols, label, scale = 1, font, tone = TONE_PLAIN, pct = 0 }) {
    const captionRows = label === undefined ? 0 : getFont(font).rows * scale;
    const barRow = row + (captionRows ? captionRows + 3 : 2);
    // Callers say `width` or `cols` for the same span. A missing one used to
    // become NaN, and the bar drew nothing.
    const total = Math.max(3, width ?? cols ?? 3);
    // One row of air under the bar, so it reads as a bar inside the frame rather
    // than as a thick bottom border.
    plate({ col, row, cols: total, rows: barRow + 3 - row, tone, ink: tone === TONE_PLAIN ? null : tone });
    if (captionRows) stampText(label, col + 2, row + 2, { scale, font });
    const barCols = total - 4;
    const filled = Math.round(Math.max(0, Math.min(1, pct)) * barCols);
    for (let i = 0; i < filled; i += 1) set(col + 2 + i, barRow, ON);
    return { col, row, cols: total, rows: barRow + 3 - row };
  }

  return { button, buttonAt, progress };
}
