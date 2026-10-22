// E6 management only. No host, field/history state, or new brush arithmetic.
import {BRUSH_DEFAULTS, resolveBrush, prepareFootprint, footprintLocal, localCoverage} from "./brush.js";
import {prepareProfile, profileTarget} from "./value_profile.js";
import {decodeTipDataUrl, storedTipValid, TIP_PREFIX} from "./custom_tip.js";
import {isHotdog} from "./procedural_tip.js";

export const LIBRARY_FILE = "conditioning-layers/brush-library-v1.json";
// Explicit v1 inventory: extending the painting engine cannot silently extend this schema.
export const SNAPSHOT_KEYS = Object.freeze(("size influence hardness amount shape scale_x scale_y rotation_degrees " +
  "mirror_horizontal mirror_vertical crop_left crop_right crop_top crop_bottom falloff_curve build_up flow spacing " +
  "spacing_percent apply_mode value_profile gradient_start gradient_end gradient_curve gradient_angle " +
  "gradient_start_position gradient_end_position gradient_center_x gradient_center_y gradient_inner gradient_outer " +
  "gradient_aspect_x gradient_aspect_y gradient_rotation tip_channel tip_invert tip_trim").split(" "));
export const PROCEDURAL_SNAPSHOT_KEYS = Object.freeze(("procedural_version procedural_type procedural_seed procedural_invert procedural_particle_shape " +
  "procedural_grid procedural_density procedural_particle_size procedural_particle_aspect " +
  "procedural_size_jitter procedural_position_jitter procedural_particle_rotation " +
  "procedural_rotation_jitter procedural_frequency procedural_octaves procedural_persistence " +
  "procedural_noise_low procedural_noise_high").split(" "));
const DECIMALS = new Set(["scale_x", "scale_y", "rotation_degrees", "gradient_curve", "gradient_angle",
  "gradient_aspect_x", "gradient_aspect_y", "gradient_rotation", "procedural_particle_aspect",
  "procedural_particle_rotation", "procedural_rotation_jitter"]);
export const PRESSURE_SNAPSHOT_KEYS = Object.freeze(["pressure_enabled", "pressure_size", "pressure_amount", "pressure_flow"]);
export const HOTDOG_SNAPSHOT_KEYS = Object.freeze(["hotdog_count", "hotdog_spread", "hotdog_invert"]);
// Optional in every version: written only when not the default, and absent means the default.
export const DYNAMICS_SNAPSHOT_KEYS = Object.freeze(["smoothing", "pressure_min_size", "angle_jitter", "size_jitter", "amount_jitter", "jitter_seed", "flow_jitter", "scatter", "follow_direction"]);
const BASE = {size: 16, influence: 255, hardness: 100, amount: 100};
const VALIDATED = new WeakMap();
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const object = v => v !== null && typeof v === "object" && !Array.isArray(v);
function label(value, name, empty = false) {
  if (typeof value !== "string" || value.trim().length > 80 || (!empty && !value.trim()))
    throw new Error(`${name} must contain ${empty ? "0" : "1"}–80 characters.`);
  return value.trim();
}
function snapshot(source, version) {
  if (!object(source)) throw new Error("Missing brush snapshot.");
  const procedural = source.shape === "procedural";
  const hotdog = procedural && isHotdog(source);
  if (hotdog && version !== 3) throw new Error("Hotdog requires preset version 3.");
  if (!hotdog && HOTDOG_SNAPSHOT_KEYS.some(key => Object.hasOwn(source, key)))
    throw new Error("Only Hotdog presets contain template settings.");
  if (procedural && source.procedural_version !== 1) throw new Error("Unsupported procedural version; expected 1.");
  if (!procedural && PROCEDURAL_SNAPSHOT_KEYS.some(key => Object.hasOwn(source, key)))
    throw new Error("Only Procedural presets contain procedural settings.");
  const brush = {};
  if (version === 1 && PRESSURE_SNAPSHOT_KEYS.some(key => Object.hasOwn(source, key)))
    throw new Error("Only version 2 presets contain pen pressure settings.");
  for (const key of [...SNAPSHOT_KEYS, ...(procedural ? PROCEDURAL_SNAPSHOT_KEYS : []),
    ...(hotdog ? HOTDOG_SNAPSHOT_KEYS : []), ...(version >= 2 ? PRESSURE_SNAPSHOT_KEYS : [])]) {
    if (!Object.hasOwn(source, key)) throw new Error(`Missing brush ${key}.`);
    const value = source[key];
    if (DECIMALS.has(key) && Math.round(value * 10) / 10 !== value)
      throw new Error(`Brush ${key} must have at most one decimal place.`);
    brush[key] = value;
  }
  for (const key of DYNAMICS_SNAPSHOT_KEYS) if (Object.hasOwn(source, key)) brush[key] = source[key];
  for (const [key, low, high] of [["size", 1, 128], ["influence", 0, 255], ["hardness", 0, 100], ["amount", 1, 100]])
    if (!Number.isInteger(brush[key]) || brush[key] < low || brush[key] > high) throw new Error(`Invalid brush ${key}.`);
  resolveBrush(brush); // Retained E3–E5 enum, range, crop and profile-pair validation.
  if (brush.shape === "custom") {
    if (!storedTipValid(source.custom_tip)) throw new Error("A Custom preset requires a valid embedded tip.");
    brush.custom_tip = source.custom_tip;
  } else if (source.custom_tip !== undefined) throw new Error("Only Custom presets contain a custom tip.");
  return Object.freeze(brush);
}

