/**
 * The review screen: the transcript, the table of flags, and the Render button.
 *
 * This is the one screen where the dot board is not the interface. A transcript is
 * two hundred words of small type and a flag row is seven columns of figures -
 * dot-drawing either would be unreadable - so both are real HTML sitting over the
 * canvas, in the monospace face, and only the title, the count and the buttons are
 * drawn as signs. That split is the rule `AGENTS.md` sets: dot-matrix for titles,
 * buttons, status and progress; HTML for anything dense.
 *
 * The user is the authority here. Everything on this screen edits a local copy of
 * the flags; nothing is sent until Render, and `censor` is sent exactly as the
 * checkboxes left it, so a word that is not on the list can still be censored and
 * one that is can be let through.
 */
import * as api from './api.js';
import { TONE_GO, TONE_PLAIN, TONE_STOP } from './flipdisc.js';
import { NOTICE_ROWS, state } from './ui.js';

/** One press of a nudge button moves a window edge by this many seconds. */
const NUDGE_S = 0.01;

/**
 * Audio either side of a word when previewing it, in seconds.
 *
 * The server has its own `PREVIEW_PAD_S` and pads again when it renders a
 * previewed region; this is only how much the browser asks for.
 */
const PREVIEW_PAD_S = 1.5;

/** Mirrors `censorflow.models.SOURCE_ASR`: a word added by clicking is ASR's. */
const SOURCE_ASR = 'asr';

/** How each source is named in the table. */
const BADGES = { asr: 'ASR', lyrics: 'LYRICS', both: 'BOTH' };

/** The fields the server reads from a flag, in the order it validates them. */
const SENT = ['word_index', 'text', 'start', 'end', 'source', 'confidence', 'approx', 'censor'];

