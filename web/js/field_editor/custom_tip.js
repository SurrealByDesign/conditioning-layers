// E5 custom brush tips: a local PNG becomes the canonical tip, and the tip's stored form.
// No host imports or import-time work. The file is read and decoded here, in the browser, by
// this module's own PNG reader: no upload, server route or colour-managed image decoder.
//
// Canonical tip: width x height pixels, row by row from the top left, as two 8-bit planes.
//   luminance Y  gray images: the gray sample. Colour: ⌊(2126·R + 7152·G + 722·B + 5000) / 10000⌋,
//                the Rec. 709 weights rounded half up, in exact integers, on the samples as stored.
//   alpha     A  the alpha sample; 0 where a tRNS colour matches; otherwise 255.
// 16-bit samples become ⌊(v + 128) / 257⌋, the nearest code (never a tie); 1-, 2- and 4-bit
// samples scale exactly by 255, 85 and 17. Colour management (gAMA, cHRM, sRGB, iCCP) and other
// ancillary chunks are ignored. Equivalent encodings of the same pixels give the same tip.
// Stored form (brush setting custom_tip): a data URL of a gray+alpha 8-bit PNG of exactly the
// two planes. Reading a tip into a footprint mask is the brush's job (brush.js tipMask).

export const TIP_PREFIX = "data:image/png;base64,";
// Import bounds: file bytes, pixels per side, pixels in all, and stored data URL characters. An
// oversized PNG is rejected before its image data is decompressed, never resized.
export const TIP_LIMITS = Object.freeze({fileBytes: 8388608, side: 1024, pixels: 262144, stored: 1048576});

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
const FORMATS = {0: [1, [1, 2, 4, 8, 16]], 2: [3, [8, 16]], 3: [1, [1, 2, 4, 8]], 4: [2, [8, 16]], 6: [4, [8, 16]]};
const DAMAGED = "The PNG is damaged or incomplete.";
const damaged = () => new Error(DAMAGED);

export function luma(r, g, b) {
  return Math.floor((2126 * r + 7152 * g + 722 * b + 5000) / 10000);
}

let crcTable = null;
function crc32(bytes) {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) crc = crcTable[(crc ^ bytes[i]) & 255] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function u32(bytes, at) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(at);
}
function join(parts) {
  const result = new Uint8Array(parts.reduce((n, part) => n + part.length, 0));
  let at = 0;
  for (const part of parts) { result.set(part, at); at += part.length; }
  return result;
}
function chunk(name, data) {
  const result = new Uint8Array(data.length + 12), view = new DataView(result.buffer);
  view.setUint32(0, data.length);
  result.set(Array.from(name, c => c.charCodeAt(0)), 4);
  result.set(data, 8);
  view.setUint32(data.length + 8, crc32(result.subarray(4, data.length + 8)));
  return result;
}
function paeth(left, up, corner) {
  const p = left + up - corner, a = Math.abs(p - left), b = Math.abs(p - up), c = Math.abs(p - corner);
  return a <= b && a <= c ? left : b <= c ? up : corner;
}

// Exactly size bytes of zlib-decompressed data, or an error; never more than size are kept.
async function inflate(data, size) {
  if (typeof DecompressionStream !== "function") throw new Error("This browser cannot decompress PNG image data.");
  const out = new Uint8Array(size), reader = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate")).getReader();
  let at = 0;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      if (value.length > size - at) throw damaged();
      out.set(value, at); at += value.length;
    }
  } catch {
    await reader.cancel().catch(() => {});
    throw damaged();
  } finally { reader.releaseLock(); }
  if (at !== size) throw damaged();
  return out;
}
async function deflate(bytes) {
  if (typeof CompressionStream !== "function") throw new Error("This browser cannot compress PNG image data.");
  const reader = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate")).getReader(), parts = [];
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  return join(parts);
}