async function decodedTip(brush) {
  if (brush.shape === "procedural") prepareFootprint(brush);
  if (brush.shape !== "custom") return null;
  // Reuse E5's decoder. Require its portable gray+alpha representation, without ancillary source metadata.
  const tip = await decodeTipDataUrl(brush.custom_tip);
  const bytes = Uint8Array.from(atob(brush.custom_tip.slice(TIP_PREFIX.length)), c => c.charCodeAt(0));
  if (bytes[24] !== 8 || bytes[25] !== 4) throw new Error("Preset tip must be an E5 canonical gray+alpha PNG.");
  const view = new DataView(bytes.buffer);
  for (let offset = 8; offset < bytes.length;) {
    const kind = String.fromCharCode(...bytes.subarray(offset + 4, offset + 8));
    if (!["IHDR", "IDAT", "IEND"].includes(kind)) throw new Error("Preset tip must contain only canonical PNG chunks.");
    offset += view.getUint32(offset) + 12;
  }
  prepareFootprint({...brush, tip}); // Refuse empty/unusable Custom brushes as E5 does.
  return tip;
}

export async function validateBrushPreset(value) {
  if (object(value) && VALIDATED.has(value)) return value;
  // v3 is reserved for Hotdog. Preserve the retained rejection for other brushes.
  const hotdogV3 = value?.version === 3 && value.brush?.shape === "procedural" && isHotdog(value.brush);
  if (!object(value) || (![1, 2].includes(value.version) && !hotdogV3))
    throw new Error("Unsupported preset version; expected v1 or v2.");
  if (value.version === 2 && value.brush?.pressure_enabled !== true)
    throw new Error("A version 2 preset must use pen pressure.");
  if (typeof value.id !== "string" || !/^[a-zA-Z0-9_-]{1,128}$/.test(value.id)) throw new Error("Invalid preset ID.");
  if (typeof value.favorite !== "boolean") throw new Error("Invalid preset favorite flag.");
  const preset = Object.freeze({version: value.version, id: value.id, name: label(value.name, "Preset name"),
    category: label(value.category, "Category", true), favorite: value.favorite, brush: snapshot(value.brush, value.version)});
  VALIDATED.set(preset, await decodedTip(preset.brush));
  return preset;
}

export async function captureBrushPreset(settings, metadata) {
  const complete = {...BASE, ...BRUSH_DEFAULTS, ...settings};
  const brush = Object.fromEntries(SNAPSHOT_KEYS.map(key => [key, complete[key]]));
  if (brush.shape === "procedural") for (const key of PROCEDURAL_SNAPSHOT_KEYS) brush[key] = complete[key];
  const hotdog = brush.shape === "procedural" && isHotdog(brush);
  if (hotdog) for (const key of HOTDOG_SNAPSHOT_KEYS) brush[key] = complete[key];
  const pressure = complete.pressure_enabled === true;
  if (pressure || hotdog) for (const key of PRESSURE_SNAPSHOT_KEYS) brush[key] = complete[key];
  for (const key of DYNAMICS_SNAPSHOT_KEYS) if (complete[key] !== BRUSH_DEFAULTS[key]) brush[key] = complete[key];
  if (brush.shape === "custom") brush.custom_tip = settings.custom_tip;
  return validateBrushPreset({favorite: false, category: "", ...metadata, version: hotdog ? 3 : pressure ? 2 : 1, brush});
}