/** Seconds as `m:ss.mmm`, which is what a nudge button reads best at. */
function stamp(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${(safe - minutes * 60).toFixed(3).padStart(6, '0')}`;
}

/**
 * Wire the review screens into `ui`.
 *
 * `ui.board` only exists once `createUi` has run, so the buttons cannot be made at
 * module level the way app.js makes its own: they are created once here and placed
 * by the painter, which is the rule the board imposes.
 */
export function registerReview(ui, { say, startUpload, status }) {
  const board = ui.board;

  /** The flags as the user has left them. Rebuilt from the server on every open. */
  let flags = [];
  /** The server's payload: the transcript the flags point into. */
  let data = null;
  /** The HTML box, once built. */
  let panel = null;
  /** One shared element for previews, so two clicks cannot play over each other. */
  let previewer = null;

  const renderButton = board.button({
    label: 'RENDER',
    scale: 2,
    tone: TONE_GO,
    onClick: () => submit(),
  });
  const overButton = board.button({
    label: 'START OVER',
    scale: 1,
    onClick: () => startUpload(),
  });

  /** A small amber-on-black button, for the dense rows rather than the board. */
  function mini(label, onClick, className = '') {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = className ? `mini ${className}` : 'mini';
    node.textContent = label;
    node.addEventListener('click', onClick);
    return node;
  }

  function cell(node) {
    const td = document.createElement('td');
    if (node) td.append(node);
    return td;
  }

  function cellText(text, className) {
    const td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  /** The header: what was heard, how much of it, and what the flags say. */
  function buildHead() {
    const head = document.createElement('div');
    head.className = 'review-head';
    const track = data.track || {};
    const title = document.createElement('strong');
    title.textContent = track.title || track.filename || 'this song';
    const facts = document.createElement('span');
    facts.className = 'muted';
    facts.textContent = [
      `${stamp(data.duration)} long`,
      `${data.words.length} words heard`,
      data.lyrics_found ? `${data.lyric_lines} lyric lines cross-checked` : 'no lyrics found',
    ].join('  ·  ');
    const spacer = document.createElement('div');
    spacer.className = 'review-spacer';
    head.append(title, facts, spacer);
    return head;
  }

  /**
   * The transcript. Every word is clickable, which is how a miss is added.
   *
   * A word the server flagged is marked; clicking it switches censoring off.
   * A word it did not flag gets a new flag, timed from the word itself.
   */
  function buildTranscript() {
    const wrap = document.createElement('div');
    wrap.className = 'transcript';
    const byIndex = new Map();
    for (const flag of flags) if (flag.word_index >= 0) byIndex.set(flag.word_index, flag);
    data.words.forEach((word, index) => {
      const flag = byIndex.get(index);
      const span = document.createElement('button');
      span.type = 'button';
      span.className = 'w';
      span.textContent = word.text;
      span.title = `${stamp(word.start)}  confidence ${(word.confidence ?? 0).toFixed(2)}`;
      if (flag) {
        span.classList.add('flag');
        if (!flag.censor) span.classList.add('off');
        if (flag.approx) span.classList.add('approx');
      }
      span.addEventListener('click', () => toggleWord(index, flag));
      wrap.append(span, document.createTextNode(' '));
    });
    return wrap;
  }

  /** Toggle a word: an existing flag switches, an unflagged word gains one. */
  function toggleWord(index, flag) {
    if (flag) {
      flag.censor = !flag.censor;
    } else {
      const word = data.words[index];
      flags.push({
        word_index: index,
        text: word.text,
        start: word.start,
        end: word.end,
        source: SOURCE_ASR,
        confidence: word.confidence ?? 0,
        approx: false,
        // The server recomputes whether this is profane and reports it back; until
        // then the badge has to admit it does not know.
        profane: null,
        censor: true,
      });
    }
    refresh();
  }

  /** A checkbox, so the switch is the same gesture in the table as in the text. */
  function censorBox(flag) {
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = flag.censor;
    box.setAttribute('aria-label', `censor ${flag.text}`);
    box.addEventListener('change', () => {
      flag.censor = box.checked;
      refresh();
    });
    return box;
  }

  /** The word's text, editable: ASR mishears, and a mishearing is not a censor. */
  function wordField(flag) {
    const field = document.createElement('input');
    field.type = 'text';
    field.className = 'word';
    field.value = flag.text;
    field.setAttribute('aria-label', 'flagged word');
    // `change`, not `input`: the server judges profanity from the committed text,
    // and rebuilding the table on every keystroke would eat the caret.
    field.addEventListener('change', () => {
      const text = field.value.trim();
      if (!text) {
        field.value = flag.text;
        say('a flag needs a word', TONE_STOP);
        return;
      }
      flag.text = text;
      flag.profane = null;
      refresh();
    });
    return field;
  }

  /** A start or end time, with the two nudge buttons AGENTS.md asks for. */
  function timeCell(flag, edge) {
    const td = document.createElement('td');
    const readout = document.createElement('span');
    readout.className = 't';
    const show = () => {
      readout.textContent = stamp(flag[edge]);
    };
    const nudge = (direction) => () => {
      flag[edge] = Math.max(0, Number((flag[edge] + direction * NUDGE_S).toFixed(6)));
      // Nudging an edge must never invert the window: `end` stops at `start`.
      if (flag.end <= flag.start) flag.end = flag.start + NUDGE_S;
      show();
      say(`${flag[edge === 'start' ? 'start' : 'end']} moved to ${stamp(flag[edge])}`);
      ui.refresh();
    };
    show();
    td.append(
      readout,
      mini('−', nudge(-1)),
      mini('+', nudge(1)),
    );
    td.dataset.edge = edge;
    return td;
  }

  /** The source badge, plus a marker when the timing was estimated. */
  function sourceCell(flag) {
    const td = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `badge ${flag.source}`;
    badge.textContent = BADGES[flag.source] || flag.source.toUpperCase();
    td.append(badge);
    if (flag.approx) {
      const verify = document.createElement('span');
      verify.className = 'verify';
      verify.textContent = 'VERIFY';
      td.append(verify);
    }
    return td;
  }

  /**
   * What the server thinks of the word.
   *
   * `null` means "not asked yet": editing a word's text cannot be judged in the
   * browser without shipping the whole word list over and reimplementing the
   * detection, so the badge says `?` until the next round trip reports back.
   */
  function verdictCell(flag) {
    const known = typeof flag.profane === 'boolean';
    return cellText(known ? (flag.profane ? 'ON THE LIST' : 'NOT ON THE LIST') : '?', 'verdict');
  }

  /** Play this flag's neighbourhood, with and without the censor applied. */
  function previewCell(flag) {
    const td = document.createElement('td');
    td.append(
      mini('hear it', () => preview('original', flag), 'plain'),
      mini('hear it muted', () => preview('censored', flag), 'plain'),
    );
    return td;
  }

  function buildTable() {
    const table = document.createElement('table');
    table.className = 'grid flags';
    const head = document.createElement('tr');
    for (const label of ['', 'word', 'start', 'end', 'source', 'verdict', 'hear']) {
      const th = document.createElement('th');
      th.textContent = label;
      head.append(th);
    }
    table.append(head);
    flags.forEach((flag) => {
      const row = document.createElement('tr');
      row.append(
        cell(censorBox(flag)),
        cell(wordField(flag)),
        timeCell(flag, 'start'),
        timeCell(flag, 'end'),
        sourceCell(flag),
        verdictCell(flag),
        previewCell(flag),
      );
      table.append(row);
    });
    return table;
  }

  /**
   * Rebuild the HTML, then redraw the board.
   *
   * Scroll position is kept because the table is often taller than the window and
   * a rebuild that jumped to the top would lose the row being worked on.
   */
  function refresh() {
    if (!panel) return;
    const top = panel.scrollTop;
    panel.replaceChildren(buildHead(), buildTranscript(), buildTable());
    panel.scrollTop = top;
    ui.refresh();
  }

  /** Ask the server for `PREVIEW_PAD_S` of audio either side of one flag. */
  function preview(kind, flag) {
    if (!state.job) return;
    if (!previewer) {
      previewer = new Audio();
      previewer.preload = 'auto';
    }
    previewer.pause();
    previewer.src = api.clipUrl(
      state.job.id,
      kind,
      Math.max(0, flag.start - PREVIEW_PAD_S),
      flag.end + PREVIEW_PAD_S,
    );
    const spoken = kind === 'original' ? 'the original' : 'the censored version';
    previewer.play().then(
      () => say(`playing ${spoken}`),
      () => say('the browser would not play that clip', TONE_STOP),
    );
  }

  /** Send the flags as the user left them, then show the render. */
  async function submit() {
    if (!state.job) return;
    say(`rendering ${flags.filter((flag) => flag.censor).length} windows`);
    ui.show('rendering');
    let payload;
    try {
      payload = await api.postReview(state.job.id, {
        flags: flags.map((flag) => Object.fromEntries(SENT.map((key) => [key, flag[key]]))),
      });
    } catch (error) {
      say(error.message, TONE_STOP);
      ui.show('review');
      return;
    }
    state.render = payload.render;
    const censored = payload.render.words_censored;
    say(censored === 1 ? 'one word censored' : `${censored} words censored`);
    ui.show('result');
  }

  /** Forget a finished review, so a new song cannot inherit the old song's flags. */
  function reset() {
    flags = [];
    data = null;
    panel = null;
    if (previewer) previewer.pause();
  }

  /** Open the review screen on a job that has finished analysing. */
  async function open(id) {
    say('loading the review');
    ui.show('awaiting');
    let payload;
    try {
      payload = await api.getReview(id);
    } catch (error) {
      say(error.message, TONE_STOP);
      ui.show('welcome');
      return;
    }
    data = payload;
    // Work on a copy: the payload is what the server said, and the table is what
    // the user has done to it.
    flags = payload.flags.map((flag) => ({ ...flag }));
    flags.sort((a, b) => a.start - b.start);
    panel = document.createElement('div');
    panel.className = 'review';
    ui.show('review');
    refresh();
    // The status line is a question, not a report: the user now has to decide.
    say(
      flags.length === 0
        ? 'nothing was flagged - render to write the clean copy anyway'
        : `check the ${flags.length} flagged words, then render`,
    );
  }

  ui.register('rendering', {
    paint(h) {
      h.sign('RENDERING', { row: h.top(60) });
      h.notice('the clean copy is being written. this takes a moment', TONE_PLAIN);
    },
  });

  ui.register('review', {
    enter() {
      // Created here, not in the painter: a panel built on every redraw would throw
      // away the scroll position and every checkbox's focus on every hover.
      if (!panel) {
        panel = document.createElement('div');
        panel.className = 'review';
        panel.setAttribute('role', 'region');
        panel.setAttribute('aria-label', 'transcript and flags');
      }
      document.getElementById('overlay').append(panel);
    },
    leave() {
      panel?.remove();
    },
    paint(h) {
      const on = flags.filter((flag) => flag.censor).length;
      let row = h.sign('REVIEW', { row: 1, centre: false, scale: 3 });
      row = h.sign(`${on} OF ${flags.length} FLAGS ON`, { row: row + 2, centre: false });
      // The panel is sized to the gap between the last sign and the buttons, so the
      // dense HTML can never sit on top of the board's own hit-tested buttons.
      const buttonRow = h.rows() - NOTICE_ROWS - renderButton.height - 3;
      if (panel) {
        panel.style.top = `${(row + 4) * h.pitch()}px`;
        panel.style.bottom = `${(h.rows() - buttonRow) * h.pitch()}px`;
      }
      h.buttonRow([renderButton, overButton], buttonRow, {
        col: h.centre([renderButton, overButton]),
      });
      h.notice(status().text, status().tone);
    },
  });

  return { open, reset };
}