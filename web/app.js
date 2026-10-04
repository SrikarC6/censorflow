/**
 * The screens: Welcome, Mode, Processing, Result.
 *
 * One `state` object holds everything the screens read, one `ui` paints them, and
 * `api` does the talking to the server. There is no animation anywhere: a state
 * change is a redraw, which is the whole point of the board.
 */
import * as api from './api.js';
import { TONE_GO, TONE_PLAIN, TONE_STOP } from './flipdisc.js';
import { createUi, state } from './ui.js';

const canvas = document.getElementById('board');
const overlay = document.getElementById('overlay');
const live = document.getElementById('live');
const fileInput = document.getElementById('file');

const ui = createUi({ canvas, overlay });
const { board } = ui;

/** The status line under everything. Redrawn on every say. */
let status = { text: '', tone: TONE_PLAIN };

/** Say something in the status line and to a screen reader, in one call. */
function say(text, tone = TONE_PLAIN) {
  status = { text, tone };
  live.textContent = text;
  ui.refresh();
}

// --- buttons -----------------------------------------------------------------
// Created once, placed by the painters. See the note at the top of ui.js.
const chooseFile = board.button({
  label: 'CHOOSE A SONG',
  scale: 2,
  tone: TONE_GO,
  onClick: () => fileInput.click(),
});
const cancelMode = board.button({
  label: 'CHOOSE ANOTHER',
  scale: 1,
  onClick: () => startUpload(),
});
const censorMode = board.button({
  label: 'CENSOR',
  scale: 2,
  tone: TONE_GO,
  onClick: () => startJob(),
});
const stemsMode = board.button({
  label: 'STEMS: SOON',
  scale: 2,
  onClick: () => say('Stem mixing is not built yet. See docs/STEMS_TODO.md.', TONE_STOP),
});
const againButton = board.button({
  label: 'ANOTHER SONG',
  scale: 1,
  onClick: () => startUpload(),
});
const playOriginal = board.button({
  label: 'ORIGINAL',
  scale: 1,
  onClick: () => playSource('original'),
});
const playClean = board.button({
  label: 'CLEAN',
  scale: 1,
  onClick: () => playSource('clean'),
});
const download = board.button({
  label: 'DOWNLOAD',
  scale: 2,
  tone: TONE_GO,
  onClick: () => saveOutput(),
});

// --- screens -----------------------------------------------------------------

/** How tall each screen's block is, in dots, so `top` can centre it. */
const BLOCK = { welcome: 100, mode: 118, awaiting: 90, result: 150, failed: 90 };

ui.register('welcome', {
  paint(h) {
    let row = h.top(BLOCK.welcome);
    row = h.sign('CENSORFLOW', { row });
    row = h.sign('SILENCE THE VOCALS. KEEP THE MUSIC.', { row: row + 4 });
    h.buttonRow([chooseFile], row + 8, { col: Math.floor(h.cols() / 2) - 16 });
    // The format hint normally; a real reason, if the install is not ready.
    h.notice(status.text || 'MP3 M4A FLAC WAV OGG OPUS AIFF - OR DROP A FILE ANYWHERE', status.tone);
  },
});

ui.register('mode', {
  paint(h) {
    const track = state.upload || {};
    let row = h.top(BLOCK.mode);
    row = h.sign('CENSORFLOW', { row });
    row = h.sign(track.title || track.filename || 'A SONG', { row: row + 3 });
    const centre = Math.floor(h.cols() / 2);
    h.buttonRow([censorMode], row + 4, { col: centre - 14 });
    h.buttonRow([stemsMode], row + 4 + censorMode.height + 3, { col: centre - 16 });
    h.buttonRow([cancelMode], row + 4 + censorMode.height + 3 + stemsMode.height + 3, {
      col: centre - 9,
    });
    h.notice(status.text, status.tone);
  },
});

/** The pipeline, in the order it actually runs. */
const STAGES = ['fetching_lyrics', 'decoding', 'separating', 'transcribing', 'detecting'];