// Prepare everything before touching the session. Caller may await this before a synchronous commit.
export async function prepareBrushPreset(value) {
  const preset = await validateBrushPreset(value);
  const tip = VALIDATED.get(preset);
  // Decoded arrays handed to an editor never alias a validated library asset.
  return {brush: preset.brush, tip: tip ? {...tip, luminance: tip.luminance.slice(), alpha: tip.alpha.slice()} : null};
}
export function applyPreparedBrush(prepared, session) {
  for (const key of [...PROCEDURAL_SNAPSHOT_KEYS, ...PRESSURE_SNAPSHOT_KEYS, ...HOTDOG_SNAPSHOT_KEYS, ...DYNAMICS_SNAPSHOT_KEYS]) session.settings[key] = BRUSH_DEFAULTS[key];
  Object.assign(session.settings, prepared.brush);
  if (!prepared.brush.custom_tip) delete session.settings.custom_tip;
  session.tip = prepared.tip;
}
export async function applyBrushPreset(value, session) {
  const prepared = await prepareBrushPreset(value);
  applyPreparedBrush(prepared, session);
}

export async function loadBrushLibrary(text) {
  const data = text === null ? {version: 1, presets: []} : JSON.parse(text);
  if (!object(data) || data.version !== 1 || !Array.isArray(data.presets))
    throw new Error("Unsupported or malformed brush library; expected a v1 preset list. Stored data was not changed.");
  const presets = [], rejected = [], warnings = [], counts = new Map();
  for (const entry of data.presets) if (typeof entry?.id === "string") counts.set(entry.id, (counts.get(entry.id) ?? 0) + 1);
  for (const [index, entry] of data.presets.entries()) {
    try {
      const preset = await validateBrushPreset(entry);
      // Neither entry owns an ambiguous ID. Otherwise deleting the first could resurrect the second.
      if (counts.get(preset.id) !== 1) throw new Error("Duplicate preset ID; all entries with this ID are unavailable.");
      presets.push(preset);
    } catch (error) {
      rejected.push(entry); warnings.push(`Preset ${index + 1}: ${error.message}`);
    }
  }
  return {presets, rejected, warnings};
}
// Valid entries have canonical key order; identity order is independent of UI sorting.
// Rejected entries survive subsequent writes verbatim as JSON values, never silently repaired/dropped.
export function serializeBrushLibrary({presets, rejected = []}) {
  return JSON.stringify({version: 1, presets: [...presets].sort((a, b) => compare(a.id, b.id)).concat(rejected)});
}
export function filterBrushPresets(presets, {search = "", category = null, favorites = false} = {}) {
  const query = search.trim().toLowerCase();
  return presets.filter(p => (!favorites || p.favorite) && (category === null || p.category === category)
    && `${p.name}\n${p.category}`.toLowerCase().includes(query))
    .sort((a, b) => Number(b.favorite) - Number(a.favorite) || compare(a.name.toLowerCase(), b.name.toLowerCase())
      || compare(a.category.toLowerCase(), b.category.toLowerCase()) || compare(a.name, b.name) || compare(a.id, b.id));
}
export function uniquePresetName(presets, name, category, except = null) {
  const base = label(name, "Preset name"), group = label(category, "Category", true);
  const used = new Set(presets.filter(p => p.id !== except && p.category.toLowerCase() === group.toLowerCase())
    .map(p => p.name.toLowerCase()));
  let result = base;
  for (let n = 2; used.has(result.toLowerCase()); n++) {
    const suffix = ` (${n})`; result = base.slice(0, 80 - suffix.length) + suffix;
  }
  return result;
}

