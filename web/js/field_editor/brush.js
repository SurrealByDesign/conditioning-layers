import {PARTICLE_SHAPES, PROCEDURAL_TYPES, PROCEDURAL_VERSION, proceduralTip} from "./procedural_tip.js";
import {sampleTip} from "./tip_sampling.js";
export {sampleTip} from "./tip_sampling.js";
// Brush footprints, built-in shapes, E5 custom and E7 procedural tips, their non-destructive transforms and
// per-cell coverage. No host imports or import-time work. The footprint decides where and how
// strongly a stamp covers cells; the value painted is the value profile's (value_profile.js).
//
// Shape frame: a built-in shape spans the source square [-1,1]^2 (x right, y down); a custom
// tip spans its mask, w x h pixels (tipMask), so a crop percentage is of w or h.
// Order: crop -> mirror (about the crop centre) -> scale (fit the cropped area's longer
// side to Size, then Scale X/Y) -> rotate clockwise -> place the crop centre at the stamp.
// A custom tip is read, inverted and trimmed before all of these.
// Coverage maps each destination cell centre back through that order. Quarter turns are
// exact; any other angle uses Math.sin/Math.cos once, when the footprint is prepared.

export const SHAPES = ["disk", "square", "diamond", "custom", "procedural"];
export const VALUE_PROFILES = ["uniform", "linear", "radial", "square"];
export const TIP_CHANNELS = ["alpha", "luminance", "alpha_luminance"];

// Coverage edge for Hardness < 100. s is 0 at the footprint edge and 1 at the Hardness
// boundary; every curve is 0 at s=0, 1 at s=1, and 1/2 at s=1/2.
export const FALLOFF_CURVES = {
  smooth: s => s * s * (3 - 2 * s), // E1 smoothstep, the default
  linear: s => s,
  sharper: s => s * s * s * (s * (s * 6 - 15) + 10), // quintic smootherstep
};

// E3–E9 brush settings, stroke dynamics and their defaults. Missing keys mean the default, so E1 brushes
// are unchanged. The gradient_* settings act only while value_profile is not "uniform", and the
// tip_* settings (how a custom tip is read) only while shape is "custom". The tip itself is no
// setting here: the editor keeps it as custom_tip and gives the engine the decoded tip as tip.
export const BRUSH_DEFAULTS = Object.freeze({
  shape: "disk", scale_x: 1, scale_y: 1, rotation_degrees: 0,
  mirror_horizontal: false, mirror_vertical: false,
  crop_left: 0, crop_right: 0, crop_top: 0, crop_bottom: 0, falloff_curve: "smooth",
  build_up: false, flow: 25, spacing: "auto", spacing_percent: 25, apply_mode: "normal",
  value_profile: "uniform", gradient_start: 255, gradient_end: 0, gradient_curve: 1,
  gradient_angle: 0, gradient_start_position: 0, gradient_end_position: 100,
  gradient_center_x: 50, gradient_center_y: 50, gradient_inner: 0, gradient_outer: 100,
  gradient_aspect_x: 1, gradient_aspect_y: 1, gradient_rotation: 0,
  tip_channel: "alpha", tip_invert: false, tip_trim: false,
  procedural_version: PROCEDURAL_VERSION, procedural_type: "scatter", procedural_seed: 0, procedural_invert: false,
  procedural_particle_shape: "circle", procedural_grid: 6, procedural_density: 50, procedural_particle_size: 60,
  procedural_particle_aspect: 1, procedural_size_jitter: 25, procedural_position_jitter: 75,
  procedural_particle_rotation: 0, procedural_rotation_jitter: 0, procedural_frequency: 4, procedural_octaves: 3,
  procedural_persistence: 50, procedural_noise_low: 30, procedural_noise_high: 70,
  hotdog_count: 1, hotdog_spread: 100, hotdog_invert: false,
  // Stroke dynamics: smoothing reshapes the pointer path (stroke_smoothing.js); pressure_min_size
  // is pen pressure's smallest stamp, as a percentage of Size; angle_jitter turns each stamp by up
  // to ± that many degrees, size_jitter resizes it and amount_jitter changes its Amount by up to ±
  // that percentage (angle_jitter.js). 0 keeps each one's earlier behavior. A nonzero jitter_seed
  // rerolls every jitter sequence; 0 keeps the earlier ones. flow_jitter changes a Build-up stamp's
  // Flow by up to ± that percentage. scatter moves each stamp up to that percentage of its size.
  // follow_direction adds the stroke's direction of travel to each stamp's Rotation.
  smoothing: 0, pressure_min_size: 0, angle_jitter: 0, size_jitter: 0, amount_jitter: 0, jitter_seed: 0, flow_jitter: 0, scatter: 0,
  follow_direction: false,
  pressure_enabled: false, pressure_size: true, pressure_amount: false, pressure_flow: false,
});
// The pressure mappings that version 2 brush presets require. Minimum Size is an optional preset key.
export const PRESSURE_KEYS = Object.freeze(["pressure_enabled", "pressure_size", "pressure_amount", "pressure_flow"]);
export const PROCEDURAL_KEYS = Object.freeze(Object.keys(BRUSH_DEFAULTS).filter(key => key.startsWith("procedural_")));
export const PROCEDURAL_EMPTY = "This procedural tip is empty: every value is 0. Raise Density or Particle Size, widen Noise Low to Noise High, or turn off Invert Procedural Tip.";
export function proceduralError(settings) {
  return settings.procedural_noise_low >= settings.procedural_noise_high ? "Noise Low must stay below Noise High." : "";
}
export function proceduralMask(brush) { return proceduralTip(resolveBrush(brush)); }

