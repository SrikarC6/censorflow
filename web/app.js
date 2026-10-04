/**
 * Wiring: the buttons, the status line, and which module owns each screen.
 *
 * Painters live in screens.js. What a click does lives in session.js. The review
 * screen lives in review.js. A button is created once, here, and placed by a painter.
 */
import { hideWelcome, mountAtmosphere, syncBanner } from './atmosphere.js';
import { hideGame, mountGame } from './game-scene.js';
import { hideHoop, mountHoop } from './hoop-scene.js';
import { hideScene, mountScene } from './welcome-scene.js';
import { TONE_GO, TONE_INFO, TONE_PLAIN } from './flipdisc.js';
import { beginModelDownload } from './model.js';
import { registerReview } from './review.js';
import { registerFlow } from './screens.js';
import { attachSession } from './session.js';
import { registerStems } from './stems.js';
import { createUi, state } from './ui.js';

const canvas = document.getElementById('board');
const overlay = document.getElementById('overlay');
const live = document.getElementById('live');
const fileInput = document.getElementById('file');

const ui = createUi({ canvas, overlay });
const { board } = ui;
mountAtmosphere(board);
mountScene(board);
mountHoop(board);
mountGame(board);
// After the screen paints, so a welcome redraw has already recorded the slogan.
board.onDraw(() => {
  syncBanner();
  if (ui.screen !== 'welcome') {
    hideWelcome();
    hideScene();
  }
  if (ui.screen !== 'processing') hideHoop();
  if (ui.screen !== 'result') hideGame();
});

/** The status line under everything. `say` writes this object; painters read it. */
const status = { text: '', tone: TONE_PLAIN };

/** Say something in the status line and to a screen reader, in one call. */
function say(text, tone = TONE_PLAIN) {
  status.text = text;
  status.tone = tone;
  live.textContent = text;
  ui.refresh();
}

// Filled in once the session exists. Clicks happen after that, so the buttons
// may close over it before attachSession returns.
const actions = {};

// --- buttons -----------------------------------------------------------------
// Created once, placed by the painters. See the note at the top of ui.js.
const chooseFile = board.button({
  label: 'UPLOAD A SONG',
  scale: 2,
  tone: TONE_GO,
  onClick: () => fileInput.click(),
});
const getModel = board.button({
  label: 'GET SPEECH MODEL',
  scale: 1,
  tone: TONE_GO,
  onClick: () => beginModelDownload(ui, say),
});
const cancelMode = board.button({
  label: 'PREVIOUS PAGE',
  scale: 1,
  tone: TONE_INFO,
  onClick: () => actions.startUpload(),
});
const censorMode = board.button({
  label: 'CENSOR',
  scale: 2,
  onClick: () => actions.startJob(),
});
const qualityFast = board.button({
  label: 'FAST',
  scale: 1,
  onClick: () => {
    state.quality = 'fast';
    ui.refresh();
  },
});
const qualityPro = board.button({
  label: 'PRO',
  scale: 1,
  onClick: () => {
    state.quality = 'pro';
    ui.refresh();
  },
});
const stemsMode = board.button({
  label: 'STEMS',
  scale: 2,
  knockout: true,
  onClick: () => ui.show('stems'),
});
const againButton = board.button({
  label: 'ANOTHER SONG',
  scale: 1,
  onClick: () => actions.startUpload(),
});
const playOriginal = board.button({
  label: 'ORIGINAL',
  scale: 1,
  onClick: () => actions.playSource('original'),
});
const playClean = board.button({
  label: 'CLEAN',
  scale: 1,
  onClick: () => actions.playSource('clean'),
});
const download = board.button({
  label: 'DOWNLOAD',
  scale: 2,
  tone: TONE_GO,
  onClick: () => actions.saveOutput(),
});
const reviewButton = board.button({
  label: 'REVIEW THE FLAGS',
  scale: 2,
  tone: TONE_GO,
  onClick: () => review.open(state.job.id),
});

// The review screens live in their own module; they are handed the two things they
// cannot own, the status line and the way out.
const review = registerReview(ui, {
  say,
  startUpload: () => actions.startUpload(),
  status: () => status,
});
registerStems(ui, { back: () => ui.show('mode') });
Object.assign(
  actions,
  attachSession(ui, { say, review, fileInput }),
);
registerFlow(ui, {
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
});

const wanted = new URLSearchParams(window.location.search).get('job');
if (wanted) actions.resume(wanted);
else ui.show('welcome');
actions.checkInstall();

// Handles for driving the board from a test or the console. The board is the
// only thing the page draws, so without these there is nothing to inspect.
window.__board = board;
window.__ui = ui;
window.__state = state;
window.__review = review;