ui.register('processing', {
  paint(h) {
    const snapshot = state.snapshot || {};
    let row = h.sign('WORKING', { row: 2, centre: false });
    row += 3;
    const done = snapshot.state === 'done';
    STAGES.forEach((stage, index) => {
      const at = snapshot.state === stage;
      // `done` and any error light every stage, which is what the eye expects.
      const past = done || STAGES.indexOf(snapshot.state) > index;
      const label = at ? `> ${stageName(stage)}` : stageName(stage);
      row = h.sign(label, {
        row,
        scale: 2,
        tone: at ? TONE_GO : TONE_PLAIN,
        centre: false,
      });
      row += 2;
    });
    row += 3;
    h.meter(snapshot.message || 'starting', (snapshot.pct || 0) / 100, { row });
    h.notice(status.text, status.tone);
  },
});

ui.register('awaiting', {
  paint(h) {
    let row = h.sign('READY FOR REVIEW', { row: h.top(BLOCK.awaiting) });
    // A sentence rather than a headline, so it is set smaller and may wrap.
    row = h.sign('THE REVIEW SCREEN ARRIVES IN 4C', { row: row + 4, scale: 2 });
    h.buttonRow([againButton], row + 8, { col: Math.floor(h.cols() / 2) - 9 });
    h.notice(status.text, status.tone);
  },
});

ui.register('result', {
  enter() {
    // The transport is real HTML on the overlay: a scrub bar and volume are dense
    // controls, and drawing them as dots would be worse, not better.
    const player = document.createElement('audio');
    player.id = 'player';
    player.controls = true;
    player.preload = 'none';
    player.className = 'player';
    overlay.append(player);
    state.player = player;
  },
  paint(h) {
    const stats = state.render || {};
    let row = h.sign('DONE', { row: h.top(BLOCK.result) });
    // Figures are a sentence's worth of words, so they are set at scale 2: at
    // scale 4 "5 WORDS CENSORED" wraps to two lines and pushes the buttons off
    // the bottom of the window.
    row = h.sign(`${stats.words_censored || 0} WORDS CENSORED`, { row: row + 4, scale: 2 });
    row = h.sign(`${(stats.muted_seconds || 0).toFixed(1)} SECONDS MUTED`, { row: row + 2, scale: 2 });
    row = h.sign(`${stats.windows || 0} WINDOWS`, { row: row + 2, scale: 2 });
    if (stats.clipped_samples) {
      row = h.sign(`${stats.clipped_samples} SAMPLES CLIPPED`, { row: row + 2, scale: 2 });
    }
    row += 4;
    const centre = Math.floor(h.cols() / 2);
    h.buttonRow([playOriginal, playClean], row, { col: centre - 16 });
    row += Math.max(playOriginal.height, playClean.height) + 3;
    h.buttonRow([download], row, { col: centre - 10 });
    h.buttonRow([againButton], row + download.height + 3, { col: centre - 9 });
    h.notice(status.text, status.tone);
  },
});

/**
 * Swap the transport between the song you gave us and the censored render,
 * keeping the playhead where it was. Same element, new source: swapping elements
 * would lose the position and the play state both.
 */
function playSource(kind) {
  const player = state.player;
  if (!player || !state.job) return;
  const wasPlaying = !player.paused;
  const at = player.currentTime || 0;
  player.src = kind === 'original' ? state.objectUrl : api.outputUrl(state.job.id);
  player.addEventListener(
    'loadedmetadata',
    () => {
      player.currentTime = Math.min(at, player.duration || at);
      if (wasPlaying) player.play().catch(() => say('press play on the transport', TONE_STOP));
    },
    { once: true },
  );
  say(kind === 'original' ? 'PLAYING THE ORIGINAL' : 'PLAYING THE CENSORED RENDER');
}

ui.register('failed', {
  paint(h) {
    let row = h.sign('SOMETHING WENT WRONG', { row: h.top(BLOCK.failed) });
    row = h.sign(state.snapshot?.error || 'unknown error', { row: row + 4, scale: 2 });
    h.buttonRow([againButton], row + 6, { col: Math.floor(h.cols() / 2) - 9 });
  },
});

function stageName(stage) {
  return stage.replace(/_/g, ' ').toUpperCase();
}

// --- actions -----------------------------------------------------------------

/** Forget the current song and go back to the start. */
function startUpload() {
  if (state.stopFollowing) {
    state.stopFollowing();
    state.stopFollowing = null;
  }
  if (state.objectUrl) {
    URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = null;
  }
  Object.assign(state, {
    file: null,
    upload: null,
    job: null,
    snapshot: null,
    render: null,
    player: null,
  });
  say('');
  ui.show('welcome');
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = '';
  if (file) uploadFile(file);
});

