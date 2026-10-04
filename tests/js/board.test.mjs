/**
 * Execute the flip-disc board and the real screens.
 *
 * Text searches of the source missed a redraw that called itself until the
 * stack died, and a progress bar whose width was never passed. This process
 * loads the modules and drives them.
 */

import assert from 'node:assert/strict';

import { installDom } from './dom.mjs';

installDom();

const { createBoard } = await import('../../web/flipdisc.js');
const { createUi } = await import('../../web/ui.js');

const canvas = document.getElementById('board');
const board = createBoard(canvas, { pitch: 4 });

board.stampText('HI', 2, 2, { scale: 1 });
board.redraw();
assert.ok(canvas.getContext().fillCount > 0, 'stamped text never lit a disc');

const clicks = [];
const button = board.button({ label: 'GO', onClick: () => clicks.push('go') });
button.place(4, 4);
board.redraw();
click(canvas, 4 * 4 + 2, 4 * 4 + 2);
assert.deepEqual(clicks, ['go'], 'a placed button did not receive the click');

button.hide();
click(canvas, 4 * 4 + 2, 4 * 4 + 2);
assert.deepEqual(clicks, ['go'], 'a hidden button still received the click');

const tone = board.button({ label: 'FAST', onClick() {} });
board.onDraw(() => {
  tone.setTone('go');
  tone.place(2, 20);
});
board.redraw();
assert.equal(tone.tone, 'go', 'setTone during paint did not stick');

const ui = createUi({ canvas, overlay: document.getElementById('overlay') });
ui.register('meter', {
  paint(h) {
    h.meter('DOWNLOADING', 0.5, { row: 2 });
  },
});
ui.show('meter');
assert.ok(canvas.getContext().fillCount > 0, 'the progress meter drew nothing');

// The app module paints Welcome as it loads. Health is stubbed so it does not
// try to reach a server.
globalThis.fetch = async () => ({
  ok: true,
  json: async () => ({ ffmpeg: true, asr_model_present: false, reason: '' }),
});
await import('../../web/app.js');
await new Promise((resolve) => setTimeout(resolve, 0));

const appUi = globalThis.window.__ui;
const liveBoard = globalThis.window.__board;
assert.equal(appUi.screen, 'welcome');
const welcome = shown();
assert.ok(welcome.includes('UPLOAD A SONG'), `welcome buttons: ${welcome}`);
assert.ok(welcome.includes('GET SPEECH MODEL'), `welcome buttons: ${welcome}`);

appUi.show('mode');
const pro = liveBoard.allButtons().find((handle) => handle.label === 'PRO');
pro.onClick();
assert.equal(globalThis.window.__state.quality, 'pro');
const mode = shown();
for (const label of ['CENSOR', 'FAST', 'PRO', 'STEMS', 'PREVIOUS PAGE']) {
  assert.ok(mode.includes(label), `mode is missing ${label}: ${mode}`);
}

appUi.show('stems');
const stems = liveBoard.handles().filter((handle) => handle.shown);
const stemLabels = stems.map((handle) => handle.label);
for (const label of ['VOCALS', 'DRUMS', 'BASS', 'MELODY', 'BACK']) {
  assert.ok(stemLabels.includes(label), `stems is missing ${label}: ${stemLabels}`);
}
const vocals = stems.find((handle) => handle.label === 'VOCALS');
assert.equal(vocals.enabled, false, 'a stem control is enabled');

function shown() {
  return globalThis.window.__board
    .handles()
    .filter((handle) => handle.shown)
    .map((handle) => handle.label);
}

function click(target, clientX, clientY) {
  const event = { clientX, clientY, pointerId: 1 };
  target._handlers.pointerdown(event);
  target._handlers.pointerup(event);
}
