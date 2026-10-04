/**
 * Just enough of a browser for the flip-disc modules to load under node.
 *
 * The screens are ES modules that touch `document` and `window` as they are
 * imported, so this has to run before that import. It is a stub, not a layout
 * engine: canvas calls are counted, they are not painted.
 */

export function installDom({ width = 1200, height = 1200 } = {}) {
  function element(id) {
    const node = {
      id,
      style: {},
      textContent: '',
      classList: { add() {}, remove() {} },
      replaceChildren() {
        node.children = [];
      },
      children: [],
      _handlers: {},
      appendChild(child) {
        node.children.push(child);
        return child;
      },
      setAttribute() {},
      addEventListener(type, fn) {
        node._handlers[type] = fn;
      },
      getBoundingClientRect() {
        return { left: 0, top: 0, width, height };
      },
      click() {},
      setPointerCapture() {},
    };
    return node;
  }

  const canvas = element('board');
  const context = new Proxy(
    { fillCount: 0 },
    {
      get(target, prop) {
        if (prop === 'fillCount') return target.fillCount;
        if (prop === 'fill') {
          return () => {
            target.fillCount += 1;
          };
        }
        return () => {};
      },
      set(target, prop, value) {
        target[prop] = value;
        return true;
      },
    },
  );
  canvas.getContext = () => context;

  const nodes = {
    board: canvas,
    overlay: element('overlay'),
    live: element('live'),
    file: element('file'),
  };

  const document = {
    documentElement: element('html'),
    getElementById(id) {
      return nodes[id] || null;
    },
    createElement() {
      return element('made');
    },
  };

  const window = {
    innerWidth: width,
    innerHeight: height,
    devicePixelRatio: 1,
    location: { search: '' },
    document,
    setTimeout,
    clearTimeout,
    addEventListener(type, fn) {
      window._handlers[type] = fn;
    },
    _handlers: {},
    requestAnimationFrame() {
      throw new Error('the board must not animate');
    },
  };

  class ResizeObserver {
    observe() {}
    disconnect() {}
  }
  window.ResizeObserver = ResizeObserver;

  Object.assign(globalThis, {
    window,
    document,
    ResizeObserver,
    getComputedStyle() {
      return { getPropertyValue: () => '' };
    },
    HTMLElement: class HTMLElement {},
    Node: class Node {},
  });

  return { canvas, nodes };
}
