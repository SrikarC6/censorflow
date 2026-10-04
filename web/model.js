/**
 * First-run speech-model download.
 *
 * The welcome screen places the button. This module only talks to the server
 * and writes `state.model`, which the painter reads.
 */
import * as api from './api.js';
import { TONE_STOP } from './flipdisc.js';
import { state } from './ui.js';

let polling = false;

/** Start the download, then keep `state.model` current until it finishes. */
export async function beginModelDownload(ui, say) {
  let report;
  try {
    report = await api.startModelDownload();
  } catch (error) {
    say(error.message, TONE_STOP);
    return;
  }
  state.model = report;
  ui.refresh();
  if (report.state === 'running') follow(ui, say);
}

async function follow(ui, say) {
  if (polling) return;
  polling = true;
  try {
    for (;;) {
      const report = await api.modelStatus();
      state.model = report;
      ui.refresh();
      if (report.state !== 'running') {
        if (report.state === 'error') say(report.message, TONE_STOP);
        else if (report.present) say('the speech model is ready');
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
  } catch (error) {
    say(error.message, TONE_STOP);
  } finally {
    polling = false;
  }
}
