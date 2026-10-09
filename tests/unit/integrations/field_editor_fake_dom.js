// Logic-only DOM fixture. No browser, transport, layout or host qualification.
export function installDOM() {
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.attributes = {};
      this.listeners = {}; this.value = ""; this.readOnly = false; this.open = false; this.hidden = false;
      this.classList = {add: name => { this.className = name; }}; }
    append(...items) { for (const item of items) { this.children.push(item); item.parent = this; } }
    replaceChildren(...items) { this.children = []; this.append(...items); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); }
    addEventListener(name, fn) { (this.listeners[name] ??= []).push(fn); }
    removeEventListener(name, fn) { this.listeners[name] = (this.listeners[name] ?? []).filter(f => f !== fn); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') delete this.src; }
    decode() { return Promise.resolve(); }
    focus() { document.activeElement = this; }
    select() { this.selected = true; }
    setPointerCapture(id) { this.captured = id; }
    releasePointerCapture() { this.captured = null; }
    getBoundingClientRect() { return {left: 0, top: 0, width: 528, height: 528}; }
    showModal() { this.open = true; this.focus(); }
    close() { this.open = false; }
    click() { return fire(this, "click"); }
    getContext() { return {createImageData: (w, h) => ({data: new Uint8ClampedArray(w * h * 4)}),
      putImageData: pixels => { this.pixels = pixels.data; }, clearRect: () => { this.pixels = null; }}; }
  }
  globalThis.document = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    body: new Element("body"), activeElement: null};
  globalThis.window = new Element("window"); window.confirm = () => true;
  let sequence = 0;
  const frames = new Map();
  globalThis.requestAnimationFrame = fn => { frames.set(++sequence, fn); return sequence; };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  return {Element, frames, flush() { for (const [id, fn] of [...frames]) { frames.delete(id); fn(); } }};
}
export function fire(element, type, args = {}) {
  const event = {type, target: element, button: 0, pointerId: 1, pointerType: "mouse", clientX: 0, clientY: 0,
    stopPropagation() { this.stopped = true; }, stopImmediatePropagation() { this.stopped = true; },
    preventDefault() { this.prevented = true; }, ...args};
  for (const fn of element.listeners[type] ?? []) fn(event);
  return event;
}
export function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }
export const settle = () => new Promise(resolve => setImmediate(resolve));
