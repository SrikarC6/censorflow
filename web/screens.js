/**
 * The flow screens: Welcome, Mode, Processing, Awaiting, Result, Failed.
 *
 * The buttons are created once in app.js and handed in. A painter only places
 * them. `status` is the same object `say` writes, so a redraw sees the latest line.
 */
import { TONE_GO, TONE_PLAIN } from './flipdisc.js';
import { state } from './ui.js';

export function registerFlow(ui, controls) {
  const {
    status,
    overlay,
    chooseFile,
    getModel,
    cancelMode,
    censorMode,
    qualityFast,
    qualityPro,
    stemsMode,
    againButton,
    reviewButton,
    playOriginal,
    playClean,
    download,
  } = controls;

/** How tall each screen's block is, in dots, so `top` can centre it. */
const BLOCK = { welcome: 100, mode: 118, awaiting: 120, result: 150, failed: 90 };

ui.register('welcome', {
  paint(h) {
    let row = h.top(BLOCK.welcome);
    row = h.sign('CENSORFLOW', { row });
    row = h.sign('SILENCE THE VOCALS. KEEP THE MUSIC.', { row: row + 4 });
    if (!h.tight(BLOCK.welcome)) {
      row = h.sign('A RESTART DROPS A JOB STILL RUNNING', { row: row + 3, scale: 1 });
    }
    h.buttonRow([chooseFile], row + 8, { col: h.centre([chooseFile]) });
    if (!h.tight(BLOCK.welcome) && state.model && state.model.present === false) {
      const below = row + 8 + chooseFile.height + 3;
      if (state.model.state === 'running') {
        h.meter(state.model.message || 'DOWNLOADING THE SPEECH MODEL', (state.model.pct || 0) / 100, {
          row: below,
        });
      } else {
        h.buttonRow([getModel], below, { col: h.centre([getModel]) });
      }
    }
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
    qualityFast.setTone(state.quality === 'fast' ? TONE_GO : TONE_PLAIN);
    qualityPro.setTone(state.quality === 'pro' ? TONE_GO : TONE_PLAIN);
    h.buttonRow([censorMode], row + 4, { col: h.centre([censorMode]) });
    if (!h.tight(BLOCK.mode)) {
      h.buttonRow([qualityFast, qualityPro], row + 4 + censorMode.height + 2, {
        col: h.centre([qualityFast, qualityPro]),
      });
    }
    // On a window too short for two rows, the one control that matters is the one
    // that starts the job; CHOOSE ANOTHER is always reachable from Welcome.
    if (h.tight(BLOCK.mode)) {
      h.notice(status.text, status.tone);
      return;
    }
    h.buttonRow([stemsMode], row + 4 + censorMode.height + qualityFast.height + 6, {
      col: h.centre([stemsMode]),
    });
    h.buttonRow([cancelMode], row + 4 + censorMode.height + qualityFast.height + 6 + stemsMode.height + 3, {
      col: h.centre([cancelMode]),
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
    row = h.sign('CHECK THE WORDS BEFORE ANYTHING IS MUTED', { row: row + 4, scale: 2 });
    h.buttonRow([reviewButton], row + 8, { col: h.centre([reviewButton]) });
    // One row on a short window: ANOTHER SONG is one click from Welcome and
    // START OVER is on the review screen, so REVIEW THE FLAGS wins the space.
    if (!h.tight(BLOCK.awaiting)) {
      h.buttonRow([againButton], row + 8 + reviewButton.height + 3, {
        col: h.centre([againButton]),
      });
    }
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
    if (!h.tight(BLOCK.result)) {
      row = h.sign(`${stats.words_censored || 0} WORDS CENSORED`, { row: row + 4, scale: 2 });
      row = h.sign(`${(stats.muted_seconds || 0).toFixed(1)} SECONDS MUTED`, { row: row + 2, scale: 2 });
      row = h.sign(`${stats.windows || 0} WINDOWS`, { row: row + 2, scale: 2 });
      if (stats.clipped_samples) {
        row = h.sign(`${stats.clipped_samples} SAMPLES CLIPPED`, { row: row + 2, scale: 2 });
      }
    }
    row += 4;
    if (h.tight(BLOCK.result)) {
      // There is not room for the figures and three rows of controls. The figures
      // are the first thing to go - they are also in the status line - and all four
      // buttons share one row so every one of them can be reached.
      h.buttonRow([playOriginal, playClean, download, againButton], row, {
        col: h.centre([playOriginal, playClean, download, againButton]),
      });
    } else {
      h.buttonRow([playOriginal, playClean], row, { col: h.centre([playOriginal, playClean]) });
      const below = row + Math.max(playOriginal.height, playClean.height) + 3;
      h.buttonRow([download], below, { col: h.centre([download]) });
      h.buttonRow([againButton], below + download.height + 3, { col: h.centre([againButton]) });
    }
    h.notice(status.text, status.tone);
  },
});

ui.register('failed', {
  paint(h) {
    let row = h.sign('SOMETHING WENT WRONG', { row: h.top(BLOCK.failed) });
    row = h.sign(state.snapshot?.error || 'unknown error', { row: row + 4, scale: 2 });
    h.buttonRow([againButton], row + 6, { col: h.centre([againButton]) });
  },
});

function stageName(stage) {
  return stage.replace(/_/g, ' ').toUpperCase();
}
}