function readHeader(data, limits) {
  if (data.length !== 13) throw damaged();
  const width = u32(data, 0), height = u32(data, 4), [depth, color, compression, filter, interlace] = data.subarray(8);
  if (!width || !height) throw new Error("The PNG has no pixels (zero width or height).");
  if (width > limits.side || height > limits.side || width * height > limits.pixels)
    throw new Error(limits.sizeMessage(width, height));
  if (compression || filter || interlace > 1) throw damaged();
  const format = FORMATS[color];
  if (!format || !format[1].includes(depth)) throw new Error(`Unsupported PNG format (colour type ${color}, bit depth ${depth}).`);
  if (interlace) throw new Error("Interlaced PNGs are not supported. Save the tip without interlacing.");
  return {width, height, depth, color, channels: format[0]};
}

// Stable per-format row loops share the parser and exact E5 canonical planes.
let T16 = null; // T16[v] = ⌊(v + 128) / 257⌋, the retained 16-bit rule, tabulated from the same expression
function table16() {
  if (!T16) { T16 = new Uint8Array(65536); for (let v = 0; v < 65536; v++) T16[v] = Math.floor((v + 128) / 257); }
  return T16;
}
function rowGray8(s, o, n, lum, alp, d, key) {
  for (let x = 0; x < n; x++) { const v = s[o + x]; lum[d + x] = v; const a = v === key ? 0 : 255; alp[d + x] = a; }
}
function rowGray16(s, o, n, lum, alp, d, key, t) {
  for (let x = 0; x < n; x++) { const v = s[o + 2 * x] << 8 | s[o + 2 * x + 1]; lum[d + x] = t[v]; const a = v === key ? 0 : 255; alp[d + x] = a; }
}
function rowGraySub(s, o, n, lum, alp, d, key, depth) {
  const mask = (1 << depth) - 1, scale = 255 / mask;
  for (let x = 0; x < n; x++) {
    const v = (s[o + (x * depth >> 3)] >> (8 - depth - (x * depth & 7))) & mask;
    lum[d + x] = v * scale; const a = v === key ? 0 : 255; alp[d + x] = a;
  }
}
function rowGA8(s, o, n, lum, alp, d) {
  for (let x = 0; x < n; x++) { lum[d + x] = s[o + 2 * x]; const a = s[o + 2 * x + 1]; alp[d + x] = a; }
}
function rowGA16(s, o, n, lum, alp, d, t) {
  for (let x = 0; x < n; x++) {
    const p = o + 4 * x; lum[d + x] = t[s[p] << 8 | s[p + 1]]; const a = t[s[p + 2] << 8 | s[p + 3]]; alp[d + x] = a;
  }
}
function rowRGB8(s, o, n, lum, alp, d, kr, kg, kb) {
  for (let x = 0; x < n; x++) {
    const p = o + 3 * x, r = s[p], g = s[p + 1], b = s[p + 2];
    lum[d + x] = Math.floor((2126 * r + 7152 * g + 722 * b + 5000) / 10000);
    const a = r === kr && g === kg && b === kb ? 0 : 255; alp[d + x] = a;
  }
}
function rowRGB16(s, o, n, lum, alp, d, kr, kg, kb, t) {
  for (let x = 0; x < n; x++) {
    const p = o + 6 * x, R = s[p] << 8 | s[p + 1], G = s[p + 2] << 8 | s[p + 3], B = s[p + 4] << 8 | s[p + 5];
    lum[d + x] = Math.floor((2126 * t[R] + 7152 * t[G] + 722 * t[B] + 5000) / 10000);
    const a = R === kr && G === kg && B === kb ? 0 : 255; alp[d + x] = a;
  }
}
function rowRGBA8(s, o, n, lum, alp, d) {
  for (let x = 0; x < n; x++) {
    const p = o + 4 * x;
    lum[d + x] = Math.floor((2126 * s[p] + 7152 * s[p + 1] + 722 * s[p + 2] + 5000) / 10000);
    const a = s[p + 3]; alp[d + x] = a;
  }
}
function rowRGBA16(s, o, n, lum, alp, d, t) {
  for (let x = 0; x < n; x++) {
    const p = o + 8 * x;
    lum[d + x] = Math.floor((2126 * t[s[p] << 8 | s[p + 1]] + 7152 * t[s[p + 2] << 8 | s[p + 3]] + 722 * t[s[p + 4] << 8 | s[p + 5]] + 5000) / 10000);
    const a = t[s[p + 6] << 8 | s[p + 7]]; alp[d + x] = a;
  }
}
function rowPalette(s, o, n, lum, alp, d, depth, pl, pa, count) {
  const mask = (1 << depth) - 1;
  for (let x = 0; x < n; x++) {
    const index = depth === 8 ? s[o + x] : (s[o + (x * depth >> 3)] >> (8 - depth - (x * depth & 7))) & mask;
    if (index >= count) throw damaged();
    lum[d + x] = pl[index]; const a = pa[index]; alp[d + x] = a;
  }
}
// One plan per image; a per-row switch keeps every per-pixel loop monomorphic.
function conversionPlan(color, depth, palette, transparency) {
  // Compare tRNS keys on raw samples, before canonical conversion.
  const key = transparency && color !== 3 ? Array.from(transparency.length === 2 ? [0] : [0, 1, 2],
    c => transparency[2 * c] << 8 | transparency[2 * c + 1]) : null;
  const plan = {kind: 0, depth, k0: -1, k1: -1, k2: -1, t: depth === 16 ? table16() : null, pl: null, pa: null, count: 0};
  if (key) { plan.k0 = key[0]; if (key.length === 3) { plan.k1 = key[1]; plan.k2 = key[2]; } }
  if (color === 3) {
    plan.kind = 9; plan.count = palette.length / 3; plan.pl = new Uint8Array(256); plan.pa = new Uint8Array(256);
    for (let i = 0; i < plan.count; i++) {
      plan.pl[i] = luma(palette[3 * i], palette[3 * i + 1], palette[3 * i + 2]);
      plan.pa[i] = transparency && i < transparency.length ? transparency[i] : 255;
    }
  } else if (color === 0) plan.kind = depth === 8 ? 0 : depth === 16 ? 1 : 2;
  else if (color === 4) plan.kind = depth === 8 ? 3 : 4;
  else if (color === 2) plan.kind = depth === 8 ? 5 : 6;
  else plan.kind = depth === 8 ? 7 : 8;
  return plan;
}
function convertRow(p, s, o, n, lum, alp, d) {
  switch (p.kind) {
    case 0: return rowGray8(s, o, n, lum, alp, d, p.k0);
    case 1: return rowGray16(s, o, n, lum, alp, d, p.k0, p.t);
    case 2: return rowGraySub(s, o, n, lum, alp, d, p.k0, p.depth);
    case 3: return rowGA8(s, o, n, lum, alp, d);
    case 4: return rowGA16(s, o, n, lum, alp, d, p.t);
    case 5: return rowRGB8(s, o, n, lum, alp, d, p.k0, p.k1, p.k2);
    case 6: return rowRGB16(s, o, n, lum, alp, d, p.k0, p.k1, p.k2, p.t);
    case 7: return rowRGBA8(s, o, n, lum, alp, d);
    case 8: return rowRGBA16(s, o, n, lum, alp, d, p.t);
    default: return rowPalette(s, o, n, lum, alp, d, p.depth, p.pl, p.pa, p.count);
  }
}

