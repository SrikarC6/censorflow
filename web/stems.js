/**
 * The stems screen: labels and disabled controls, and nothing that mixes audio.
 *
 * The routes answer 501. This screen exists so STEMS is a place you can open,
 * not a button that pretends a request was made. The checklist is docs/STEMS_TODO.md.
 */
import { TONE_PLAIN } from './flipdisc.js';

const LABELS = ['VOCALS', 'DRUMS', 'BASS', 'MELODY'];
const BLOCK = 150;

export function registerStems(ui, { back }) {
  const { board } = ui;
  const backButton = board.button({
    label: 'BACK',
    scale: 1,
    onClick: back,
  });
  const stems = LABELS.map((label) => {
    const handle = board.button({
      label,
      scale: 1,
      tone: TONE_PLAIN,
      onClick: () => {},
    });
    handle.setEnabled(false);
    return handle;
  });

  ui.register('stems', {
    paint(h) {
      let row = h.top(BLOCK);
      row = h.sign('STEMS', { row });
      row = h.sign('COMING SOON', { row: row + 3, scale: 2 });
      row += 4;
      if (!h.tight(BLOCK)) {
        stems.forEach((handle) => {
          handle.setEnabled(false);
          h.buttonRow([handle], row, { col: h.centre([handle]) });
          row += handle.height + 2;
        });
      }
      h.buttonRow([backButton], row, { col: h.centre([backButton]) });
      h.notice('MIXING IS NOT BUILT YET', TONE_PLAIN);
    },
  });
}