const integer = (low, high) => v => Number.isInteger(v) && v >= low && v <= high;
const number = (low, high) => v => typeof v === "number" && v >= low && v <= high;
const oneOf = (...choices) => v => choices.includes(v);
const flag = v => typeof v === "boolean";
const RULES = {
  shape: oneOf(...SHAPES), scale_x: number(0.1, 10), scale_y: number(0.1, 10),
  rotation_degrees: number(-360, 360), mirror_horizontal: flag, mirror_vertical: flag,
  crop_left: integer(0, 99), crop_right: integer(0, 99), crop_top: integer(0, 99), crop_bottom: integer(0, 99),
  falloff_curve: oneOf(...Object.keys(FALLOFF_CURVES)), build_up: flag, flow: integer(1, 100),
  spacing: oneOf("auto", "custom"), spacing_percent: integer(1, 1000),
  apply_mode: oneOf("normal", "raise_only", "lower_only"),
  value_profile: oneOf(...VALUE_PROFILES), gradient_start: integer(0, 255), gradient_end: integer(0, 255),
  gradient_curve: number(0.1, 10), gradient_angle: number(-360, 360),
  gradient_start_position: integer(0, 100), gradient_end_position: integer(0, 100),
  gradient_center_x: integer(0, 100), gradient_center_y: integer(0, 100),
  gradient_inner: integer(0, 300), gradient_outer: integer(0, 300),
  gradient_aspect_x: number(0.1, 10), gradient_aspect_y: number(0.1, 10), gradient_rotation: number(-360, 360),
  tip_channel: oneOf(...TIP_CHANNELS), tip_invert: flag, tip_trim: flag,
  procedural_version: oneOf(PROCEDURAL_VERSION), procedural_type: oneOf(...PROCEDURAL_TYPES),
  procedural_seed: integer(0, 4294967295), procedural_invert: flag, procedural_particle_shape: oneOf(...PARTICLE_SHAPES),
  procedural_grid: integer(1, 32), procedural_density: integer(0, 100), procedural_particle_size: integer(1, 200),
  procedural_particle_aspect: number(0.1, 10), procedural_size_jitter: integer(0, 90), procedural_position_jitter: integer(0, 100),
  procedural_particle_rotation: number(-360, 360), procedural_rotation_jitter: number(0, 180),
  procedural_frequency: integer(1, 16), procedural_octaves: integer(1, 4), procedural_persistence: integer(0, 100),
  procedural_noise_low: integer(0, 100), procedural_noise_high: integer(0, 100),
  hotdog_count: integer(1, 1024), hotdog_spread: integer(0, 100), hotdog_invert: flag,
  smoothing: integer(0, 100), pressure_min_size: integer(0, 100), angle_jitter: integer(0, 180), size_jitter: integer(0, 100), amount_jitter: integer(0, 100),
  jitter_seed: integer(0, 4294967295), flow_jitter: integer(0, 100), scatter: integer(0, 200), follow_direction: flag,
  pressure_enabled: flag, pressure_size: flag, pressure_amount: flag, pressure_flow: flag,
};