async function uploadFile(file) {
  state.file = file;
  // The browser still holds the file, so the original is playable without the
  // server ever being asked to serve it back.
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = URL.createObjectURL(file);
  say(`UPLOADING ${file.name}`);
  ui.show('mode');
  try {
    state.upload = await api.upload(file, (pct) => say(`UPLOADING ${Math.round(pct)}%`));
    say(`${state.upload.filename} READY`);
  } catch (error) {
    say(error.message, TONE_STOP);
  }
  ui.show('mode');
}

async function startJob() {
  if (!state.upload) return;
  say('STARTING');
  try {
    state.job = await api.startJob({
      source: state.upload.source,
      mode: 'censor',
      quality: 'fast',
      export_format: 'flac',
    });
  } catch (error) {
    say(error.message, TONE_STOP);
    ui.show('mode');
    return;
  }
  ui.show('processing');
  state.stopFollowing = api.followJob(state.job.id, onJobEvent);
}

function onJobEvent(event) {
  if (event.job) state.snapshot = event;
  if (event.event === 'stage' || event.event === 'snapshot') {
    state.snapshot = { ...state.snapshot, ...event };
    if (state.snapshot.state === 'error') {
      say(state.snapshot.error || 'failed', TONE_STOP);
      ui.show('failed');
      return;
    }
    if (state.snapshot.state === 'awaiting_review') {
      say('EVERY FLAG IS WAITING FOR YOU');
      ui.show('awaiting');
      return;
    }
    ui.refresh();
  }
}

function saveOutput() {
  if (!state.job) return;
  const anchor = document.createElement('a');
  anchor.href = api.outputUrl(state.job.id);
  anchor.download = '';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

// --- a song dropped anywhere on the page -------------------------------------

window.addEventListener('dragover', (event) => {
  event.preventDefault();
});
window.addEventListener('drop', (event) => {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file) uploadFile(file);
});

window.addEventListener('error', (event) => say(String(event.message), TONE_STOP));

/**
 * Rejoin a job that is already running, from `?job=<id>`.
 *
 * A render on a laptop takes minutes, and a refresh or a closed tab should not
 * throw that away: the job lives in the server's own store, so the page can pick
 * the stream back up. A job that has already finished is not resumed - the render
 * numbers only exist in the review response, which is phase 4c's business.
 */
async function resume(id) {
  try {
    state.snapshot = await api.getJob(id);
  } catch (error) {
    say(error.message, TONE_STOP);
    ui.show('welcome');
    return;
  }
  const state_ = state.snapshot.state;
  if (state_ === 'done' || state_ === 'error') {
    say('that job has already finished - start again', TONE_STOP);
    ui.show('welcome');
    return;
  }
  state.job = { id };
  ui.show('processing');
  if (state_ === 'awaiting_review') {
    say('EVERY FLAG IS WAITING FOR YOU');
    ui.show('awaiting');
    return;
  }
  state.stopFollowing = api.followJob(id, onJobEvent);
}

const wanted = new URLSearchParams(window.location.search).get('job');
if (wanted) resume(wanted);
else ui.show('welcome');
checkInstall();

/**
 * Ask the server whether this install can actually do anything, and say so on the
 * welcome screen if it cannot.
 *
 * ffmpeg is a hard requirement and the speech model is a large download, so both
 * are better found before a user picks a song than three stages into a job. A
 * server that will not answer is not an error worth a red sign: the page still
 * works if it comes back, and `fetch` will retry on the next reload.
 */
async function checkInstall() {
  let report;
  try {
    report = await api.health();
  } catch {
    return;
  }
  if (!report.ffmpeg) {
    say(report.reason || 'ffmpeg is not installed. Install it with: brew install ffmpeg', TONE_STOP);
  } else if (!report.asr_model_present) {
    say('the speech model is not downloaded yet', TONE_STOP);
  }
}
// Handles for driving the board from a test or the console. The board is the
// only thing the page draws, so without these there is nothing to inspect.
window.__board = board;
window.__ui = ui;
window.__state = state;