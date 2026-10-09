import {decodePngPlanes} from "./custom_tip.js";

export const MASK_LIMITS = Object.freeze({fileBytes: 33554432, side: 4096, pixels: 16777216});
export const MASK_READS = Object.freeze(["luminance", "alpha", "alpha_luminance"]);
export const MASK_PLACEMENTS = Object.freeze(["stretch", "fit", "fill"]);
export const MASK_DEFAULTS = Object.freeze({read: "luminance", placement: "stretch", binary: false, invert: false});
const FILE_MESSAGE = "PNG files for mask import may be at most 33,554,432 bytes.";

export async function readMaskFile(file) {
  if (!(file?.size <= MASK_LIMITS.fileBytes)) throw new Error(FILE_MESSAGE);
  return decodePngPlanes(new Uint8Array(await file.arrayBuffer()), {...MASK_LIMITS, fileMessage: FILE_MESSAGE,
    sizeMessage: (w, h) => `Masks may be at most 4,096 pixels a side and 16,777,216 pixels in all; this PNG is ${w}×${h}.`});
}

export function maskPlacement(width, height, placement) {
  if (!MASK_PLACEMENTS.includes(placement)) throw new Error("Invalid mask placement");
  const region = {x0: 0, y0: 0, sw: width, sh: height, ox: 0, oy: 0, rw: 128, rh: 128};
  if (placement === "fit") {
    if (width >= height) {
      region.rh = Math.max(1, Math.floor((256 * height + width) / (2 * width)));
      region.oy = Math.floor((128 - region.rh) / 2);
    } else {
      region.rw = Math.max(1, Math.floor((256 * width + height) / (2 * height)));
      region.ox = Math.floor((128 - region.rw) / 2);
    }
  } else if (placement === "fill") {
    const side = Math.min(width, height);
    region.x0 = Math.floor((width - side) / 2); region.y0 = Math.floor((height - side) / 2);
    region.sw = region.sh = side;
  }
  return region;
}

// Direct canonical planes avoid copies. Only Alpha × Luminance needs a cached plane.
// The source is dialog-owned; its weak key releases the cache after disposal.
const ALPHA_LUMINANCE = new WeakMap();
function alphaLuminanceRow(y, a, codes, from, to) {
  for (let i = from; i < to; i++) codes[i] = Math.floor((a[i] * y[i] + 127) / 255);
}
function channelCodes(source, read) {
  if (read === "luminance") return source.luminance;
  if (read === "alpha") return source.alpha;
  let codes = ALPHA_LUMINANCE.get(source);
  if (!codes) {
    codes = new Uint8Array(source.width * source.height);
    for (let y = 0; y < source.height; y++) alphaLuminanceRow(source.luminance, source.alpha, codes, y * source.width, (y + 1) * source.width);
    ALPHA_LUMINANCE.set(source, codes);
  }
  return codes;
}
// Each footprint sums to sourceSize in integer scaled units.
// Typed axis weights: destination j uses count[j] source indices from start[j], weights from offset[j].
function axisWeights(sourceSize, targetSize) {
  const start = new Int32Array(targetSize), count = new Int32Array(targetSize), offset = new Int32Array(targetSize), list = [];
  for (let j = 0; j < targetSize; j++) {
    const lo = j * sourceSize, hi = (j + 1) * sourceSize;
    start[j] = Math.floor(lo / targetSize); offset[j] = list.length;
    for (let i = start[j]; i * targetSize < hi; i++) list.push(Math.min(hi, (i + 1) * targetSize) - Math.max(lo, i * targetSize));
    count[j] = list.length - offset[j];
  }
  return {start, count, offset, weight: Int32Array.from(list)};
}
function horizontalRow(m, from, cols, out, at, rw) {
  const {start, count, offset, weight} = cols;
  for (let j = 0; j < rw; j++) {
    let sum = 0;
    const s = from + start[j], w = offset[j], n = count[j];
    for (let k = 0; k < n; k++) sum += weight[w + k] * m[s + k];
    out[at + j] = sum;
  }
}
function verticalRow(horizontal, rows, k, rw, numerators) {
  const s = rows.start[k], w = rows.offset[k], n = rows.count[k];
  for (let j = 0; j < rw; j++) numerators[j] = 0;
  for (let q = 0; q < n; q++) {
    const weight = rows.weight[w + q], base = (s + q) * rw;
    for (let j = 0; j < rw; j++) numerators[j] += weight * horizontal[base + j];
  }
}
export function reduceMask(source, options) {
  const {read, placement, binary, invert} = options;
  if (!MASK_READS.includes(read) || typeof binary !== "boolean" || typeof invert !== "boolean")
    throw new Error("Invalid mask options");
  const m = channelCodes(source, read);
  const {x0, y0, sw, sh, ox, oy, rw, rh} = maskPlacement(source.width, source.height, placement);
  const columns = axisWeights(sw, rw), rows = axisWeights(sh, rh);
  // Horizontal sums <= 255 * 4096 = 1,044,480, safely signed int32.
  // Vertical numerators <= 255 * 4096 * 4096 = 4,278,190,080: binary64,
  // never signed int32. No intermediate quantization; all integers are below 2^53.
  const horizontal = new Int32Array(sh * rw);
  for (let r = 0; r < sh; r++) horizontalRow(m, (y0 + r) * source.width + x0, columns, horizontal, r * rw, rw);
  const result = new Uint8Array(16384), denominator = sw * sh, numerators = new Float64Array(rw);
  for (let k = 0; k < rh; k++) {
    verticalRow(horizontal, rows, k, rw, numerators);
    for (let j = 0; j < rw; j++) {
      let numerator = numerators[j];
      if (invert) numerator = 255 * denominator - numerator;
      const quotient = Math.floor(numerator / denominator);
      const code = quotient + (2 * (numerator - quotient * denominator) >= denominator ? 1 : 0);
      result[(oy + k) * 128 + ox + j] = binary ? (code >= 128 ? 255 : 0) : code;
    }
  }
  return result;
}
