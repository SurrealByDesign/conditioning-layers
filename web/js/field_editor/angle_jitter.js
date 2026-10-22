// Angle, Size, Amount and Flow Jitter: each placed stamp turns by a whole-degree offset in [-N, N]
// around the brush's Rotation, resizes by a whole-percent offset in [-S, S] of its size, changes its
// Amount by a whole-percent offset in [-A, A] of its Amount, and with Build-up its Flow by one in
// [-F, F] of its Flow. No host imports or import-time work.
// The ordinary and pressure engines stay as they are; these strokes only choose the footprint (and
// a gradient's profile) and the Amount each stamp uses. Spacing keeps the unjittered size.
// A per-stamp Amount needs the pressure stroke's per-cell Amount bookkeeping, so a mouse stroke
// with Amount Jitter runs as a pressure stroke held at full pressure, which paints exactly as the
// ordinary stroke does.
//
// Stamp k of a stroke gets offset ⌊h·(2N+1) / 2^32⌋ − N with h = hashWords([tag, x0, y0, k]),
// where (x0, y0) is the stroke's first stamp position on the 1/256-cell grid and tag selects the
// channel, so angle, size, Amount and Flow draw independent sequences. Stamps sit at fixed distances along the
// path, so the offsets depend on the path, never on how many pointer events delivered it or when.
// A nonzero Jitter Seed s rerolls all four: h = hashWords([tag, x0, y0, k, s]). Seed 0 hashes the
// four words alone, so it keeps every earlier sequence exactly. The seed never moves a stamp.
//
// Scatter moves each stamp's centre, after its base position along the path is fixed, by a point
// drawn uniformly over a disk of radius Scatter% of the stamp's size (pressure, Minimum Size and
// Size Jitter applied). Attempt a = 0, 1, … draws u, v from hashWords([tag, x0, y0, k, a(, s)]) on
// two more channels and maps each to the odd multiple (2h + 1)/2^32 − 1 in (−1, 1); the first pair
// with u² + v² ≤ 1 is kept, and after 16 misses (odds about 2·10⁻¹¹) the stamp stays unmoved. Exact
// arithmetic only, so engines agree. Spacing, the path and each stamp's pressure never see it.
// A rotation-symmetric brush (an unscaled, uncropped Disk with a Uniform or centred circular
// profile) ignores rotation, so Angle Jitter and Follow Stroke Direction leave it unturned; Size
// Jitter still applies.
//
// Follow Stroke Direction adds the direction of travel to each stamp's Rotation, before Angle
// Jitter: angle = (Rotation + jitter offset, as without it) + direction, reduced mod 360. Brush
// angles turn clockwise with x right and y down, so travel (dx, dy) has direction atan2(dy, dx):
// moving right is 0°, down 90°, left 180°, up 270°, and a tip at Rotation 0 keeps its look when
// drawn left to right; no fixed correction is added. The direction comes from base stamp positions
// only (after smoothing and spacing, before Scatter; never pressure, size, Amount or Flow): the
// chord from the anchor to this stamp, in whole degrees rounded half up into 0–359. The first stamp
// is the anchor. A chord shorter than half the path distance between consecutive stamps (spacing)
// is unreliable: the stamp keeps the last direction and the anchor stays, so tremor in place or a
// fold within one spacing cannot flip the tip. A kept chord makes its stamp the new anchor. Every
// hash sequence is unchanged.
// Stamps before the first direction (the first stamp, and any within that threshold of it) are
// held, each with its own offsets, Scatter and pressure code, and painted in order with the first
// direction once a stamp finds it. A stroke whose result is read while stamps are held (the live
// preview, or the end of a click or a still stroke) paints them at Rotation alone; the next stamp
// withdraws that provisional paint exactly before painting them with the direction.
import {Stroke, PressureStroke, PRESSURE_FULL, flowFactor, pressureMappings, roundHalf, scaledControl} from "./engine.js";
import {prepareFootprint, resolveBrush} from "./brush.js";
import {prepareProfile} from "./value_profile.js";
import {hashWords} from "./procedural_tip.js";

const TAG = 0x414e474c, SIZE_TAG = 0x53495a45, AMOUNT_TAG = 0x414d4e54, FLOW_TAG = 0x464c4f57;
const SCATTER_X_TAG = 0x53435458, SCATTER_Y_TAG = 0x53435459, SCATTER_ATTEMPTS = 16;

