/**
 * Flip-disc sound.
 *
 * Ported from `lib/flip-sound.ts` in the flip-disc portfolio prototype, with the
 * types stripped. The synthesis is unchanged because it is the good part: a
 * lubed tactile switch bottoming out, run through a lowpass and a compressor
 * so a dense row of flips blends into a rattle instead of clipping.
 *
 * Audio is strictly opt-in and strictly a user gesture. Nothing here makes a
 * sound until `setSoundEnabled(true)` runs from a click, and the choice is
 * remembered in localStorage.
 */

const STORAGE_KEY = 'flip-sound';

/** Fastest a good typist goes; denser than this blurs into a rattle. */
const MIN_KEY_GAP = 0.05;

/** Dispatched when sound is switched on, so a listener can replay a flourish. */
export const SOUND_ON_EVENT = 'flipsound:on';

let enabled = false;
let loaded = false;
let ctx = null;
let master = null;
let noise = null;
let lastKeyAt = 0;

const listeners = new Set();

function load() {
  if (loaded || typeof window === 'undefined') return;
  loaded = true;
  enabled = window.localStorage.getItem(STORAGE_KEY) === 'on';
}

/** Call `listener` whenever sound is toggled. Returns an unsubscribe function. */
export function subscribeSound(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isSoundEnabled() {
  load();
  return enabled;
}

/**
 * Build the graph on first use. Rolling off the highs is what makes the flip
 * creamy instead of clacky; the compressor is what keeps a whole row of them
 * from stacking into a click.
 */
function ensureContext() {
  if (!ctx) {
    ctx = new AudioContext();
    master = ctx.createGain();
    master.gain.value = 0.6;
    const soften = ctx.createBiquadFilter();
    soften.type = 'lowpass';
    soften.frequency.value = 3800;
    soften.Q.value = 0.5;
    const glue = ctx.createDynamicsCompressor();
    glue.threshold.value = -18;
    glue.ratio.value = 3;
    glue.attack.value = 0.002;
    glue.release.value = 0.08;
    master.connect(soften).connect(glue).connect(ctx.destination);
    noise = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 0.1), ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
  }
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

/** Must be called from a user gesture so the browser allows audio. */
export function setSoundEnabled(next) {
  load();
  enabled = next;
  window.localStorage.setItem(STORAGE_KEY, next ? 'on' : 'off');
  if (next) {
    ensureContext();
    window.dispatchEvent(new Event(SOUND_ON_EVENT));
  }
  listeners.forEach((listener) => listener());
}

if (typeof window !== 'undefined') {
  const unlock = () => {
    if (isSoundEnabled()) ensureContext();
  };
  window.addEventListener('pointerdown', unlock, { passive: true });
  window.addEventListener('keydown', unlock);
}

function envelope(audio, at, peak, attack, decay) {
  const gain = audio.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(peak, at + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
  return gain;
}

function tone(audio, at, from, to, peak, decay) {
  if (!master) return;
  const osc = audio.createOscillator();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(from, at);
  osc.frequency.exponentialRampToValueAtTime(to, at + decay);
  osc.connect(envelope(audio, at, peak, 0.003, decay)).connect(master);
  osc.start(at);
  osc.stop(at + decay + 0.02);
}

function burst(audio, at, type, frequency, q, peak, decay) {
  if (!master || !noise) return;
  const src = audio.createBufferSource();
  src.buffer = noise;
  src.playbackRate.value = 0.9 + Math.random() * 0.2;
  const filter = audio.createBiquadFilter();
  filter.type = type;
  filter.frequency.value = frequency;
  filter.Q.value = q;
  src.connect(filter).connect(envelope(audio, at, peak, 0.001, decay)).connect(master);
  src.start(at);
  src.stop(at + decay + 0.02);
}

/**
 * A lubed tactile switch bottoming out: a low damped body (the "thock"), a
 * muffled impact, and a faint top-end tick so it still reads as a keypress.
 */
function keystroke(audio, at, pitch, level) {
  tone(audio, at, pitch, pitch * 0.78, level, 0.075);
  tone(audio, at, pitch * 2.4, pitch * 2.1, level * 0.28, 0.035);
  burst(audio, at, 'lowpass', 1300, 0.9, level * 0.55, 0.022);
  burst(audio, at, 'bandpass', 2600, 2.2, level * 0.07, 0.008);
}

/** The key springing back: same voice, softer and a touch higher. */
function release(audio, at, pitch, level) {
  tone(audio, at, pitch * 1.18, pitch * 0.95, level * 0.3, 0.045);
  burst(audio, at, 'lowpass', 1600, 0.9, level * 0.18, 0.014);
}

/**
 * One keystroke per row, rate-limited across every animation on the page.
 * `discs` is how many discs actually changed in this frame, which nudges the
 * level so a single flip is quiet and a full-board wipe has some weight.
 */
export function playRowFlip(discs, large = false) {
  if (!isSoundEnabled() || discs === 0 || !ctx || ctx.state !== 'running') return;

  const now = ctx.currentTime;
  if (now - lastKeyAt < MIN_KEY_GAP) return;
  lastKeyAt = now;

  const at = now + 0.005 + Math.random() * 0.012;
  const pitch = (large ? 165 : 205) * (0.94 + Math.random() * 0.12);
  const weight = 0.8 + 0.2 * Math.min(1, discs / 12);
  const level = (large ? 0.55 : 0.4) * weight * (0.85 + Math.random() * 0.15);
  keystroke(ctx, at, pitch, level);
  release(ctx, at + 0.085 + Math.random() * 0.03, pitch, level);
}