export function validBrushSetting(key, value) { return RULES[key](value); }

export function cropError(settings) {
  if (settings.crop_left + settings.crop_right >= 100) return "Crop Left + Crop Right must stay below 100%.";
  if (settings.crop_top + settings.crop_bottom >= 100) return "Crop Top + Crop Bottom must stay below 100%.";
  return "";
}

// A gradient's transition needs room, as Field Fade's: Start before End, Inner inside Outer.
export function profileError(settings) {
  if (settings.gradient_start_position >= settings.gradient_end_position)
    return "Start Position must stay below End Position.";
  if (settings.gradient_inner >= settings.gradient_outer) return "Inner must stay below Outer.";
  return "";
}

// Validated E3/E4 settings. Invalid values, crops that leave no area and empty gradient
// transitions throw; nothing is normalized.
export function resolveBrush(brush) {
  const result = {};
  for (const [key, fallback] of Object.entries(BRUSH_DEFAULTS)) {
    const value = brush[key] === undefined ? fallback : brush[key];
    if (!RULES[key](value)) throw new Error(`Invalid brush ${key}`);
    result[key] = value;
  }
  const error = cropError(result) || profileError(result) || proceduralError(result);
  if (error) throw new Error(error);
  return result;
}

function nearest(value) {
  const floor = Math.floor(value);
  return floor + (value - floor >= 0.5 ? 1 : 0);
}

// E5: a custom tip's mask. The tip is its canonical source (custom_tip.js): width x height codes
// of luminance Y and alpha A. Reading it gives one code m per pixel, 255 full coverage, 0 none:
//   alpha m = A;  luminance m = Y;  alpha_luminance m = ⌊(A·Y + 127) / 255⌋, which is A·Y/255
//   rounded to the nearest code (never a tie). Then Invert Tip: m = 255 − m. Then Trim: keep the
//   smallest rectangle holding every m > 0.
// Masks are kept per tip object, so a replaced or cleared tip never leaves a stale entry.
const MASKS = new WeakMap();

function tipValid(tip) {
  const n = tip?.width * tip?.height;
  return Number.isInteger(tip?.width) && Number.isInteger(tip?.height) && tip.width >= 1 && tip.height >= 1
    && tip.luminance instanceof Uint8Array && tip.alpha instanceof Uint8Array
    && tip.luminance.length === n && tip.alpha.length === n;
}

function readTip({width, height, luminance, alpha}, channel, invert, trim) {
  const codes = new Uint8Array(width * height);
  let left = width, right = -1, top = -1, bottom = -1;
  for (let y = 0, i = 0; y < height; y++) {
    for (let x = 0; x < width; x++, i++) {
      let m = channel === "alpha" ? alpha[i] : channel === "luminance" ? luminance[i]
        : Math.floor((alpha[i] * luminance[i] + 127) / 255);
      if (invert) m = 255 - m;
      codes[i] = m;
      if (m > 0) {
        if (x < left) left = x;
        if (x > right) right = x;
        if (top < 0) top = y;
        bottom = y;
      }
    }
  }
  const empty = right < 0, w = right - left + 1, h = bottom - top + 1;
  if (empty || !trim || (w === width && h === height))
    return Object.freeze({codes, width, height, left: 0, top: 0, sourceWidth: width, sourceHeight: height, empty});
  const trimmed = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) trimmed.set(codes.subarray((top + y) * width + left, (top + y) * width + left + w), y * w);
  return Object.freeze({codes: trimmed, width: w, height: h, left, top, sourceWidth: width, sourceHeight: height, empty});
}

