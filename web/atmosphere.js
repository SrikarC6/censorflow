/**
 * A rectangular glow on the banner, the slogan and Choose a Song.
 *
 * The glow is an HTML box the same size as each plate. Banner and slogan stay
 * still. Choose a Song's green glow pulses in CSS, so the dot grid is not redrawn.
 */
import { getFont } from './font5x7.js';

const BANNER_SCALE = 2;

let api = null;

function place(node, rect) {
  if (!rect) {
    node.hidden = true;
    return;
  }
  const key = `${rect.col}:${rect.row}:${rect.cols}:${rect.rows}`;
  node.hidden = false;
  if (node._at === key) return;
  node._at = key;
  const pitch = api.pitch();
  node.style.transform = `translate(${rect.col * pitch}px, ${rect.row * pitch}px)`;
  node.style.width = `${rect.cols * pitch}px`;
  node.style.height = `${rect.rows * pitch}px`;
}

/** Build the overlay once the board exists. Safe to call from the node tests. */
export function mountAtmosphere(board) {
  const root = document.createElement('div');
  root.className = 'atmosphere';
  const banner = document.createElement('div');
  banner.className = 'glow glow-amber';
  const slogan = document.createElement('div');
  slogan.className = 'glow glow-amber glow-slogan';
  const button = document.createElement('div');
  button.className = 'glow glow-go glow-button';
  slogan.hidden = true;
  button.hidden = true;
  root.appendChild(banner);
  root.appendChild(slogan);
  root.appendChild(button);

  const boardEl = document.getElementById('board');
  if (boardEl?.parentNode) boardEl.parentNode.insertBefore(root, boardEl.nextSibling);
  else document.documentElement.appendChild(root);

  api = {
    pitch: () => board.pitch,
    syncBanner() {
      const rows = getFont().rows * BANNER_SCALE + 4;
      place(banner, { col: 1, row: 0, cols: Math.max(12, board.cols - 2), rows });
    },
    showWelcome(sloganBox, buttonBox) {
      place(slogan, sloganBox);
      place(button, buttonBox);
    },
    hideWelcome() {
      if (slogan.hidden && button.hidden) return;
      slogan.hidden = true;
      button.hidden = true;
      slogan._at = '';
      button._at = '';
    },
  };
  return api;
}

export function syncBanner() {
  api?.syncBanner();
}

export function showWelcome(sloganBox, buttonBox) {
  api?.showWelcome(sloganBox, buttonBox);
}

export function hideWelcome() {
  api?.hideWelcome();
}