function rotationSymmetric(b) {
  const disk = b.shape === "disk" && b.scale_x === b.scale_y && !(b.crop_left || b.crop_right || b.crop_top || b.crop_bottom);
  const round = b.value_profile === "uniform" || (b.value_profile === "radial" && b.gradient_aspect_x === b.gradient_aspect_y
    && b.gradient_center_x === 50 && b.gradient_center_y === 50);
  return disk && round;
}

export function angleJitterActive(brush) {
  const b = resolveBrush(brush);
  return b.angle_jitter !== 0 && !rotationSymmetric(b);
}

export function followDirectionActive(brush) {
  const b = resolveBrush(brush);
  return b.follow_direction && !rotationSymmetric(b);
}

// Flow has meaning only with Build-up, so Flow Jitter acts only there.
export function flowJitterRange(brush) { const b = resolveBrush(brush); return b.build_up ? b.flow_jitter : 0; }

// Whether a stroke needs per-stamp jitter at all.
export function stampJitterActive(brush) {
  const b = resolveBrush(brush);
  return b.size_jitter > 0 || b.amount_jitter > 0 || flowJitterRange(brush) > 0 || b.scatter > 0 || angleJitterActive(brush) || followDirectionActive(brush);
}

function offset(tag, range, x0, y0, k, seed) {
  const words = seed === 0 ? [tag, x0 >>> 0, y0 >>> 0, k] : [tag, x0 >>> 0, y0 >>> 0, k, seed];
  return Math.floor(hashWords(words) * (2 * range + 1) / 4294967296) - range;
}

// The offset in whole degrees of stamp k for a stroke starting at (x0, y0) in 1/256 cells.
export function jitterOffset(range, x0, y0, k, seed = 0) { return offset(TAG, range, x0, y0, k, seed); }

// The offset in whole percent of stamp k's size, drawn as jitterOffset on its own channel.
export function sizeJitterOffset(range, x0, y0, k, seed = 0) { return offset(SIZE_TAG, range, x0, y0, k, seed); }

// The offset in whole percent of stamp k's Amount, drawn as jitterOffset on its own channel.
export function amountJitterOffset(range, x0, y0, k, seed = 0) { return offset(AMOUNT_TAG, range, x0, y0, k, seed); }

// The offset in whole percent of stamp k's Flow, drawn as jitterOffset on its own channel.
export function flowJitterOffset(range, x0, y0, k, seed = 0) { return offset(FLOW_TAG, range, x0, y0, k, seed); }

// Stamp k's Scatter offset [dx, dy] in cells for a stamp of size cells, within scatter% of size.
export function scatterOffset(scatter, size, x0, y0, k, seed = 0) {
  const reach = scatter * size / 100;
  for (let a = 0; a < SCATTER_ATTEMPTS; a++) {
    const words = seed === 0 ? [0, x0 >>> 0, y0 >>> 0, k, a] : [0, x0 >>> 0, y0 >>> 0, k, a, seed];
    words[0] = SCATTER_X_TAG; const u = (2 * hashWords(words) + 1) / 4294967296 - 1;
    words[0] = SCATTER_Y_TAG; const v = (2 * hashWords(words) + 1) / 4294967296 - 1;
    if (u * u + v * v <= 1) return [reach * u, reach * v];
  }
  return [0, 0];
}

// A Flow changed by percent, rounded half up and kept within Flow's 1–100.
export function jitteredFlow(flow, percent) { return jitteredAmount(flow, percent); }

// An Amount changed by percent, rounded half up and kept within Amount's 1–100.
export function jitteredAmount(amount, percent) {
  return Math.min(100, Math.max(1, Math.floor((amount * (100 + percent) + 50) / 100)));
}

// The brush's Rotation turned by offset, kept within the setting's ±360°.
export function jitteredRotation(base, offset) {
  const angle = base + offset;
  return angle > 360 ? angle - 360 : angle < -360 ? angle + 360 : angle;
}

// The whole-degree direction, 0–359, of travel (dx, dy) cells, or null when the chord is shorter
// than half of gap cells.
export function strokeDirection(dx, dy, gap) {
  if (4 * (dx * dx + dy * dy) < gap * gap) return null;
  const degrees = roundHalf(Math.atan2(dy, dx) * 180 / Math.PI);
  return degrees < 0 ? degrees + 360 : degrees;
}

// A stamp's Rotation (Angle Jitter applied) turned by its stroke direction, within ±360°.
export function followedRotation(rotation, direction) { return (rotation + direction) % 360; }

