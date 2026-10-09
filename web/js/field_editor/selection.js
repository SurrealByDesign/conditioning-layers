// Session-only binary cell geometry. null is no gate, never an all-ones mask.
export const SELECTION_MODES = Object.freeze(["replace", "add", "subtract"]);

export function selectionCell(position) {
  return {x: Math.max(0, Math.min(127, Math.floor(position.x))),
    y: Math.max(0, Math.min(127, Math.floor(position.y)))};
}

export function onField(position) {
  return position !== null && position.x >= 0 && position.x < 128 && position.y >= 0 && position.y < 128;
}

export function selectionRectangle(a, b) {
  a = selectionCell(a); b = selectionCell(b);
  const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
  return {x0, x1, y0, y1, width: x1 - x0 + 1, height: y1 - y0 + 1};
}

export function rectangleSelection(a, b) {
  const {x0, x1, y0, y1} = selectionRectangle(a, b), mask = new Uint8Array(16384);
  for (let y = y0; y <= y1; y++) mask.fill(1, y * 128 + x0, y * 128 + x1 + 1);
  return mask;
}

export function ellipseSelection(a, b) {
  const {x0, x1, y0, y1, width: w, height: h} = selectionRectangle(a, b), mask = new Uint8Array(16384);
  const ww = w * w, hh = h * h;
  for (let y = y0; y <= y1; y++) {
    const v = 2 * (y - y0) + 1 - h;
    for (let x = x0; x <= x1; x++) {
      const u = 2 * (x - x0) + 1 - w;
      if (u * u * hh + v * v * ww <= ww * hh) mask[y * 128 + x] = 1;
    }
  }
  return mask;
}

export function combineSelection(current, shape, mode) {
  if (!SELECTION_MODES.includes(mode)) throw new Error("Invalid selection mode");
  const next = shape.map((v, i) => mode === "replace" ? v
    : mode === "add" ? Number(!!(v || current?.[i])) : Number(!!current?.[i] && !v));
  return next.some(Boolean) ? next : null;
}

export function invertSelection(current) {
  if (current === null) return selectAll();
  const next = current.map(v => 1 - v);
  return next.some(Boolean) ? next : null;
}

export function selectAll() { return new Uint8Array(16384).fill(1); }

export function selectionStats(mask) {
  let count = 0, left = 128, right = -1, top = 128, bottom = -1;
  if (mask !== null) for (let i = 0; i < mask.length; i++) if (mask[i]) {
    count++; const x = i % 128, y = Math.floor(i / 128);
    left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
  }
  return {count, left, right, top, bottom};
}