// Two alternating row buffers; the previous row is zero before the first row.
// Uint8Array assignment supplies PNG unsigned-byte wrap at every bpp boundary.
function unfilterRow(raw, from, filter, out, prior, rowBytes, bpp, first) {
  if (filter > 4) throw damaged();
  if (first && filter === 2) filter = 0;
  if (first && filter === 4) filter = 1;
  if (filter === 0) out.set(raw.subarray(from, from + rowBytes));
  else if (filter === 1) {
    out.set(raw.subarray(from, from + bpp));
    for (let x = bpp; x < rowBytes; x++) out[x] = raw[from + x] + out[x - bpp];
  } else if (filter === 2) {
    for (let x = 0; x < rowBytes; x++) out[x] = raw[from + x] + prior[x];
  } else if (filter === 3) {
    for (let x = 0; x < rowBytes; x++) {
      const left = x >= bpp ? out[x - bpp] : 0, up = first ? 0 : prior[x];
      out[x] = raw[from + x] + ((left + up) >> 1);
    }
  } else {
    for (let x = 0; x < bpp; x++) out[x] = raw[from + x] + prior[x];
    for (let x = bpp; x < rowBytes; x++) {
      const left = out[x - bpp], up = prior[x], corner = prior[x - bpp];
      const p = left + up - corner, a = Math.abs(p - left), b = Math.abs(p - up), c = Math.abs(p - corner);
      out[x] = raw[from + x] + (a <= b && a <= c ? left : b <= c ? up : corner);
    }
  }
}

