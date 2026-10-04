/**
 * Painting the flip-disc grid: discs, plates, and stamped text.
 *
 * The board in flipdisc.js owns the cell buffer. This module draws into it.
 * `env` is a live view of that buffer, because a resize replaces the arrays.
 */
import { drawDisc, drawHighlight } from './board-field.js';
import { layoutFlipCells } from './font5x7.js';
import { BLUE, DIM, INV, OFF, ON, ORANGE, TONE_GO, TONE_INFO, TONE_PLAIN, TONE_STOP } from './flipdisc.js';

/** Inverted flaps overdraw the lit disc so a knocked-out letter stays a hole. */
const INV_OVERDRAW = 1.16;
/** Plate border thickness in CSS pixels: a hairline, not a row of dots. */
const PLATE_LINE = 1;

/**
 * Draw into the board's buffer. `env` exposes the live grid; the functions close
 * over each other, which is how a plate repaint reaches the same discs.
 */
export function attachPaint(env) {
  function paint(col, row) {
    if (!env.inside(col, row)) return;
    const state = env.cells[env.index(col, row)];
    const x = col * env.pitch;
    const y = row * env.pitch;
    const cx = x + env.pitch / 2;
    const cy = y + env.pitch / 2;
    // A cell inside a plate is the plate's own colour, not the board's, and its
    // outermost ring carries the hairline. Outside a plate the cell is the board.
    const panel = panelAt(col, row);
    env.ctx.fillStyle = panel ? panel.fill : env.colours.bg;
    env.ctx.fillRect(x, y, env.pitch, env.pitch);
    if (panel) drawPanelEdges(panel, col, row, x, y);
    // Nothing on this board is ever a filled square: the dots are the design, so
    // a lit cell is a round flap and the gaps between flaps stay background.
    if (state === OFF) return;
    if (state === DIM) {
      drawDisc(env.ctx, cx, cy, env.radius, env.colours.dim);
      return;
    }
    if (state === ORANGE) {
      drawDisc(env.ctx, cx, cy, env.radius, env.colours.ball);
      return;
    }
    if (state === BLUE) {
      drawDisc(env.ctx, cx, cy, env.radius, env.colours.info);
      return;
    }
    if (state === INV) {
      // Inverted: a flap flipped to its dark side. Drawn in the plate's own
      // resting colour and a hair wider than a lit disc, so it fully covers the
      // flap underneath: a knocked-out letter is a gap in the dots, not a dot on
      // top of dots. The knock-out follows the letterforms, which is what keeps
      // the word readable while the plate behind it is lit.
      drawDisc(env.ctx, cx, cy, env.radius * INV_OVERDRAW, env.colours.plateBg);
      return;
    }
    // A plate may claim the ink for its own lettering, so a sign whose border is
    // green or red has dots of that same colour rather than amber dots inside a
    // green frame. The specular highlight belongs to the amber flaps only: on a
    // tinted disc it would read as a stray light dot.
    const ink = panel && panel.ink ? panel.ink : env.colours.on;
    // Off-dot lettering on a lit plate has to overdraw the fill, or the yellow
    // shows around each disc and the word reads as yellow-on-yellow.
    if (ink === env.colours.off) {
      drawDisc(env.ctx, cx, cy, env.radius * INV_OVERDRAW, ink);
      return;
    }
    drawDisc(env.ctx, cx, cy, env.radius, ink);
    if (ink === env.colours.on) drawHighlight(env.ctx, cx, cy, env.radius, env.colours.hi);
  }

  function repaintAll() {
    for (let row = 0; row < env.rows; row += 1) {
      for (let col = 0; col < env.cols; col += 1) paint(col, row);
    }
  }

  /** Mutate a cell without drawing. */
  function put(col, row, state) {
    if (!env.inside(col, row)) return;
    env.cells[env.index(col, row)] = state;
  }

  /** Mutate and draw one cell. */
  function set(col, row, state) {
    if (!env.inside(col, row)) return;
    env.cells[env.index(col, row)] = state;
    paint(col, row);
  }

  function fill(col, row, width, height, state) {
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) put(c, r, state);
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) paint(c, r);
    }
  }

  function stroke(col, row, width, height, state) {
    for (let c = col; c < col + width; c += 1) {
      put(c, row, state);
      put(c, row + height - 1, state);
    }
    for (let r = row; r < row + height; r += 1) {
      put(col, r, state);
      put(col + width - 1, r, state);
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) paint(c, r);
    }
  }

