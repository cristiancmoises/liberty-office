// Some browser/monitor combinations report CSS-sized device-pixel boxes.
// eframe trusts those boxes, which otherwise doubles its UI at DPR 2.
export function canvasEntry(entry, canvas, win) {
  if (entry.target !== canvas || !('devicePixelContentBoxSize' in entry)) return entry;
  const css = entry.contentBoxSize?.[0] || entry.contentBoxSize;
  const inline = css?.inlineSize ?? entry.contentRect?.width;
  const block = css?.blockSize ?? entry.contentRect?.height;
  const dpr = win.devicePixelRatio;
  if (![inline, block, dpr].every(value => Number.isFinite(value) && value > 0)) return entry;
  const width = Math.round(inline * dpr), height = Math.round(block * dpr);
  const original = entry.devicePixelContentBoxSize?.[0];
  if (original && Math.abs(original.inlineSize - width) <= 1 && Math.abs(original.blockSize - height) <= 1) return entry;
  const prototype = original ? Object.getPrototypeOf(original) : win.ResizeObserverSize?.prototype;
  if (!prototype) return entry;
  // Keep native prototypes: wasm-bindgen checks the browser interface types.
  const size = Object.create(prototype, {
    inlineSize: { value: width }, blockSize: { value: height },
  });
  Object.defineProperty(entry, 'devicePixelContentBoxSize', { value: [size], configurable: true });
  return entry;
}

const installed = new WeakSet();
export function installCanvasDensity(win, canvas = win.document.querySelector('canvas')) {
  if (!canvas || !win.ResizeObserver || installed.has(win)) return;
  const NativeObserver = win.ResizeObserver;
  win.ResizeObserver = class extends NativeObserver {
    constructor(callback) {
      super((entries, observer) => callback(entries.map(entry => canvasEntry(entry, canvas, win)), observer));
    }
  };
  installed.add(win);
}