// The direction of the base stamp at (x, y) cells, gap cells along the path from the one before.
function followed(j, x, y, gap) {
  if (!j.follow) return null;
  if (j.at === null) { j.at = [x, y]; return null; }
  const direction = strokeDirection(x - j.at[0], y - j.at[1], gap);
  if (direction !== null) { j.direction = direction; j.at = [x, y]; }
  return j.direction;
}

// A size changed by percent, rounded half up to whole cells and never below 1 cell.
export function jitteredSize(size, percent) { return Math.max(1, Math.floor((size * (100 + percent) + 50) / 100)); }

function nextOffsets(stroke) {
  if (stroke.jitter === undefined) {
    const b = resolveBrush(stroke.brush);
    stroke.jitter = {range: angleJitterActive(stroke.brush) ? b.angle_jitter : 0, sizeRange: b.size_jitter,
      amountRange: b.amount_jitter, flowRange: flowJitterRange(stroke.brush), scatter: b.scatter, seed: b.jitter_seed, settings: b, x0: stroke.last[0], y0: stroke.last[1], k: 0, footprints: new Map(),
      follow: followDirectionActive(stroke.brush), at: null, direction: null, gap: 0, held: null, provisional: null};
    if (stroke.jitter.follow) stroke.jitter.held = [];
  }
  const j = stroke.jitter, k = j.k++;
  return [jitterOffset(j.range, j.x0, j.y0, k, j.seed), sizeJitterOffset(j.sizeRange, j.x0, j.y0, k, j.seed),
    amountJitterOffset(j.amountRange, j.x0, j.y0, k, j.seed), flowJitterOffset(j.flowRange, j.x0, j.y0, k, j.seed)];
}

// The footprint, and the profile for a gradient, of a stamp of this size, angle offset and stroke
// direction (null: none).
function turnedStamp(stroke, size, offset, profiled, direction) {
  const key = direction === null ? `${size} ${offset}` : `${size} ${offset} ${direction}`, footprints = stroke.jitter.footprints;
  if (!footprints.has(key)) {
    const turned = jitteredRotation(stroke.brush.rotation_degrees ?? 0, offset);
    const rotation = direction === null ? turned : followedRotation(turned, direction);
    const footprint = prepareFootprint({...stroke.brush, size, rotation_degrees: rotation});
    footprints.set(key, {footprint, profile: profiled ? prepareProfile(stroke.jitter.settings, footprint) : null});
  }
  return footprints.get(key);
}

// Everything painting a held stamp changes: per-cell buffers and each engine's per-stamp state.
const PAINTED = ["coverage", "amounts", "targets", "centrality", "strongest", "strongestAmounts"];
const STATE = ["lastSnap", "lastStamp", "footprint", "profile", "flow", "offset", "percent", "direction", "amountPercent", "flowPercent"];

// Whether this stamp is held: before the first direction. With it, the held stamps are painted.
function held(stroke, stamp, direction) {
  const j = stroke.jitter;
  if (j.held === null) return false;
  withdraw(stroke);
  if (direction === null) { j.held.push(stamp); return true; }
  const stamps = j.held; j.held = null;
  for (const s of stamps) stroke.place(s, direction);
  return false;
}

// Held stamps painted at Rotation alone until the next stamp, which withdraws them exactly.
function reveal(stroke) {
  const j = stroke.jitter;
  if (j === undefined || j.held === null || j.held.length === 0 || j.provisional !== null) return;
  j.provisional = {buffers: PAINTED.map(key => stroke[key]?.slice() ?? null), state: STATE.map(key => stroke[key])};
  for (const s of j.held) stroke.place(s, null);
}

function withdraw(stroke) {
  const saved = stroke.jitter.provisional;
  if (saved === null) return;
  PAINTED.forEach((key, i) => { if (saved.buffers[i]) stroke[key].set(saved.buffers[i]); });
  STATE.forEach((key, i) => { stroke[key] = saved.state[i]; });
  stroke.jitter.provisional = null;
}

export class JitterStroke extends Stroke {
  stamp(x, y) {
    const [offset, percent, , flowPercent] = nextOffsets(this);
    const j = this.jitter, stamp = {x, y, k: j.k - 1, offset, size: jitteredSize(this.brush.size, percent), flowPercent};
    const direction = followed(j, x, y, this.spacing / 256);
    if (!held(this, stamp, direction)) this.place(stamp, direction);
  }

