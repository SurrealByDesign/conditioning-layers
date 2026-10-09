// Display-only helpers. No field writes, host imports or import-time DOM work.
import {footprintToCell} from "./brush.js";

export const SELECTION_VEIL = Object.freeze([128, 0, 255, 60]);

export function selectionOutlinePath(mask) {
  if (mask === null) return "";
  const runs = [], at = (x, y) => x < 0 || x >= 128 || y < 0 || y >= 128 ? 0 : mask[y * 128 + x];
  for (let y = 0; y <= 128; y++) for (let x = 0; x < 128;) {
    if (at(x, y - 1) === at(x, y)) { x++; continue; }
    const start = x++;
    while (x < 128 && at(x, y - 1) !== at(x, y)) x++;
    runs.push(`M${start} ${y}H${x}`);
  }
  for (let x = 0; x <= 128; x++) for (let y = 0; y < 128;) {
    if (at(x - 1, y) === at(x, y)) { y++; continue; }
    const start = y++;
    while (y < 128 && at(x - 1, y) !== at(x, y)) y++;
    runs.push(`M${x} ${start}V${y}`);
  }
  return runs.join(" ");
}

export function heatColor(code) {
  // Black -> red -> yellow -> white. Every channel, and luminance, is monotonic.
  return [Math.min(255, code * 3), Math.max(0, Math.min(255, code * 3 - 255)),
    Math.max(0, code * 3 - 510)];
}

export function fieldPosition(clientX, clientY, rect, zoom, panX, panY) {
  return {x: (clientX - rect.left - panX) / zoom, y: (clientY - rect.top - panY) / zoom};
}

export function cellReadout(codes, position) {
  if (!position) return null;
  const x = Math.floor(position.x), y = Math.floor(position.y);
  if (!(x >= 0 && x < 128 && y >= 0 && y < 128)) return null;
  const code = codes[y * 128 + x];
  return {x, y, code, percent: code * 100 / 255};
}

export function gridVisible(enabled, zoom) { return enabled && zoom >= 8; }

export function gridPath() {
  const lines = [];
  for (let i = 0; i <= 128; i++) lines.push(`M${i} 0V128`, `M0 ${i}H128`);
  return lines.join(" ");
}

export function fieldStatistics(codes) {
  let nonzero = 0, min = 255, max = 0, sum = 0, binary = true;
  const distinct = new Set();
  for (const code of codes) {
    if (code) nonzero++;
    if (code !== 0 && code !== 255) binary = false;
    min = Math.min(min, code); max = Math.max(max, code); sum += code; distinct.add(code);
  }
  return {total: codes.length, nonzero, zero: codes.length - nonzero, binary,
    min, max, mean: sum / codes.length, distinct: distinct.size};
}

export function displayState(view, hasReference) {
  return {referenceOpacity: view.referenceOpacity / 100,
    fieldOpacity: view.comparing && hasReference ? 0 : hasReference ? 0.5 : 1};
}

export function createViewSession() {
  return {grid: false, heat: false, referenceOpacity: 50, comparing: false};
}

// Keep the side of an axis-aligned line where sign * (point[axis] - limit) >= 0.
function clip(points, axis, limit, sign) {
  const kept = [];
  points.forEach((p, i) => {
    const q = points[(i + 1) % points.length], a = sign * (p[axis] - limit), b = sign * (q[axis] - limit);
    if (a >= 0) kept.push(p);
    if ((a >= 0) !== (b >= 0)) {
      const t = a / (a - b);
      kept.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
    }
  });
  return kept;
}

// Outline of a prepared footprint as offsets from its stamp anchor, in field cells: the shape
// clipped to its crop, then mirrored, scaled and rotated. The disk is drawn as a 128-gon and a
// custom tip as its (cropped) frame; the exact covered cells are the stamp preview's job.
export function footprintOutline(footprint) {
  const r = footprint.radius, {centerX: cx, centerY: cy, halfX: hx, halfY: hy, radiusX: rx, radiusY: ry} = footprint;
  let points = footprint.shape === "disk"
    ? Array.from({length: 128}, (_, k) => [r * Math.cos(k * Math.PI / 64), r * Math.sin(k * Math.PI / 64)])
    : footprint.shape === "square" ? [[r, r], [-r, r], [-r, -r], [r, -r]]
    : footprint.shape === "diamond" ? [[r, 0], [0, r], [-r, 0], [0, -r]] : [[rx, ry], [-rx, ry], [-rx, -ry], [rx, -ry]];
  for (const [axis, limit, sign] of [[0, cx - hx, 1], [0, cx + hx, -1], [1, cy - hy, 1], [1, cy + hy, -1]])
    points = clip(points, axis, limit, sign);
  return points.map(([u, v]) => footprintToCell(footprint, u, v));
}

export function outlinePath(points, [x, y]) {
  return points.length ? `${points.map(([px, py], i) => `${i ? "L" : "M"}${x + px} ${y + py}`).join(" ")} Z` : "";
}
// Session context only: these pixels never feed back into field codes.
export const OVERLAY_COLORS = Object.freeze([
  [249, 100, 241], [184, 254, 96], [9, 135, 119], [215, 25, 8]].map(c => Object.freeze(c)));
export function overlayAlpha(code) { return code === 0 ? 0 : 32 + Math.floor((64 * code + 85) / 170); }
export function overlayPixels(codes, color) {
  const out = new Uint8ClampedArray(65536);
  for (let i = 0; i < 16384; i++) {
    const j = i * 4;
    out[j] = color[0]; out[j + 1] = color[1]; out[j + 2] = color[2]; out[j + 3] = overlayAlpha(codes[i]);
  }
  return out;
}