// The canonical tip of a PNG file's bytes, or an error naming what is wrong.
export async function decodeTipPng(bytes) {
  return decodePngPlanes(bytes, {...TIP_LIMITS,
    fileMessage: "PNG files for custom tips may be at most 8,388,608 bytes.",
    sizeMessage: (width, height) => `Custom tips may be at most 1,024 pixels a side and 262,144 pixels in all; this PNG is ${width}×${height}.`});
}

export async function decodePngPlanes(bytes, limits) {
  if (!(bytes instanceof Uint8Array)) throw new Error("Expected PNG file bytes.");
  if (bytes.length > limits.fileBytes) throw new Error(limits.fileMessage);
  if (bytes.length < 8 || SIGNATURE.some((v, i) => bytes[i] !== v)) throw new Error("Not a PNG file.");
  let at = 8, header = null, palette = null, transparency = null, ended = false;
  const parts = [];
  for (;;) {
    if (bytes.length - at < 12) throw damaged();
    const length = u32(bytes, at), end = at + 12 + length;
    if (length > 0x7fffffff || end > bytes.length) throw damaged();
    const name = String.fromCharCode(...bytes.subarray(at + 4, at + 8));
    if (!/^[A-Za-z]{2}[A-Z][A-Za-z]$/.test(name) || u32(bytes, end - 4) !== crc32(bytes.subarray(at + 4, end - 4))) throw damaged();
    const data = bytes.subarray(at + 8, end - 4);
    at = end;
    if (!header !== (name === "IHDR")) throw damaged(); // IHDR first, and only once
    if (name === "IDAT") {
      if (ended) throw damaged(); // image data chunks are consecutive
      parts.push(data); continue;
    }
    if (parts.length) ended = true;
    if (name === "IHDR") header = readHeader(data, limits);
    else if (name === "IEND") {
      if (length || !parts.length) throw damaged();
      break;
    } else if (name === "PLTE") {
      if (palette || parts.length || header.color === 0 || header.color === 4 || !length || length % 3) throw damaged();
      palette = data;
    } else if (name === "tRNS") {
      const size = {0: 2, 2: 6}[header.color] ?? (header.color === 3 && palette ? palette.length / 3 : 0);
      if (transparency || parts.length || !length || length > size || (header.color !== 3 && length !== size)) throw damaged();
      transparency = data;
    } else if (["acTL", "fcTL", "fdAT"].includes(name)) throw new Error("Animated PNGs are not supported.");
    else if (name === "eXIf") throw new Error("PNGs with orientation metadata (eXIf) are not supported.");
    else if (!(name.charCodeAt(0) & 32)) throw new Error(`Unsupported PNG chunk ${name}.`);
  }
  if (at !== bytes.length) throw damaged();
  const {width, height, depth, color, channels} = header, bits = depth * channels;
  if (color === 3 && (!palette || palette.length / 3 > 1 << depth)) throw damaged();
  const rowBytes = Math.ceil(width * bits / 8);
  const raw = await inflate(join(parts), height * (rowBytes + 1)), bpp = Math.max(1, bits >> 3);
  const luminance = new Uint8Array(width * height), alpha = new Uint8Array(width * height);
  const plan = conversionPlan(color, depth, palette, transparency);
  let out = new Uint8Array(rowBytes), prior = new Uint8Array(rowBytes);
  for (let y = 0; y < height; y++) {
    unfilterRow(raw, y * (rowBytes + 1) + 1, raw[y * (rowBytes + 1)], out, prior, rowBytes, bpp, y === 0);
    convertRow(plan, out, 0, width, luminance, alpha, y * width);
    const swap = out; out = prior; prior = swap;
  }
  return Object.freeze({width, height, luminance, alpha});
}