/**
   * A plate: an opaque panel the colour of the board with a hairline border.
   *
   * This is the only container the UI uses, and it is deliberately the same box
   * as the `.chip` specimens in the stylesheet - same background, same hairline,
   * same dot of air inside - so a sign drawn here and a specimen drawn in HTML
   * are the same object. `fill` is the panel colour, normally the board colour;
   * `tone` colours the border and is how a control says what it will do.
   *
   * The panel is remembered rather than baked into the cell buffer, so `redraw`
   * can rebuild it from scratch: clearing the buffer and re-running the painters
   * is enough, and `paint` re-draws the panel whenever it walks a cell inside
   * one. `repaintAll` therefore cannot erase a plate.
   *
   * `key` names the panel so a caller that redraws one plate many times a second -
   * the scrolling banner - replaces its record instead of appending a new one.
   * An unkeyed plate is matched by its grid rect, so a hover can redraw one
   * button without leaking a new panel each time.
   */
  function plate({
    col,
    row,
    cols: width,
    rows: height,
    fill,
    tone = TONE_PLAIN,
    key = null,
    ink = null,
  } = {}) {
    const record = {
      col,
      row,
      cols: width,
      rows: height,
      fill: fill ?? env.colours.plateBg,
      border:
        tone === TONE_GO
          ? env.colours.go
          : tone === TONE_STOP
            ? env.colours.stop
            : tone === TONE_INFO
              ? env.colours.info
              : env.colours.plateLine,
      // `ink` is the colour the plate's own lettering takes. Left null the plate
      // uses the standard amber; a toned plate passes its tone colour so the dots
      // match the hairline. The caller passes null again while it is lit, because
      // then the lettering is knocked out instead.
      ink: ink ?? null,
      key,
    };
    const existing =
      key !== null
        ? env.panels.findIndex((other) => other.key === key)
        : env.panels.findIndex(
            (other) =>
              other.key == null &&
              other.col === col &&
              other.row === row &&
              other.cols === width &&
              other.rows === height,
          );
    if (existing === -1) env.panels.push(record);
    else env.panels[existing] = record;
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) {
        put(c, r, OFF);
        if (env.inside(c, r)) env.guard[env.index(c, r)] = 1;
      }
    }
    for (let r = row; r < row + height; r += 1) {
      for (let c = col; c < col + width; c += 1) paint(c, r);
    }
    return { col, row, cols: width, rows: height, tone };
  }

  /** The plate covering a cell, if any. Panels are few, so this is a plain scan. */
  function panelAt(col, row) {
    for (const record of env.panels) {
      if (col < record.col || col >= record.col + record.cols) continue;
      if (row < record.row || row >= record.row + record.rows) continue;
      return record;
    }
    return null;
  }

  /**
   * The hairline, one cell edge at a time.
   *
   * Drawn per cell rather than as a single `strokeRect` so that the repaint of a
   * single cell - which is what hover, press and the marquee all do - keeps the
   * border intact. `PLATE_LINE` is a CSS pixel, so at a 2x display it lands as a
   * two-device-pixel line and stays crisp.
   */
  function drawPanelEdges(panel, col, row, x, y) {
    env.ctx.fillStyle = panel.border;
    if (col === panel.col) env.ctx.fillRect(x, y, PLATE_LINE, env.pitch);
    if (col === panel.col + panel.cols - 1) env.ctx.fillRect(x + env.pitch - PLATE_LINE, y, PLATE_LINE, env.pitch);
    if (row === panel.row) env.ctx.fillRect(x, y, env.pitch, PLATE_LINE);
    if (row === panel.row + panel.rows - 1) env.ctx.fillRect(x, y + env.pitch - PLATE_LINE, env.pitch, PLATE_LINE);
  }

  /** The fill colour a tone means, for a plate lit in that tone. */
  function toneColour(tone) {
    if (tone === TONE_GO) return env.colours.go;
    if (tone === TONE_STOP) return env.colours.stop;
    if (tone === TONE_INFO) return env.colours.info;
    return env.colours.on;
  }

  /**
   * Light `text` into the grid and return its footprint.
   * `col`/`row` is the top-left corner; `center` instead treats them as the
   * horizontal centre of the first line.
   *
   * Marks every cell it touches as protected, so a caller that animates the
   * field (see the animation in `font-test.html`) can ask which cells carry
   * meaning and leave them alone.
   */
  function stampText(text, col, row, { scale = 1, center = false, state = ON, font } = {}) {
    const { cells: lit, cols: width, rows: height } = layoutFlipCells(text, scale, { center, font });
    const x0 = center ? col - Math.floor(width / 2) : col;
    for (let r = row; r < row + height; r += 1) {
      for (let c = x0; c < x0 + width; c += 1) {
        if (env.inside(c, r)) env.guard[env.index(c, r)] = 1;
      }
    }
    for (const cell of lit) put(x0 + cell.x, row + cell.y, state);
    for (let r = row; r < row + height; r += 1) {
      for (let c = x0; c < x0 + width; c += 1) paint(c, r);
    }
    return { x: x0, y: row, cols: width, rows: height };
  }

  return { paint, repaintAll, put, set, fill, stroke, plate, stampText, toneColour };
}