// One adapter-owned instance per page serializes writes across nodes. Refresh before every mutation.
// No local state is published until the host acknowledges persistence; failed writes are retryable.
export function createBrushLibrary(storage, newId = () => crypto.randomUUID()) {
  let tail = Promise.resolve();
  const run = action => { const result = tail.then(action); tail = result.catch(() => {}); return result; };
  const load = async () => loadBrushLibrary(await storage.read());
  async function mutate(action) {
    return run(async () => {
      const library = await load(), id = await action(library);
      await storage.write(serializeBrushLibrary(library));
      return {...library, id};
    });
  }
  function fresh(library) {
    const id = newId();
    if (library.presets.some(p => p.id === id) || library.rejected.some(p => p?.id === id))
      throw new Error("Generated preset ID already exists; retry the operation.");
    return id;
  }
  const find = (library, id) => {
    const index = library.presets.findIndex(p => p.id === id);
    if (index < 0) throw new Error("Preset no longer exists. Refresh the library.");
    return index;
  };
  return {
    load: () => run(load),
    save: (settings, name, category = "") => {
      const source = {...settings}; // Capture now, before waiting for another writer.
      return mutate(async library => {
        const id = fresh(library), safeName = uniquePresetName(library.presets, name, category);
        library.presets.push(await captureBrushPreset(source, {id, name: safeName, category})); return id;
      });
    },
    update: (id, settings) => {
      const source = {...settings};
      return mutate(async library => {
        const i = find(library, id);
        library.presets[i] = await captureBrushPreset(source, library.presets[i]); return id;
      });
    },
    metadata: (id, changes) => mutate(async library => {
      const i = find(library, id), previous = library.presets[i];
      const category = changes.category ?? previous.category;
      const name = uniquePresetName(library.presets, changes.name ?? previous.name, category, id);
      library.presets[i] = await validateBrushPreset({...previous, name, category,
        favorite: changes.favorite ?? previous.favorite}); return id;
    }),
    remove: id => mutate(library => { library.presets.splice(find(library, id), 1); return null; }),
    duplicate: id => mutate(async library => {
      const original = library.presets[find(library, id)], copyId = fresh(library);
      library.presets.push(await validateBrushPreset({...original, id: copyId,
        name: uniquePresetName(library.presets, original.name, original.category)})); return copyId;
    }),
    importPreset: text => mutate(async library => {
      const original = await validateBrushPreset(JSON.parse(text)), id = fresh(library);
      library.presets.push(await validateBrushPreset({...original, id,
        name: uniquePresetName(library.presets, original.name, original.category)})); return id;
    }),
  };
}

// Small display-only samples of the retained footprint/profile evaluators. No Stroke or field operation.
export function createPresetThumbnails(limit = 64) {
  const cache = new Map();
  return async preset => {
    const key = preset.id, previous = cache.get(key);
    if (previous && [...SNAPSHOT_KEYS, ...PROCEDURAL_SNAPSHOT_KEYS, ...HOTDOG_SNAPSHOT_KEYS, "custom_tip"].every(k => previous.brush[k] === preset.brush[k])) return previous.task;
    const task = (async () => {
      const {brush, tip} = await prepareBrushPreset(preset), f = prepareFootprint({...brush, tip});
      const p = prepareProfile(brush, f), side = 48, pixels = new Uint8ClampedArray(side * side * 4);
      const span = Math.max(...f.extent) * 2 / 0.9, local = [0, 0];
      for (let y = 0; y < side; y++) for (let x = 0; x < side; x++) {
        footprintLocal(f, ((x + 0.5) / side - 0.5) * span, ((y + 0.5) / side - 0.5) * span, local);
        const weight = localCoverage(f, ...local), target = p ? profileTarget(p, ...local) : brush.influence;
        const i = (y * side + x) * 4;
        pixels[i] = pixels[i + 1] = pixels[i + 2] = target; pixels[i + 3] = Math.round(weight * 255);
      }
      return {side, pixels};
    })();
    cache.set(key, {brush: preset.brush, task});
    if (cache.size > limit) cache.delete(cache.keys().next().value);
    try { return await task; } catch (error) { if (cache.get(key)?.task === task) cache.delete(key); throw error; }
  };
}
