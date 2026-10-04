/**
 * The review transcript and the flag table: real HTML, not dots.
 *
 * The screen in review.js owns the flags and talks to the server. This module
 * only builds the elements. `host` is read at click time, so an edit sees the
 * flags as they are now.
 */
import { TONE_STOP } from './flipdisc.js';

/** One press of a nudge button moves a window edge by this many seconds. */
const NUDGE_S = 0.01;

/** Mirrors `censorflow.models.SOURCE_ASR`: a word added by clicking is ASR's. */
const SOURCE_ASR = 'asr';

/** How each source is named in the table. */
const BADGES = { asr: 'ASR', lyrics: 'LYRICS', both: 'BOTH' };

/** Seconds as `m:ss.mmm`, which is what a nudge button reads best at. */
function stamp(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${(safe - minutes * 60).toFixed(3).padStart(6, '0')}`;
}

export function createReviewDom(host) {
  const { say, ui } = host;
  /** Whether the transcript is expanded. Survives panel rebuilds; reset on each open. */
  let transcriptOpen = false;
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
    const track = host.data.track || {};
    const title = document.createElement('strong');
    title.textContent = track.title || track.filename || 'this song';
    const facts = document.createElement('span');
    facts.className = 'muted';
    facts.textContent = [
      `${stamp(host.data.duration)} long`,
      `${host.data.words.length} words heard`,
      host.data.lyrics_found ? `${host.data.lyric_lines} lyric lines cross-checked` : 'no lyrics found',
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
   * Collapsed by default so the table of flags gets the room.
   */
  function buildTranscript() {
    const box = document.createElement('details');
    box.className = 'transcript-box';
    box.open = transcriptOpen;
    const summary = document.createElement('summary');
    const label = () => (box.open ? 'hide transcript ▾' : 'show transcript ▸');
    summary.textContent = label();
    box.addEventListener('toggle', () => {
      transcriptOpen = box.open;
      summary.textContent = label();
    });
    const wrap = document.createElement('div');
    wrap.className = 'transcript';
    box.append(summary, wrap);
    const byIndex = new Map();
    for (const flag of host.flags) if (flag.word_index >= 0) byIndex.set(flag.word_index, flag);
    host.data.words.forEach((word, index) => {
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
    return box;
  }

  /** Toggle a word: an existing flag switches, an unflagged word gains one. */
  function toggleWord(index, flag) {
    if (flag) {
      flag.censor = !flag.censor;
    } else {
      const word = host.data.words[index];
      host.flags.push({
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
    host.refresh();
  }

  /** A checkbox, so the switch is the same gesture in the table as in the text. */
  function censorBox(flag) {
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = flag.censor;
    box.setAttribute('aria-label', `censor ${flag.text}`);
    box.addEventListener('change', () => {
      flag.censor = box.checked;
      host.refresh();
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
      host.refresh();
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
      mini('hear it', () => host.preview('original', flag), 'plain'),
      mini('hear it muted', () => host.preview('censored', flag), 'plain'),
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
    host.flags.forEach((flag) => {
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

  /** Collapse the transcript, so every review starts with the table getting the room. */
  function resetTranscript() {
    transcriptOpen = false;
  }

  return { buildHead, buildTranscript, buildTable, resetTranscript };
}