  place({x, y, k, offset, size, flowPercent}, direction) {
    const j = this.jitter;
    // Flow Jitter replaces only the stamp's Flow; the factor keeps the stroke's spacing and Size.
    if (j.flowRange) this.flow = flowFactor(jitteredFlow(j.settings.flow, flowPercent), this.spacing, this.brush.size);
    const {footprint, profile} = turnedStamp(this, size, offset, this.profile !== null, direction);
    // A repeated hard stamp is skipped only at the same snap, size and angle.
    if (footprint !== this.footprint) { this.footprint = footprint; this.profile = profile; this.lastSnap = null; }
    if (j.scatter === 0) { super.stamp(x, y); return; }
    const [dx, dy] = scatterOffset(j.scatter, size, j.x0, j.y0, k, j.seed);
    super.stamp(x + dx, y + dy);
  }

  result() { reveal(this); return super.result(); }
}

export class JitterPressureStroke extends PressureStroke {
  // pressure null: a mouse stroke, painted at full pressure with the set values. With Amount Jitter
  // the pressure Amount mapping always runs, so each stamp can keep its own Amount per cell;
  // jitterBase records whether pen pressure itself changes Amount.
  constructor(codes, width, height, brush, x, y, restore = null, selection = null, pressure = PRESSURE_FULL) {
    const pen = pressure !== null, b = resolveBrush(brush);
    const engineBrush = b.amount_jitter === 0 ? brush : {...brush, pressure_enabled: true, pressure_amount: true,
      jitterBase: pen && pressureMappings(b)?.amount === true};
    super(codes, width, height, engineBrush, x, y, restore, selection, pen ? pressure : PRESSURE_FULL);
    this.mouse = !pen;
  }

  add(x, y, pressure) { super.add(x, y, this.mouse ? PRESSURE_FULL : pressure); }

  slot(x, y, code) {
    const [offset, percent, amount, flowPercent] = nextOffsets(this);
    // The path distance from the slot before is the spacing it returned.
    const j = this.jitter, direction = followed(j, x, y, j.gap / 256);
    const stamp = {x, y, code, k: j.k - 1, offset, percent, amount, flowPercent};
    // A held slot still spaces the next one by its own unjittered size.
    if (held(this, stamp, direction)) return j.gap = super.prepare(this.sizeAt(code)).spacing;
    return j.gap = this.place(stamp, direction);
  }

  place({x, y, code, k, offset, percent, amount, flowPercent}, direction) {
    if (offset !== this.offset || percent !== this.percent || direction !== this.direction) {
      this.offset = offset; this.percent = percent; this.direction = direction; this.lastStamp = null;
    }
    this.amountPercent = amount; this.flowPercent = flowPercent;
    const j = this.jitter;
    if (j.scatter === 0 || code === 0) return super.slot(x, y, code);
    // The slot's own pressure code sets the size Scatter reaches with; its spacing is unchanged.
    const [dx, dy] = scatterOffset(j.scatter, jitteredSize(this.sizeAt(code), percent), j.x0, j.y0, k, j.seed);
    return super.slot(x + dx, y + dy, code);
  }

  result() { reveal(this); return super.result(); }

  // Amount Jitter varies the stamp's own Amount: the set Amount, or pen pressure's when it maps Amount.
  amountAt(code) {
    if (this.jitter === undefined || this.jitter.amountRange === 0) return super.amountAt(code);
    return jitteredAmount(this.brush.jitterBase ? scaledControl(this.brush.amount, code) : this.brush.amount, this.amountPercent);
  }

  // Flow Jitter varies the stamp's own Flow: the set Flow, or pen pressure's when it maps Flow.
  flowAt(code) {
    const flow = super.flowAt(code);
    return this.jitter === undefined || this.jitter.flowRange === 0 ? flow : jitteredFlow(flow, this.flowPercent);
  }

  // size is the pressure stamp's size (Minimum Size applied); Size Jitter varies it. Spacing stays
  // that of the unjittered size.
  prepare(size) {
    const entry = super.prepare(size);
    if (this.jitter === undefined) return entry;  // Construction, before any stamp.
    const jittered = jitteredSize(size, this.percent);
    const {footprint} = turnedStamp(this, jittered, this.offset, false, this.direction);
    return {...entry, footprint, profile: jittered === size ? entry.profile : super.prepare(jittered).profile};
  }
}