function validTip(tip) {
  const n = tip?.width * tip?.height;
  return Number.isInteger(tip?.width) && Number.isInteger(tip?.height) && tip.width >= 1 && tip.height >= 1
    && tip.width <= TIP_LIMITS.side && tip.height <= TIP_LIMITS.side && n <= TIP_LIMITS.pixels
    && tip.luminance instanceof Uint8Array && tip.alpha instanceof Uint8Array
    && tip.luminance.length === n && tip.alpha.length === n;
}

export function sameTip(a, b) {
  return validTip(a) && validTip(b) && a.width === b.width && a.height === b.height
    && a.luminance.every((v, i) => v === b.luminance[i]) && a.alpha.every((v, i) => v === b.alpha[i]);
}

// The stored PNG: gray+alpha, 8-bit, non-interlaced, Paeth-filtered rows, one IDAT. The same
// planes give the same bytes in a given browser; identity is the planes, never the bytes.
export async function encodeTipPng(tip) {
  if (!validTip(tip)) throw new Error("Invalid custom tip.");
  const {width, height, luminance, alpha} = tip, rowBytes = 2 * width;
  const raw = new Uint8Array(height * (rowBytes + 1));
  let prior = new Uint8Array(rowBytes), current = new Uint8Array(rowBytes);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) { current[2 * x] = luminance[y * width + x]; current[2 * x + 1] = alpha[y * width + x]; }
    const at = y * (rowBytes + 1);
    raw[at] = 4;
    for (let k = 0; k < rowBytes; k++)
      raw[at + 1 + k] = (current[k] - paeth(k >= 2 ? current[k - 2] : 0, prior[k], k >= 2 ? prior[k - 2] : 0)) & 255;
    [prior, current] = [current, prior];
  }
  const header = new Uint8Array(13), view = new DataView(header.buffer);
  view.setUint32(0, width); view.setUint32(4, height); header[8] = 8; header[9] = 4;
  return join([new Uint8Array(SIGNATURE), chunk("IHDR", header), chunk("IDAT", await deflate(raw)), chunk("IEND", new Uint8Array())]);
}

export async function encodeTipDataUrl(tip) {
  const bytes = await encodeTipPng(tip);
  let text = "";
  for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return TIP_PREFIX + btoa(text);
}

// A stored custom_tip that may be kept: a bounded PNG data URL in strict, padded base64. Its PNG
// is checked only when it is decoded; an unreadable one is reported and kept, never dropped.
export function storedTipValid(text) {
  return typeof text === "string" && text.length > TIP_PREFIX.length && text.length <= TIP_LIMITS.stored
    && text.startsWith(TIP_PREFIX) && (text.length - TIP_PREFIX.length) % 4 === 0
    && /^[A-Za-z0-9+/]*={0,2}$/.test(text.slice(TIP_PREFIX.length));
}

export async function decodeTipDataUrl(text) {
  if (!storedTipValid(text)) throw new Error("The stored custom tip is not a PNG data URL.");
  const binary = atob(text.slice(TIP_PREFIX.length)), bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return decodeTipPng(bytes);
}

// Import a local PNG file: bound its size before reading it, decode it, then store and re-read
// the canonical PNG, so the session paints with exactly what a reopened workflow restores. The
// file's name and path are never read.
export async function importTipFile(file) {
  if (!(file?.size <= TIP_LIMITS.fileBytes)) throw new Error("PNG files for custom tips may be at most 8,388,608 bytes.");
  const source = await decodeTipPng(new Uint8Array(await file.arrayBuffer()));
  const value = await encodeTipDataUrl(source);
  if (value.length > TIP_LIMITS.stored) throw new Error("This tip is too large to keep with the node.");
  const tip = await decodeTipDataUrl(value);
  if (!sameTip(tip, source)) throw new Error("The custom tip could not be stored exactly.");
  return {tip, value};
}
