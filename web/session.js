/**
 * What happens after a button: upload, run, review, download, rejoin.
 *
 * The screens only paint. This module is the sequence those clicks start.
 */
import * as api from './api.js';
import { TONE_STOP } from './flipdisc.js';
import { state } from './ui.js';

export function attachSession(ui, { say, review, fileInput }) {
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
  // The browser's own copy of the upload is free, but it only exists while this page has
  // been alive. After a reload the server still has the untouched file, so fall back to it
  // rather than handing the element a null source that would look like a working player.
  const original = state.objectUrl || api.originalUrl(state.job.id);
  player.src = kind === 'original' ? original : api.outputUrl(state.job.id);
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
  // The review screen keeps its own copy of the transcript and the flags, because
  // they are what the user is editing. A new song must not inherit them.
  review.reset();
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
      quality: state.quality || 'fast',
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
      say('every flag is waiting for you');
      review.open(state.job.id);
      return;
    }
    ui.refresh();
  }
}

function saveOutput() {
  if (!state.job) return;
  const name = state.render?.filename;
  const anchor = document.createElement('a');
  anchor.href = api.outputUrl(state.job.id);
  anchor.download = name || '';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  say(name ? `SAVED ${name}` : 'SAVED');
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

/**
 * Rejoin a job that is already running, from `?job=<id>`.
 *
 * A render on a laptop takes minutes, and a refresh or a closed tab should not
 * throw that away: the job lives in the server's own store, so the page can pick
 * the stream back up. A job that has already finished rejoins the result screen,
 * because the figures it needs now travel in the job's own snapshot.
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
  if (state_ === 'error') {
    say(state.snapshot.error || 'that job failed - start again', TONE_STOP);
    ui.show('failed');
    return;
  }
  state.job = { id };
  if (state_ === 'done') {
    // The render already happened, so the file is on disk. Refusing to rejoin here would
    // throw the download away over a refresh, which is the one thing the user came back for.
    state.render = state.snapshot.render || state.render;
    if (!state.render) {
      say('that job has finished but its figures are gone - start again', TONE_STOP);
      ui.show('welcome');
      return;
    }
    say('this song is already rendered - here it is again');
    ui.show('result');
    return;
  }
  if (state_ === 'awaiting_review') {
    say('every flag is waiting for you');
    review.open(id);
    return;
  }
  ui.show('processing');
  state.stopFollowing = api.followJob(id, onJobEvent);
}

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
    state.model = { present: false, state: 'idle', pct: 0, message: '' };
    say('the speech model is not downloaded yet', TONE_STOP);
  }
}

  return { startUpload, startJob, playSource, saveOutput, resume, checkInstall };
}
