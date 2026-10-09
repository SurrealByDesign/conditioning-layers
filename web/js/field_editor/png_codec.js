// Raw grayscale reader matching assets/png_inspector.py under ADR-0031 limits.
export const PREFIX = "data:image/png;base64,";
const FORMAT = "Expected a 128x128 non-interlaced grayscale-8 PNG (maximum 65,536 bytes).";
function fail() { throw new Error(FORMAT); }
function u32(bytes, at) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(at);
}
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const value of bytes) {
    crc ^= value;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
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
async function transform(bytes, stream, limit) {
  const reader = new Blob([bytes]).stream().pipeThrough(stream).getReader();
  const parts = []; let size = 0;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      size += value.length;
      if (size > limit) { await reader.cancel(); fail(); }
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  return join(parts);
}
export function pngDataUrl(bytes) {
  return PREFIX + btoa(String.fromCharCode(...bytes));
}
export async function decodeFieldDataUrl(text) {
  if (typeof text !== "string" || text.length > 100000) fail();
  if (text === "") return new Uint8Array(16384);
  if (!text.startsWith(PREFIX)) fail();
  const base64 = text.slice(PREFIX.length);
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(base64)) fail();
  const clean = base64.replace(/=+$/, "");
  const bytes = Uint8Array.from(atob(clean), c => c.charCodeAt(0));
  return decodeFieldPng(bytes);
}
export async function decodeFieldPng(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length > 65536 || bytes.length < 8) fail();
  if (![137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => bytes[i] === v)) fail();
  let at = 8, header = false, idat = false, ended = false, iend = false;
  const parts = [];
  while (at < bytes.length) {
    if (bytes.length - at < 12) fail();
    const length = u32(bytes, at), end = at + 12 + length;
    if (end > bytes.length) fail();
    const name = String.fromCharCode(...bytes.subarray(at + 4, at + 8));
    if (!/^[A-Za-z]{2}[A-Z][A-Za-z]$/.test(name)) fail();
    const data = bytes.subarray(at + 8, end - 4);
    if (u32(bytes, end - 4) !== crc32(bytes.subarray(at + 4, end - 4))) fail();
    if (!header && name !== "IHDR") fail();
    if (name === "IHDR") {
      if (header || length !== 13 || u32(data, 0) !== 128 || u32(data, 4) !== 128
          || ![8, 0, 0, 0, 0].every((v, i) => data[8 + i] === v)) fail();
      header = true;
    } else if (["acTL", "fcTL", "fdAT", "eXIf", "PLTE"].includes(name)) fail();
    else if (name === "IDAT") {
      if (ended) fail();
      idat = true; parts.push(data);
    } else if (name === "IEND") {
      if (length || !idat) fail();
      iend = true; at = end; break;
    } else {
      if (idat) ended = true;
      if (!(name.charCodeAt(0) & 32)) fail();
    }
    at = end;
  }
  if (!iend || at !== bytes.length) fail();
  const raw = await transform(join(parts), new DecompressionStream("deflate"), 16512);
  if (raw.length !== 16512) fail();
  const codes = new Uint8Array(16384);
  for (let y = 0; y < 128; y++) {
    const filter = raw[y * 129];
    if (filter > 4) fail();
    for (let x = 0; x < 128; x++) {
      const i = y * 128 + x, left = x ? codes[i - 1] : 0;
      const above = y ? codes[i - 128] : 0, upperLeft = x && y ? codes[i - 129] : 0;
      let predictor = 0;
      if (filter === 1) predictor = left;
      if (filter === 2) predictor = above;
      if (filter === 3) predictor = Math.floor((left + above) / 2);
      if (filter === 4) {
        const p = left + above - upperLeft, a = Math.abs(p - left);
        const b = Math.abs(p - above), c = Math.abs(p - upperLeft);
        predictor = a <= b && a <= c ? left : b <= c ? above : upperLeft;
      }
      codes[i] = (raw[y * 129 + x + 1] + predictor) & 255;
    }
  }
  return codes;
}
export async function encodeFieldPng(codes) {
  if (!(codes instanceof Uint8Array) || codes.length !== 16384) fail();
  const raw = new Uint8Array(16512);
  for (let y = 0; y < 128; y++) raw.set(codes.subarray(y * 128, (y + 1) * 128), y * 129 + 1);
  const header = new Uint8Array(13), view = new DataView(header.buffer);
  view.setUint32(0, 128); view.setUint32(4, 128); header[8] = 8;
  const compressed = await transform(raw, new CompressionStream("deflate"), 65536);
  return join([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header), chunk("IDAT", compressed), chunk("IEND", new Uint8Array())]);
}
export async function encodeFieldDataUrl(codes) {
  return codes.some(v => v !== 0) ? pngDataUrl(await encodeFieldPng(codes)) : "";
}