// The mask of a tip read with these settings: {codes, width, height, left, top, sourceWidth,
// sourceHeight, empty}; left and top place a trimmed mask in the tip.
export function tipMask(tip, channel, invert, trim) {
  if (!tipValid(tip) || !TIP_CHANNELS.includes(channel) || typeof invert !== "boolean" || typeof trim !== "boolean")
    throw new Error("Invalid custom tip");
  let masks = MASKS.get(tip);
  if (!masks) MASKS.set(tip, masks = new Map());
  const key = `${channel} ${invert} ${trim}`;
  let mask = masks.get(key);
  if (!mask) masks.set(key, mask = readTip(tip, channel, invert, trim));
  return mask;
}

function customMask(tip, b) {
  if (tip === undefined || tip === null) throw new Error("No custom tip is loaded. Import a PNG under Custom Tip.");
  const mask = tipMask(tip, b.tip_channel, b.tip_invert, b.tip_trim);
  if (mask.empty) throw new Error("This custom tip is empty as read: every value is 0. Choose another channel or Invert Tip.");
  return mask;
}

// Bilinear in code space. Mask pixel (i, j) has its centre at (i + 1/2, j + 1/2), in pixels from
// the mask's top left corner. Each neighbour index is clamped to the mask, so inside the mask
// rectangle an edge pixel's code holds out to the edge and a solid tip covers its whole rectangle;
// outside it, localCoverage has already returned 0. At a pixel centre this is its code exactly.

// Everything a stamp needs, computed once per brush change. Lengths are in field cells.
export function prepareFootprint(brush) {
  const b = resolveBrush(brush), {size, hardness} = brush;
  // A custom tip's frame is its mask, w x h pixels; a built-in shape's is one square, w = h = 1.
  const mask = b.shape === "procedural" ? proceduralTip(b) : b.shape === "custom" ? customMask(brush.tip, b) : null;
  if (b.shape === "procedural" && mask.empty) throw new Error(PROCEDURAL_EMPTY);
  const w = mask ? mask.width : 1, h = mask ? mask.height : 1;
  const width = (100 - b.crop_left - b.crop_right) * w, height = (100 - b.crop_top - b.crop_bottom) * h;
  const fit = Math.max(width, height); // the cropped area's longer side becomes Size
  const radius = 50 * size / fit; // half the uncropped shape, in cells
  const f = {
    hard: hardness === 100, shape: b.shape, curve: FALLOFF_CURVES[b.falloff_curve],
    // A custom tip's Hardness acts on reach across its frame, which is 1 at the frame's edge.
    radius: mask ? 1 : radius, inner: mask ? hardness / 100 : hardness / 100 * radius,
    // Crop rectangle centre (the anchor) and half extents, in cells from the shape centre.
    centerX: (b.crop_left - b.crop_right) * w * size / (2 * fit),
    centerY: (b.crop_top - b.crop_bottom) * h * size / (2 * fit),
    halfX: width * size / (2 * fit), halfY: height * size / (2 * fit),
    scaleX: b.scale_x, scaleY: b.scale_y, mirrorX: b.mirror_horizontal, mirrorY: b.mirror_vertical,
    quarter: null, cos: 0, sin: 0,
  };
  // A custom tip adds its mask, the half extents of its uncropped frame in cells and mask pixels
  // per cell. Built-in footprints keep E4's fields only, which keeps their strokes as fast.
  if (mask) Object.assign(f, {mask, radiusX: 50 * w * size / fit, radiusY: 50 * h * size / fit, pixelsPerCell: fit / (100 * size)});
  const angle = (b.rotation_degrees % 360 + 360) % 360;
  if (angle % 90 === 0) f.quarter = angle / 90;
  else {
    const radians = angle * (Math.PI / 180);
    f.cos = Math.cos(radians); f.sin = Math.sin(radians);
  }
  const ax = f.halfX * f.scaleX, ay = f.halfY * f.scaleY;
  // Half extents of the transformed crop rectangle around the anchor: the stamp's loop bounds.
  f.extent = f.quarter === null
    ? [Math.abs(f.cos) * ax + Math.abs(f.sin) * ay, Math.abs(f.sin) * ax + Math.abs(f.cos) * ay]
    : f.quarter % 2 ? [ay, ax] : [ax, ay];
  // Hard stamps snap per axis by the parity of the frame's whole-cell extent, taken at the
  // nearest quarter turn. E1's disk gets its Size-parity rule; an equal-scale disk never
  // changes parity with rotation.
  const turn = f.quarter ?? Math.floor(angle / 90 + 0.5) % 4;
  const [px, py] = turn % 2 ? [ay, ax] : [ax, ay];
  f.oddX = nearest(2 * px) % 2 === 1; f.oddY = nearest(2 * py) % 2 === 1;
  return f;
}

export function snapAnchor(f, x, y) {
  return [f.oddX ? Math.floor(x) + 0.5 : Math.floor(x + 0.5),
    f.oddY ? Math.floor(y) + 0.5 : Math.floor(y + 0.5)];
}

function falloff(f, distance) {
  if (distance <= f.inner) return 1;
  if (distance >= f.radius) return 0;
  return f.curve((f.radius - distance) / (f.radius - f.inner));
}

// Brush-local position of the cell centre at (dx, dy) cells from the stamp anchor, written to
// out: rotation, scale and mirror undone, in cells from the crop centre. Coverage and the
// value profile both read this one mapping, so a profile moves with the brush.
export function footprintLocal(f, dx, dy, out) {
  let x, y;
  switch (f.quarter) { // undo the clockwise rotation
    case 0: x = dx; y = dy; break;
    case 1: x = dy; y = -dx; break;
    case 2: x = -dx; y = -dy; break;
    case 3: x = -dy; y = dx; break;
    default: x = f.cos * dx + f.sin * dy; y = -f.sin * dx + f.cos * dy;
  }
  x /= f.scaleX; y /= f.scaleY;
  if (f.mirrorX) x = -x;
  if (f.mirrorY) y = -y;
  out[0] = x; out[1] = y;
  return out;
}

// A custom tip's coverage at (u, v), in cells from its frame's centre: the mask sampled there, as
// code / 255. Below Hardness 100 that is multiplied by the falloff of reach, the larger of |u| and
// |v| as fractions of the frame's half extents (1 at the frame's edge). Hardness fades the tip's
// outer envelope only; it never blurs or remaps the codes inside it.
function tipCoverage(f, u, v) {
  const m = f.mask, code = sampleTip(m, m.width / 2 + u * f.pixelsPerCell, m.height / 2 + v * f.pixelsPerCell);
  if (f.hard) return code / 255;
  return code / 255 * falloff(f, Math.max(Math.abs(u) / f.radiusX, Math.abs(v) / f.radiusY));
}

// Coverage 0..1 at brush-local (x, y), in cells from the crop centre.
export function localCoverage(f, x, y) {
  if (x < -f.halfX || x > f.halfX || y < -f.halfY || y > f.halfY) return 0; // closed crop rectangle
  const u = f.centerX + x, v = f.centerY + y; // cells from the shape centre
  if (f.shape === "disk") {
    const squared = u * u + v * v;
    if (f.hard) return squared <= f.radius * f.radius ? 1 : 0;
    return falloff(f, Math.sqrt(squared));
  }
  if (f.mask) return tipCoverage(f, u, v);
  const reach = f.shape === "square" ? Math.max(Math.abs(u), Math.abs(v)) : Math.abs(u) + Math.abs(v);
  if (f.hard) return reach <= f.radius ? 1 : 0;
  return falloff(f, reach);
}

// Forward map of a shape-frame point (cells from the shape centre) to an offset from the anchor.
export function footprintToCell(f, u, v) {
  let x = u - f.centerX, y = v - f.centerY;
  if (f.mirrorX) x = -x;
  if (f.mirrorY) y = -y;
  x *= f.scaleX; y *= f.scaleY;
  switch (f.quarter) {
    case 0: return [x, y];
    case 1: return [-y, x];
    case 2: return [-x, -y];
    case 3: return [y, -x];
    default: return [f.cos * x - f.sin * y, f.sin * x + f.cos * y];
  }
}
