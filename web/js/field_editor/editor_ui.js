import {Stroke, fieldOperation, percentToCode, sameCodes, stampPreview, transformField, withinSelection, FIELD_TRANSFORMS, PressureStroke, pressureCode, pressureMappings, pressurePercent} from "./engine.js";
import {FieldHistory, observeHistory} from "./history.js";
import {TransferLinks, transferReach, transferEngineBrush, transferSource, nothingMovable,
  BALANCE_DEFAULT_SHARE, balanceTarget, balancePartner, balanceSettled} from "./transfer.js";
import {createNumberControl} from "./number_control.js";
import {StrokeSmoother} from "./stroke_smoothing.js";
import {JitterStroke, JitterPressureStroke, stampJitterActive} from "./angle_jitter.js";
import {decodeFieldPng, encodeFieldPng} from "./png_codec.js";
import {BRUSH_DEFAULTS, PROCEDURAL_KEYS, PROCEDURAL_EMPTY, cropError, profileError, proceduralError, proceduralMask, tipMask, validBrushSetting} from "./brush.js";
import {decodeTipDataUrl, importTipFile, storedTipValid} from "./custom_tip.js";
import {applyPreparedBrush} from "./brush_library.js";
import {isHotdog} from "./procedural_tip.js";
import {openBrushLibrary} from "./brush_library_ui.js";
import {selectionCell, onField, selectionRectangle, rectangleSelection, ellipseSelection,
  combineSelection, invertSelection, selectAll, selectionStats, SELECTION_MODES} from "./selection.js";
import {MASK_DEFAULTS, readMaskFile} from "./field_import.js";
import {openMaskImport} from "./field_import_ui.js";
import {openFieldChooser} from "./field_chooser_ui.js";
import {OVERLAY_COLORS, overlayPixels, drawContribution} from "./view.js";
import {heatColor, fieldPosition, cellReadout, gridVisible, gridPath, fieldStatistics,
  displayState, createViewSession, footprintOutline, outlinePath, SELECTION_VEIL, selectionOutlinePath} from "./view.js";

const SVG = "http://www.w3.org/2000/svg";
const ONE_DECIMAL = new Set(["scale_x", "scale_y", "rotation_degrees", "gradient_curve", "gradient_angle",
  "gradient_aspect_x", "gradient_aspect_y", "gradient_rotation", "procedural_particle_aspect",
  "procedural_particle_rotation", "procedural_rotation_jitter"]);
const ORDERED_PAIRS = [["gradient_start_position", "gradient_end_position"], ["gradient_inner", "gradient_outer"],
  ["procedural_noise_low", "procedural_noise_high"]];
const GRADIENTS = {linear: "Linear gradient", radial: "Radial gradient", square: "Square gradient"};
const GRADIENT_HELP = {
  linear: "Start Value sits at Start Position and End Value at End Position; 0–100% spans the brush along the angle.",
  centred: "Start Value fills Inner and End Value lies beyond Outer; 100% reaches the brush edge and Center 50% is its middle.",
  both: "The gradient crops, mirrors, scales and turns with the brush. Curve shapes Start→End; Hardness shapes coverage.",
};
const TIP_CHANNELS = {alpha: "Alpha", luminance: "Luminance", alpha_luminance: "Alpha × Luminance"};
// Why a Custom brush cannot paint, by the condition of its tip; "ready" paints.
const TIP_BADGES = {none: "no tip", loading: "loading", error: "unreadable", empty: "empty"};
const TRANSFORM_LABELS = ["Flip Horizontal", "Flip Vertical", "Rotate 90° CW", "Rotate 90° CCW"];
const TRANSFORM_DISABLED = "Flip and rotate move every cell, so they are unavailable while a selection is active. Clear Selection first.";
const EMPTY_SELECTION = "That would leave no cells selected, so the selection is unchanged.";
export const MAX_SESSION_FIELDS = 4;
export function nextColorSlot(used) {
  for (let slot = 0; slot < MAX_SESSION_FIELDS; slot++) if (!used.includes(slot)) return slot;
  throw new Error("No free colour slot");
}
export function activeIndexAfterRemoval(count, removed, active) {
  if (removed !== active) return active > removed ? active - 1 : active;
  return Math.min(removed, count - 2);
}

// Canonical stored settings: the E1 keys always, and an E3/E4/E5 brush setting only when it differs
// from its default, so node properties saved before E3 stay byte-identical until one changes.
// Restore is session-scoped (its baseline is this session's opening field) and stores as Paint.
// An imported custom tip is kept as custom_tip, its canonical PNG data URL, only while there is one.
export function editorSettings(source = {}) {
  const result = {tool: "paint", size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: "percent"};
  for (const [key, low, high] of [["size", 1, 128], ["influence", 0, 255], ["hardness", 0, 100], ["amount", 1, 100]]) {
    if (Number.isInteger(source?.[key]) && source[key] >= low && source[key] <= high) result[key] = source[key];
  }
  if (source?.tool === "erase") result.tool = "erase";
  if (source?.influenceUnit === "code") result.influenceUnit = "code";
  const brush = {...BRUSH_DEFAULTS};
  for (const key of Object.keys(brush)) {
    const value = source?.[key];
    if (value !== undefined && validBrushSetting(key, value)
        && (!ONE_DECIMAL.has(key) || Math.round(value * 10) / 10 === value)) brush[key] = value;
  }
  // As with any invalid stored setting, an impossible crop or gradient pair falls back to its defaults.
  if (brush.crop_left + brush.crop_right >= 100) brush.crop_left = brush.crop_right = 0;
  if (brush.crop_top + brush.crop_bottom >= 100) brush.crop_top = brush.crop_bottom = 0;
  for (const [low, high] of ORDERED_PAIRS)
    if (brush[low] >= brush[high]) { brush[low] = BRUSH_DEFAULTS[low]; brush[high] = BRUSH_DEFAULTS[high]; }
  const proceduralContent = source?.shape === "procedural" || PROCEDURAL_KEYS.some(key => key !== "procedural_version" && Object.hasOwn(source ?? {}, key));
  if (proceduralContent && source?.procedural_version !== 1) {
    for (const key of PROCEDURAL_KEYS) brush[key] = BRUSH_DEFAULTS[key];
    if (brush.shape === "procedural") brush.shape = "disk";
  }
  const storeProcedural = brush.shape === "procedural" || PROCEDURAL_KEYS.some(key => brush[key] !== BRUSH_DEFAULTS[key]);
  for (const [key, fallback] of Object.entries(BRUSH_DEFAULTS))
    if (brush[key] !== fallback || (key === "procedural_version" && storeProcedural)) result[key] = brush[key];
  if (storedTipValid(source?.custom_tip)) result.custom_tip = source.custom_tip;
  return result;
}

// The full working settings of one session: every E3 key present, defaults filled in.
function sessionSettings(source) {
  const stored = editorSettings(source), result = {};
  for (const key of ["tool", "size", "influence", "hardness", "amount", "influenceUnit"]) result[key] = stored[key];
  for (const [key, fallback] of Object.entries(BRUSH_DEFAULTS)) result[key] = key in stored ? stored[key] : fallback;
  if (stored.custom_tip) result.custom_tip = stored.custom_tip;
  return result;
}

// How a custom tip is read, where that differs from the default (Alpha, not inverted, untrimmed).
function tipModifiers(s) {
  const result = [];
  if (s.tip_channel !== BRUSH_DEFAULTS.tip_channel) result.push(TIP_CHANNELS[s.tip_channel]);
  if (s.tip_invert) result.push("Inverted");
  if (s.tip_trim) result.push("Trimmed");
  return result;
}

// Collapsed-header indicators for advanced brush behavior that is active. Flow and custom
// Spacing values, gradient settings under Uniform and tip reading under a built-in shape have
// no effect and are not flagged. tip is the custom tip's condition; anything but "ready" is shown.
function pressureLabels(settings) {
  const mappings = pressureMappings(settings);
  return ["Size", "Amount", "Flow"].filter(label => mappings?.[label.toLowerCase()])
    .map(label => label === "Size" && settings.pressure_min_size ? `Size ≥ ${settings.pressure_min_size}%` : label);
}
export function brushBadges(s, tip = "ready", procedural = "ready", share = BALANCE_DEFAULT_SHARE) {
  const behavior = [], shape = [], profile = [];
  if (s.amount !== 100) behavior.push(`Amount ${s.amount}%`);
  if (s.amount_jitter) behavior.push(`Amount Jitter ±${s.amount_jitter}%`);
  if (s.tool === "restore") behavior.push("Restore");
  if (s.tool === "transfer") behavior.push("Transfer");
  if (s.tool === "balance") behavior.push(`Balance ${share}:${100 - share}`);
  if (s.build_up) behavior.push(`Build-up ${s.flow}%`);
  if (s.build_up && s.flow_jitter) behavior.push(`Flow Jitter ±${s.flow_jitter}%`);
  if (s.spacing === "custom") behavior.push(`Spacing ${s.spacing_percent}%`);
  if (s.smoothing) behavior.push(`Smoothing ${s.smoothing}%`);
  if (s.falloff_curve !== "smooth") behavior.push(s.falloff_curve === "linear" ? "Linear falloff" : "Sharper falloff");
  if (s.apply_mode !== "normal") behavior.push((s.apply_mode === "raise_only" ? "Raise Only" : "Lower Only")
    + (s.tool === "transfer" ? " (inactive for Transfer)" : s.tool === "balance" ? " (inactive for Balance)" : ""));
  if (s.pressure_enabled) behavior.push(`Pen Pressure (${pressureLabels(s).join(", ") || "no effect"})`);
  if (s.shape === "custom") shape.push(TIP_BADGES[tip] ? `Custom (${TIP_BADGES[tip]})` : "Custom", ...tipModifiers(s));
  else if (s.shape === "procedural") shape.push(`Procedural ${s.procedural_type === "scatter" ? "Scatter" : "Noise"}${procedural === "empty" ? " (empty)" : ""}`, ...proceduralModifiers(s));
  else if (s.shape !== "disk") shape.push(s.shape === "square" ? "Square" : "Diamond");
  if (s.scale_x !== 1 || s.scale_y !== 1) shape.push(`Scale ${s.scale_x}×${s.scale_y}`);
  if (s.rotation_degrees !== 0) shape.push(`Rotation ${s.rotation_degrees}°`);
  if (s.follow_direction) shape.push("Follow Direction");
  if (s.angle_jitter) shape.push(`Angle Jitter ±${s.angle_jitter}°`);
  if (s.size_jitter) shape.push(`Size Jitter ±${s.size_jitter}%`);
  if (s.scatter) shape.push(`Scatter ${s.scatter}%`);
  if (s.jitter_seed) shape.push(`Jitter Seed ${s.jitter_seed}`);
  if (s.mirror_horizontal) shape.push("Mirror H");
  if (s.mirror_vertical) shape.push("Mirror V");
  if (s.crop_left || s.crop_right || s.crop_top || s.crop_bottom)
    shape.push(`Crop L${s.crop_left} R${s.crop_right} T${s.crop_top} B${s.crop_bottom}`);
  if (s.value_profile !== "uniform") {
    profile.push(GRADIENTS[s.value_profile], `${s.gradient_start}→${s.gradient_end}`);
    if (s.gradient_curve !== 1) profile.push(`Curve ${s.gradient_curve}`);
    if (s.tool !== "paint") profile.push(`inactive for ${s.tool === "erase" ? "Erase" : s.tool === "transfer" ? "Transfer"
      : s.tool === "balance" ? "Balance" : "Restore"}`);
  }
  return {behavior, shape, profile};
}

function proceduralModifiers(s) {
  return [...(s.procedural_type === "scatter" ? [s.procedural_particle_shape[0].toUpperCase() + s.procedural_particle_shape.slice(1)] : []),
    `Seed ${s.procedural_seed}`, ...(isHotdog(s) ? [`Count ${s.hotdog_count}`, `Spread ${s.hotdog_spread}%`,
      ...(s.hotdog_invert ? ["Template inverted"] : [])] : s.procedural_invert ? ["Inverted"] : [])];
}

export function createEditorSession(codes, settings) {
  const initial = codes.slice(), history = new FieldHistory();
  // initial is the immutable session-open field: the Done baseline and the Restore target.
  // tip is the decoded custom tip of settings.custom_tip, once it is read (never stored itself).
  return {codes: codes.slice(), settings: sessionSettings(settings), history, initial, tip: null,
    selection: null, selectTool: null, selectionMode: "replace",
    changed() { return !sameCodes(initial, this.codes); },
    replace(label, after) { history.record(label, this.codes, after); this.codes = after.slice(); },
    operation(name) { this.replace(name, withinSelection(this.codes, fieldOperation(this.codes, name, this.settings.influence), this.selection)); },
    transform(name) {
      if (this.selection !== null) throw new Error("Clear the selection to flip or rotate the whole field.");
      this.replace(TRANSFORM_LABELS[FIELD_TRANSFORMS.indexOf(name)], transformField(this.codes, name));
    },
    undo() { this.codes = history.undo() ?? this.codes; },
    redo() { this.codes = history.redo() ?? this.codes; }};
}

export function drawCodes(canvas, codes, heat = false) {
  canvas.width = 128; canvas.height = 128;
  const context = canvas.getContext("2d"), pixels = context.createImageData(128, 128);
  for (let i = 0; i < codes.length; i++) {
    const color = heat ? heatColor(codes[i]) : [codes[i], codes[i], codes[i]];
    pixels.data.set(color, i * 4);
    pixels.data[i * 4 + 3] = 255;
  }
  context.putImageData(pixels, 0, 0); // Display only; never read back into field data.
}

export function openInfluenceFieldEditor({codes, settings, host, onDone, onCancel}) {
  const links = new TransferLinks(() => records);
  function record(item, slot) {
    const session = createEditorSession(item.codes, item.settings);
    observeHistory(session.history, links.discarded);
    return {key: item.key, label: item.label, slot, visible: true, session, transferSource: null,
      balancePartner: null, balanceShare: BALANCE_DEFAULT_SHARE,
      initialSettings: JSON.stringify(editorSettings(session.settings)), tipLoad: "none", tipError: "",
      tipOpaque: false, overlay: null, shownCodes: null};
  }
  const records = [record({key: host.fields?.openingKey ?? "opening", label: host.fields?.openingLabel ?? "Painted Field", codes, settings}, 0)];
  let active = records[0], session = active.session;
  const changed = r => r.session.changed() || JSON.stringify(editorSettings(r.session.settings)) !== r.initialSettings;
  const isAvailable = r => host.fields ? host.fields.available(r.key) : true;
  let stroke = null, smoother = null, gesture = null, space = false, closed = false, busy = false, frame = null;
  let transfer = null, transferMessage = null;
  // A Balance stroke's binding at its start, and the message-line text Balance set.
  let balance = null, balanceMessage = null;
  let zoom = 1, panX = 0, panY = 0, cursor = null;
  // E5: the stored tip is read after opening ("loading"); "error" keeps its string unchanged.
  let shownMask = null;
  // The message-line text Custom Tip set, a refusal or a failed import: only it is ever cleared by Custom Tip.
  let tipMessage = null;
  const view = createViewSession();
  let previewService = null, previewQueue = null, previewPoll = null, previewEpoch = 0;
  let previewContext = null, previewField = null, previewSnapshot = null, previewOptions = "";
  let previewError = null, preparedState = null, preparedWeights = null;
  let referenceUrl = null, referenceRevision = 0, anchor = null, endpoint = null, comparePointer = null, compareKey = null;
  const pendingReferences = new Set();
  const controls = [], synced = [], refreshers = [];
  let rejection = "";
  let libraryDialog = null;
  let chooserDialog = null;
  let maskDialog = null, fieldToolsMessage = null, candidate = null;
  let shownSelection = undefined, shownCandidate = undefined;
  const maskOptions = {...MASK_DEFAULTS};
  const el = (tag, text, parent) => {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    parent?.append(item); return item;
  };
  const dialog = el("dialog"); dialog.className = "cl-field-editor";
  dialog.setAttribute("aria-label", "Influence Field Editor");
  const style = el("style", null, dialog);
  style.textContent = `
    .cl-field-editor {width:96vw;height:96vh;box-sizing:border-box;
      background:#24262b;color:#eee;border:1px solid #777;border-radius:8px;padding:16px;}
    .cl-field-editor::backdrop {background:#0009;}
    .cl-field-editor .layout {display:flex;flex-direction:column;gap:6px;height:100%;}
    .cl-field-editor .bar {display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
    .cl-field-editor .top-bar {flex-wrap:nowrap;flex:none;min-width:0;}
    .cl-field-editor .top-bar > :not(.status) {flex:none;white-space:nowrap;}
    .cl-field-editor .body {display:flex;gap:16px;flex:1;min-height:0;}
    .cl-field-editor .viewport {position:relative;flex:1;min-width:100px;overflow:hidden;background:#141519;touch-action:none;}
    .cl-field-editor canvas {position:absolute;left:0;top:0;image-rendering:pixelated;transform-origin:0 0;}
    .cl-field-editor .reference,.cl-field-editor .cell-grid {position:absolute;left:0;top:0;
      width:128px;height:128px;transform-origin:0 0;pointer-events:none;}
    .cl-field-editor .reference {object-fit:fill;}
    .cl-field-editor .cell-grid {overflow:visible;}
    .cl-field-editor .target-cell {position:absolute;box-sizing:border-box;border:1px solid #00ffff;
      box-shadow:0 0 0 1px #111;pointer-events:none;}
    .cl-field-editor .reference-drop {border:1px dashed #888;padding:6px;font-size:12px;}
    .cl-field-editor .brush-outline {position:absolute;left:0;top:0;width:128px;height:128px;
      transform-origin:0 0;overflow:visible;pointer-events:none;}
    .cl-field-editor .brush-preview {pointer-events:none;}
    .cl-field-editor .selection-veil {pointer-events:none;}
    .cl-field-editor .selection-outline,.cl-field-editor .selection-candidate {position:absolute;left:0;top:0;
      width:128px;height:128px;transform-origin:0 0;overflow:visible;pointer-events:none;}
    .cl-field-editor .tools {display:grid;grid-template-columns:minmax(0,1fr) auto auto;
      grid-template-rows:32px;gap:8px;flex:none;min-width:0;position:relative;}
    .cl-field-editor .painting-controls {display:flex;align-items:center;gap:8px;min-width:0;
      overflow-x:auto;overflow-y:hidden;scrollbar-width:thin;grid-column:1;grid-row:1;}
    .cl-field-editor .painting-controls > * {flex:none;}
    .cl-field-editor .painting-controls .bar {flex-wrap:nowrap;}
    .cl-field-editor .painting-controls label {white-space:nowrap;}
    .cl-field-editor .painting-controls input {width:56px;}
    .cl-field-editor .influence-control {width:208px;}
    .cl-field-editor .influence-group {display:flex;align-items:center;gap:2px;}
    .cl-field-editor .influence-menu > summary {list-style:none;min-width:20px;text-align:center;
      border:1px solid #777;border-radius:3px;line-height:18px;}
    .cl-field-editor .influence-menu > summary::-webkit-details-marker {display:none;}
    .cl-field-editor .influence-menu[open] > summary {background:#3a3d44;}
    /* The containing block is the toolbar, outside its scrolling strip. */
    .cl-field-editor .painting-options {position:absolute;top:100%;left:clamp(0px,25%,calc(100% - 318px));
      z-index:3;width:300px;display:flex;flex-direction:column;align-items:flex-start;gap:8px;
      padding:8px;background:#24262b;border:1px solid #777;font-size:12px;}
    .cl-field-editor .painting-options small {font-size:inherit;}
    .cl-field-editor .painting-options button {padding:6px;}
    .cl-field-editor .influence-readout {white-space:nowrap;font-variant-numeric:tabular-nums;}
    .cl-field-editor .field-strip .profile-note {width:300px;font-size:12px;line-height:14px;white-space:normal;}
    .cl-field-editor .field-menu {grid-column:2;grid-row:1;position:relative;}
    .cl-field-editor .field-menu-content {position:absolute;right:0;top:100%;z-index:3;width:240px;
      display:flex;flex-direction:column;gap:6px;padding:8px;background:#24262b;border:1px solid #777;
      max-height:50vh;overflow:auto;}
    .cl-field-editor .advanced-panel {width:240px;flex:none;min-height:0;overflow:auto;}
    .cl-field-editor .advanced-toggle {grid-column:3;grid-row:1;width:126px;white-space:nowrap;}
    .cl-field-editor .painting-controls .advanced-state {flex:none;width:100px;white-space:nowrap;
      overflow:hidden;text-overflow:ellipsis;}
    @media (max-width:1279px) {
      .cl-field-editor .tools {grid-template-rows:44px;}
    }
    .cl-field-editor details.group {margin:6px 0;padding-left:8px;border-left:2px solid #555;}
    .cl-field-editor details.group > * {margin:6px 0;}
    .cl-field-editor details.group > summary {font-weight:600;}
    .cl-field-editor label {display:flex;justify-content:space-between;gap:8px;align-items:center;}
    .cl-field-editor .tip-drop {border:1px dashed #888;padding:6px;font-size:12px;}
    .cl-field-editor .tip-frame {position:relative;display:inline-block;line-height:0;}
    .cl-field-editor .tip-thumbnail {position:static;display:block;border:1px solid #777;background:#000;}
    .cl-field-editor .tip-crop {position:absolute;box-sizing:border-box;border:1px solid #00ffff;pointer-events:none;}
    .cl-field-editor .tip-prepared {display:flex;flex-direction:column;align-items:flex-start;gap:4px;}
    .cl-field-editor .tip-status,.cl-field-editor .tip-help {display:block;}
    .cl-field-editor .procedural-frame {position:relative;display:inline-block;line-height:0;}
    .cl-field-editor .procedural-thumbnail {position:static;display:block;border:1px solid #777;background:#000;image-rendering:pixelated;}
    .cl-field-editor .procedural-crop {position:absolute;box-sizing:border-box;border:1px solid #00ffff;pointer-events:none;}
    .cl-field-editor .procedural-prepared {display:flex;flex-direction:column;align-items:flex-start;gap:4px;}
    .cl-field-editor .procedural-status,.cl-field-editor .procedural-help {display:block;}
    .cl-field-editor .field-strip {display:flex;align-items:center;gap:8px;overflow-x:auto;white-space:nowrap;height:48px;flex:none;scrollbar-width:thin;}
    .cl-field-editor .field-strip > * {flex:none;}
    .cl-field-editor .field-tab {display:flex;align-items:center;gap:2px;border:1px solid #555;border-radius:4px;padding:2px;}
    .cl-field-editor .field-tab.active {border-color:#79aeff;background:#2f3440;}
    .cl-field-editor .field-swatch {display:inline-block;width:10px;height:10px;margin-right:6px;border:1px solid #111;}
    .cl-field-editor .field-name {display:inline-block;max-width:160px;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;}
    .cl-field-editor .field-overlay {pointer-events:none;}
    .cl-field-editor .transfer-help,.cl-field-editor .transfer-status {display:block;}
    .cl-field-editor .transfer-status {color:#ffb5ab;}
    .cl-field-editor .field-transfer {color:#ffd27a;}
    .cl-field-editor .balance-help,.cl-field-editor .balance-status {display:block;}
    .cl-field-editor .balance-status {color:#ffb5ab;}
    .cl-field-editor .field-balance {color:#ffd27a;}
    .cl-field-editor .field-role {margin-left:6px;font-size:11px;}
    .cl-field-editor [hidden] {display:none;}
    .cl-field-editor input {width:82px;padding:6px;cursor:ew-resize;background:#16181c;color:#fff;border:1px solid #777;}
    .cl-field-editor input:not([readonly]) {cursor:text;}
    .cl-field-editor button,.cl-field-editor summary {padding:6px;cursor:pointer;}
    .cl-field-editor button[aria-pressed=true] {outline:2px solid #79aeff;}
    .cl-field-editor .status {font-size:12px;flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .cl-field-editor .profile-note {flex:none;}
    .cl-field-editor .error {color:#ffb5ab;box-sizing:border-box;height:24px;flex:none;
      line-height:24px;white-space:nowrap;text-overflow:ellipsis;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;}
    .cl-field-editor .error::-webkit-scrollbar {display:none;}
  `;
  const layout = el("div", null, dialog); layout.className = "layout";
  const top = el("div", null, layout); top.className = "bar top-bar";
  el("strong", "Influence Field Editor", top);
  const button = (parent, label, action) => {
    const b = el("button", label, parent); b.type = "button";
    b.addEventListener("click", () => { if (!busy && !maskDialog && !libraryDialog && !chooserDialog) action(); }); return b;
  };
  function edit(action) { if (stroke) return; anchor = null; action(); schedule(); }
  const undo = button(top, "Undo", () => edit(() => historyStep("undo")));
  const redo = button(top, "Redo", () => edit(() => historyStep("redo")));
  button(top, "Fit", fit);
  const fieldsView = host.createCompositionPreview ? button(top, "Fields", () => setContribution(false)) : null;
  const contributionView = host.createCompositionPreview ? button(top, "Contribution", () => setContribution(true)) : null;
  const contextChoice = host.createCompositionPreview ? el("select", null, top) : null;
  if (contextChoice) {
    contextChoice.setAttribute("aria-label", "Contribution Compose and layer");
    contextChoice.style.cssText = "max-width:220px;min-width:0"; contextChoice.hidden = true;
    contextChoice.addEventListener("change", () => { previewContext = contextChoice.value || null; schedule(); });
  }
  const status = el("span", null, top); status.className = "status";
  async function setContribution(enabled) {
    if (stroke || gesture || closed) return;
    view.contribution = enabled; const epoch = ++previewEpoch;
    previewQueue?.dispose(); previewQueue = null;
    if (previewPoll !== null) clearInterval(previewPoll);
    previewPoll = null; previewError = null; preparedState = preparedWeights = null;
    schedule();
    if (!enabled) return;
    try {
      const service = previewService ?? await host.createCompositionPreview();
      if (closed || epoch !== previewEpoch) return;
      previewService = service; previewQueue = service.createQueue(service.calculate, schedule);
      // Detect programmatic changes while the modal is idle. Reads only; unchanged snapshots do no work.
      previewPoll = setInterval(schedule, 500);
    } catch (error) { if (epoch === previewEpoch) previewError = error.message; }
    schedule();
  }
  function refreshContribution() {
    fieldsView?.setAttribute("aria-pressed", !view.contribution);
    contributionView?.setAttribute("aria-pressed", view.contribution);
    if (contextChoice) contextChoice.hidden = !view.contribution;
    if (!view.contribution || !previewQueue) return;
    if (previewField !== active.key) { previewField = active.key; previewContext = null; }
    try {
      previewSnapshot = previewService.inspect(active.key, new Map(records.map(r => [r.key, r.session.codes])), previewContext);
      if (previewContext === null && previewSnapshot.key !== null) previewContext = previewSnapshot.key;
      const options = JSON.stringify(previewSnapshot.choices.map(c => [c.key, c.label]));
      if (options !== previewOptions) {
        previewOptions = options; contextChoice.replaceChildren();
        const placeholder = el("option", "Select Compose / layer", contextChoice); placeholder.value = "";
        for (const choice of previewSnapshot.choices) { const option = el("option", choice.label, contextChoice); option.value = choice.key; }
      }
      contextChoice.value = previewSnapshot.key ?? "";
      contextChoice.title = previewSnapshot.choice?.label ?? "Choose the complete composition to inspect";
      previewQueue.update(previewSnapshot, !!stroke);
    } catch (error) {
      previewQueue.update({fingerprint: `error:${error.message}`, error: error.message});
    }
  }
  function contributionState() {
    return previewError ? {status: "unavailable", message: previewError} : previewQueue?.state ?? {status: "pending"};
  }
  button(top, "Cancel", cancel);
  const done = button(top, "Done", async () => {
    if (stroke) endStroke();
    for (const control of controls) control.commit();
    busy = true; done.disabled = true;
    try {
      if (host.fields) await host.fields.commit(records.filter(r => r.key === host.fields.openingKey || changed(r))
        .map(r => ({key: r.key, codes: r.session.codes.slice(), settings: editorSettings(r.session.settings)})));
      else await onDone(session.codes.slice(), editorSettings(session.settings));
      close();
    }
    catch (error) { message.textContent = message.title = error.message; }
    finally { busy = false; done.disabled = false; }
  });
  const strip = el("div", null, layout); strip.className = "field-strip";
  strip.setAttribute("role", "group"); strip.setAttribute("aria-label", "Fields in this session");
  const editing = el("span", null, strip); editing.className = "field-editing"; editing.setAttribute("aria-live", "polite");
  const add = host.fields ? button(strip, "Add Field…", chooseField) : null;
  if (add) add.className = "field-add";
  let tabs = [], copies = [];
  let transferRow = null, transferHelp = null, transferStatus = null, transferStrip = null, transferButtons = [];
  // Balance: partner row and strip text at the first two-field membership; the share control,
  // help and status at the first partner choice. Both are kept for the dialog's life.
  let balanceRow = null, balanceStrip = null, balanceButtons = [];
  let shareRow = null, shareControl = null, balanceHelp = null, balanceStatus = null;
  const tools = el("div", null, layout); tools.className = "tools";
  tools.setAttribute("role", "group"); tools.setAttribute("aria-label", "Painting controls");
  const paintingControls = el("div", null, tools); paintingControls.className = "painting-controls";
  const body = el("div", null, layout); body.className = "body";
  const viewport = el("div", null, body); viewport.className = "viewport";
  const reference = el("img", null, viewport); reference.className = "reference";
  reference.alt = "Session reference image"; reference.hidden = true;
  const canvas = el("canvas", null, viewport);
  const veil = el("canvas", null, viewport); veil.className = "selection-veil";
  // Exact coverage of the stamp a click here would make; display only, never field data.
  const preview = el("canvas", null, viewport); preview.className = "brush-preview";
  const grid = document.createElementNS(SVG, "svg");
  grid.classList.add("cell-grid"); grid.setAttribute("viewBox", "0 0 128 128"); viewport.append(grid);
  const gridLines = document.createElementNS(SVG, "path");
  gridLines.setAttribute("d", gridPath()); gridLines.setAttribute("fill", "none");
  gridLines.setAttribute("stroke", "#888");
  gridLines.setAttribute("shape-rendering", "crispEdges"); grid.append(gridLines);
  function selectionLayer(className, color) {
    const layer = document.createElementNS(SVG, "svg");
    layer.classList.add(className); layer.setAttribute("viewBox", "0 0 128 128"); viewport.append(layer);
    const paths = ["#111", color].map(color => {
      const path = document.createElementNS(SVG, "path"); path.setAttribute("fill", "none");
      path.setAttribute("stroke", color); path.setAttribute("shape-rendering", "crispEdges"); layer.append(path); return path;
    });
    return {layer, paths};
  }
  const selectionOutline = selectionLayer("selection-outline", "#ffd400");
  const selectionCandidate = selectionLayer("selection-candidate", "#ffffff");
  const cell = el("div", null, viewport); cell.className = "target-cell";
  const outline = document.createElementNS(SVG, "svg");
  outline.classList.add("brush-outline"); outline.setAttribute("viewBox", "0 0 128 128"); viewport.append(outline);
  const outlinePaths = ["#111", "white"].map(color => {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("fill", "none"); path.setAttribute("stroke", color); outline.append(path); return path;
  });
  const toolBar = el("div", null, paintingControls); toolBar.className = "bar";
  function setTool(tool) {
    cancelSelectionGesture();
    if (session.settings.tool !== tool || session.selectTool !== null) anchor = null;
    session.selectTool = null; session.settings.tool = tool;
    active.transferSource = null; clearTransferMessage();
    active.balancePartner = null; clearBalanceMessage(); schedule();
  }
  const paint = button(toolBar, "Paint", () => setTool("paint"));
  const erase = button(toolBar, "Erase", () => setTool("erase"));
  function number(parent, label, key, min, max, step = 1, integer = true, convert = n => n, check = null) {
    const row = el("label", label, parent);
    const control = createNumberControl({label, min, max, step, integer, value: session.settings[key],
      onChange: n => {
        if (busy) return;
        const value = convert(n), problem = check?.(value);
        // A rejected value is reported and reverted, never silently adjusted.
        if (problem) { control.setValue(session.settings[key]); message.textContent = message.title = rejection = problem; return; }
        if (rejection && message.textContent === rejection) message.textContent = message.title = rejection = "";
        session.settings[key] = value; schedule();
      }});
    row.append(control.element); controls.push(control); synced.push([control, key]); control.row = row;
    return control;
  }
  function choice(parent, label, key, options) { // Categorical: exempt from the numeric rule.
    const row = el("div", null, parent); row.className = "bar";
    el("span", label, row);
    const buttons = options.map(([value, text]) => button(row, text, () => { session.settings[key] = value; schedule(); }));
    refreshers.push(() => buttons.forEach((b, i) => b.setAttribute("aria-pressed", session.settings[key] === options[i][0])));
  }
  function toggle(parent, text, key) {
    const b = button(parent, text, () => { session.settings[key] = !session.settings[key]; schedule(); });
    refreshers.push(() => b.setAttribute("aria-pressed", session.settings[key]));
    return b;
  }
  function group(parent, title, key) { // Collapsible group; expansion is a per-user host preference.
    const details = el("details", null, parent); details.className = "group";
    details.open = host.getGroupExpanded(key);
    details.addEventListener("toggle", () => { if (!closed) host.setGroupExpanded(key, details.open); });
    return {details, heading: el("summary", title, details), title};
  }
  number(paintingControls, "Size (cells)", "size", 1, 128);
  const influenceGroup = el("div", null, paintingControls); influenceGroup.className = "influence-group";
  const influenceRow = el("div", null, influenceGroup); influenceRow.className = "influence-control";
  let influence;
  function influenceControl() {
    if (influence) {
      controls.splice(controls.indexOf(influence), 1);
      synced.splice(synced.findIndex(([control]) => control === influence), 1); influenceRow.replaceChildren();
    }
    const percent = session.settings.influenceUnit === "percent";
    influence = number(influenceRow, percent ? "Influence (%)" : "Influence (0–255)", "influence",
      0, percent ? 100 : 255, percent ? 0.1 : 1, !percent, percent ? percentToCode : n => n);
  }
  influenceControl();
  const influenceMenu = el("details", null, influenceGroup); influenceMenu.className = "influence-menu";
  const influenceSummary = el("summary", "⋯", influenceMenu);
  influenceSummary.title = "Influence units and presets";
  influenceSummary.setAttribute("aria-label", "Influence options");
  const paintingOptions = el("div", null, influenceMenu); paintingOptions.className = "painting-options";
  paintingOptions.setAttribute("role", "group"); paintingOptions.setAttribute("aria-label", "Influence options");
  function closeInfluenceMenu() { influenceMenu.open = false; }
  dialog.addEventListener("pointerdown", event => {
    if (!influenceGroup.contains(event.target)) closeInfluenceMenu();
  });
  influenceGroup.addEventListener("focusout", event => {
    if (!influenceGroup.contains(event.relatedTarget)) closeInfluenceMenu();
  });
  const exact = el("small"); exact.className = "influence-readout";
  // Influence stays visible and still sets Fill; a gradient replaces it only as Paint's target.
  const profileNote = el("small"); profileNote.className = "profile-note";
  button(paintingOptions, "% ⇄ 0–255", () => {
    influence.commit(); session.settings.influenceUnit = session.settings.influenceUnit === "percent" ? "code" : "percent";
    influenceControl(); schedule();
  });
  const chips = el("div", null, paintingOptions); chips.className = "bar";
  for (const p of [0, 25, 50, 75, 100]) button(chips, `${p}%`, () => {
    session.settings.influence = percentToCode(p); schedule();
  });
  paintingOptions.append(exact);
  number(paintingControls, "Hardness (%)", "hardness", 0, 100);
  button(paintingControls, "Clear", () => edit(() => session.operation("clear"))).title =
    "Set cells to 0: every cell, or only the selected cells while a selection is active.";
  const field = el("details", null, tools); field.className = "field-menu"; el("summary", "Field", field);
  const fieldContent = el("div", null, field); fieldContent.className = "field-menu-content";
  button(fieldContent, "Fill with Influence", () => edit(() => session.operation("fill"))).title =
    "Set cells to Influence: every cell, or only the selected cells while a selection is active.";
  button(fieldContent, "Invert", () => edit(() => session.operation("invert"))).title =
    "Replace each code with 255 − code: every cell, or only the selected cells while a selection is active.";
  const picker = el("input", null, fieldContent); picker.type = "file"; picker.accept = ".png"; picker.hidden = true;
  button(fieldContent, "Import PNG…", () => picker.click()).title =
    "Exact 128×128 grayscale field PNG, as Export PNG writes; never resized. With an active selection, only selected cells change. Other sizes: Advanced ▸ Field Tools ▸ Import Mask…";
  picker.addEventListener("change", () => { importFile(picker.files?.[0]); picker.value = ""; });
  const copyButtons = el("span", null, fieldContent); copyButtons.className = "field-copies";
  button(fieldContent, "Export PNG", async () => {
    busy = true;
    try {
      const bytes = await encodeFieldPng(session.codes);
      if (closed) return;
      const url = URL.createObjectURL(new Blob([bytes], {type: "image/png"}));
      const a = el("a", null, dialog); a.href = url; a.download = "influence-field.png"; a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { message.textContent = message.title = error.message; }
    finally { busy = false; }
  });
  const advancedToggle = button(tools, "", () => {
    if (stroke || gesture) return;
    advanced.open = !advanced.open;
    updateAdvancedPanel();
  });
  advancedToggle.className = "advanced-toggle";
  const advancedPanel = el("div", null, body); advancedPanel.className = "advanced-panel";
  const advanced = el("details", null, advancedPanel);
  advanced.id = "cl-field-editor-advanced";
  advanced.open = host.getAdvancedExpanded();
  const summary = el("summary", null, advanced);
  advancedToggle.setAttribute("aria-controls", advanced.id);
  const advancedState = el("small", null, paintingControls); advancedState.className = "advanced-state";
  function updateAdvancedPanel() {
    if (stroke || gesture) { advanced.open = !advancedPanel.hidden; return; }
    const resized = advancedPanel.hidden !== !advanced.open;
    advancedPanel.hidden = !advanced.open;
    advancedToggle.textContent = advanced.open ? "Hide Advanced" : "Show Advanced";
    advancedToggle.setAttribute("aria-expanded", advanced.open);
    if (resized) {
      if (!advanced.open) advancedToggle.focus();
      host.setAdvancedExpanded(advanced.open);
      fit(); // Deliberate panel-width change: reuse the existing Fit behavior.
    }
  }
  advancedPanel.hidden = !advanced.open;
  updateAdvancedPanel();
  advanced.addEventListener("toggle", () => { if (!closed) updateAdvancedPanel(); });
  button(advanced, "Brush Library…", async () => {
    if (libraryDialog || stroke || gesture || closed) return;
    for (const control of controls) control.commit();
    space = false; releaseCompare();
    const target = active;
    busy = true;
    try {
      const library = await host.getBrushLibrary();
      if (closed) return;
      libraryDialog = openBrushLibrary({library, currentBrush: () => ({...target.session.settings}),
        apply: prepared => {
          if (closed || active !== target) return;
          applyPreparedBrush(prepared, target.session);
          active.tipLoad = session.tip ? "ready" : "none"; active.tipError = "";
          if (session.tip) setTip(session.tip);
          clearTipMessage(); anchor = null; schedule();
        }, confirmDelete: name => window.confirm(`Delete brush preset “${name}”?`),
        onClose: () => { libraryDialog = null; dialog.focus(); }});
    } catch (error) { message.textContent = message.title = `Cannot open Brush Library: ${error.message}`; }
    finally { busy = false; }
  });
  const behavior = group(advanced, "Brush Behavior", "behavior");
  number(behavior.details, "Amount (%)", "amount", 1, 100);
  number(behavior.details, "Amount Jitter (%)", "amount_jitter", 0, 100).row.title =
    "Changes each stamp's Amount by a repeatable whole-percent amount, up to this much lower or higher (pen pressure's Amount applied first), kept within 1–100%. 0: every stamp at its Amount.";
  const buildUpRow = el("div", null, behavior.details); buildUpRow.className = "bar";
  toggle(buildUpRow, "Build-up", "build_up");
  const flow = number(behavior.details, "Flow (%)", "flow", 1, 100);
  const flowJitter = number(behavior.details, "Flow Jitter (%)", "flow_jitter", 0, 100);
  flowJitter.row.title = "Changes each Build-up stamp's Flow by a repeatable whole-percent amount, up to this much lower or higher (pen pressure's Flow applied first), kept within 1–100%. 0: every stamp at its Flow.";
  choice(behavior.details, "Spacing", "spacing", [["auto", "Auto"], ["custom", "Custom"]]);
  const spacing = number(behavior.details, "Spacing (% of Size)", "spacing_percent", 1, 1000);
  number(behavior.details, "Smoothing (%)", "smoothing", 0, 100).row.title =
    "Steadies the painted path against hand jitter; higher values follow the pointer more loosely. The stroke still ends where you release. 0: the path as drawn.";
  choice(behavior.details, "Falloff", "falloff_curve", [["smooth", "Smooth"], ["linear", "Linear"], ["sharper", "Sharper"]]);
  choice(behavior.details, "Apply", "apply_mode",
    [["normal", "Normal"], ["raise_only", "Raise Only"], ["lower_only", "Lower Only"]]);
  const restoreRow = el("div", null, behavior.details); restoreRow.className = "bar";
  const restore = button(restoreRow, "Restore", () => setTool("restore"));
  restore.title = "Paint toward the field as it was when this field joined the session";
  el("small", "Restore paints toward the field as it was when this field joined the session. Paint or Erase leaves it.", behavior.details);
  const pressureGroup = group(behavior.details, "Pen Pressure", "pressure");
  toggle(pressureGroup.details, "Use Pen Pressure", "pressure_enabled").title =
    "Read a pen's pressure while painting with Paint, Erase, Restore, Transfer or Balance. Mouse, touch and Shift-click lines always paint with the set values.";
  const pressureRow = el("div", null, pressureGroup.details); pressureRow.className = "bar";
  el("span", "Pressure changes", pressureRow);
  toggle(pressureRow, "Size", "pressure_size").title = "Lighter pressure paints a smaller stamp, down to Minimum Size and never below 1 cell.";
  toggle(pressureRow, "Amount", "pressure_amount").title = "Lighter pressure lowers how far a stamp can move cells toward the target. Amount stays the most.";
  const pressureFlow = toggle(pressureRow, "Flow", "pressure_flow");
  pressureFlow.title = "Lighter pressure builds up more slowly. Acts only with Build-up.";
  const pressureMin = number(pressureGroup.details, "Minimum Size (% of Size)", "pressure_min_size", 0, 100);
  pressureMin.row.title = "The smallest stamp light pressure paints, as a percentage of Size. 0: down to 1 cell.";
  const pressureNote = el("small", "Pen pressure changes nothing yet: choose Size or Amount, or turn on Build-up for Flow.", pressureGroup.details);
  el("small", "Pen only. Each stamp uses the pen's pressure where it lands: full pressure paints with the set value, lighter pressure with less (never below 1), and no pressure paints nothing. Mouse, touch and Shift-click lines paint with the set values.", pressureGroup.details);
  const shape = group(advanced, "Brush Shape & Transform", "shape");
  choice(shape.details, "Shape", "shape", [["disk", "Disk"], ["square", "Square"], ["diamond", "Diamond"], ["custom", "Custom"], ["procedural", "Procedural"]]);
  // E5: the imported tip and how it is read, shown while Shape is Custom or a tip is kept. The
  // file is decoded here and kept only in this node's brush settings: no upload, name or path.
  const tipGroup = group(shape.details, "Custom Tip", "tip");
  const tipActions = el("div", null, tipGroup.details); tipActions.className = "bar";
  const tipPicker = el("input", null, tipGroup.details);
  tipPicker.type = "file"; tipPicker.accept = ".png,image/png"; tipPicker.hidden = true;
  button(tipActions, "Import Tip PNG…", () => tipPicker.click());
  const clearTipButton = button(tipActions, "Clear Custom Tip", clearTip);
  clearTipButton.title = "Remove the imported tip and its reading settings from this brush. Shape stays Custom.";
  tipPicker.addEventListener("change", () => { importTip(tipPicker.files?.[0]); tipPicker.value = ""; });
  const tipDrop = el("div", "Drop a PNG here to import it as the tip", tipGroup.details); tipDrop.className = "tip-drop";
  tipDrop.addEventListener("dragover", event => { event.preventDefault(); event.stopPropagation(); });
  tipDrop.addEventListener("drop", event => {
    event.preventDefault(); event.stopPropagation(); importTip(event.dataTransfer?.files?.[0]);
  });
  // The prepared tip: read, inverted and trimmed, before crop (outlined) and transform; caption below.
  const tipPrepared = el("div", null, tipGroup.details); tipPrepared.className = "tip-prepared";
  const tipFrame = el("div", null, tipPrepared); tipFrame.className = "tip-frame";
  const thumbnail = el("canvas", null, tipFrame); thumbnail.className = "tip-thumbnail";
  thumbnail.setAttribute("aria-label", "Prepared custom tip");
  const cropBox = el("div", null, tipFrame); cropBox.className = "tip-crop";
  const tipCaption = el("small", null, tipPrepared);
  const tipReading = el("div", null, tipGroup.details);
  choice(tipReading, "Read", "tip_channel", Object.entries(TIP_CHANNELS));
  const tipToggles = el("div", null, tipReading); tipToggles.className = "bar";
  toggle(tipToggles, "Invert Tip", "tip_invert"); toggle(tipToggles, "Trim Empty Border", "tip_trim");
  const tipStatus = el("small", null, tipGroup.details); tipStatus.className = "tip-status";
  el("small", "PNG only, at most 1,024 pixels a side and 262,144 in all. Read as coverage: 255 is full, 0 none. " +
    "Hardness fades the tip's frame edge; the Value Profile still sets the target. The tip is kept with the " +
    "node's brush settings, so it adds to the workflow's size.", tipGroup.details).className = "tip-help";
  const paired = (rule, label, key) => value => { // checks one percentage of a constrained pair
    const problem = rule({...session.settings, [key]: value});
    return problem && `${problem} ${label.slice(0, -4)} ${value}% was not applied.`;
  };
  const proceduralGroup = group(shape.details, "Procedural Tip", "procedural");
  choice(proceduralGroup.details, "Type", "procedural_type", [["scatter", "Scatter"], ["noise", "Noise"]]);
  const seed = number(proceduralGroup.details, "Seed", "procedural_seed", 0, 4294967295);
  const newSeed = button(proceduralGroup.details, "New Seed", () => {
    seed.commit();
    const drawn = globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
    session.settings.procedural_seed = drawn === session.settings.procedural_seed ? (drawn + 1) % 4294967296 : drawn;
    schedule();
  });
  newSeed.title = "Pick a new random Seed. The tip is generated from the stored Seed, so typing it again reproduces this tip exactly.";
  const scatterRows = el("div", null, proceduralGroup.details), noiseRows = el("div", null, proceduralGroup.details);
  choice(scatterRows, "Particle Shape", "procedural_particle_shape",
    [["circle", "Circle"], ["rectangle", "Rectangle"], ["diamond", "Diamond"], ["trapezoid", "Trapezoid"], ["irregular", "Irregular"], ["hotdog", "Hotdog"]]);
  const ordinaryScatter = [];
  for (const [label, key, min, max, step, integer] of [
    ["Particle Grid (slots per side)", "procedural_grid", 1, 32, 1, true],
    ["Density (%)", "procedural_density", 0, 100, 1, true],
    ["Particle Size (% of slot)", "procedural_particle_size", 1, 200, 1, true],
    ["Particle Aspect (W:H)", "procedural_particle_aspect", 0.1, 10, 0.1, false],
    ["Size Jitter (±%)", "procedural_size_jitter", 0, 90, 1, true],
    ["Position Jitter (%)", "procedural_position_jitter", 0, 100, 1, true],
    ["Particle Rotation (°)", "procedural_particle_rotation", -360, 360, 1, false],
    ["Rotation Jitter (±°)", "procedural_rotation_jitter", 0, 180, 1, false],
  ]) {
    const control = number(scatterRows, label, key, min, max, step, integer);
    if (["procedural_grid", "procedural_density", "procedural_particle_size", "procedural_particle_rotation"].includes(key))
      ordinaryScatter.push(control.row);
  }
  // Build template-only controls on demand. Basic/default editor inventory is unchanged.
  let hotdogRows = null;
  function renderHotdog(s) {
    const active = isHotdog(s);
    if (active && !hotdogRows) {
      hotdogRows = el("div", null, scatterRows); hotdogRows.className = "hotdog-controls";
      number(hotdogRows, "Hotdog Count", "hotdog_count", 1, 1024);
      number(hotdogRows, "Hotdog Size (% of slot)", "procedural_particle_size", 1, 200);
      number(hotdogRows, "Spread (%)", "hotdog_spread", 0, 100);
      number(hotdogRows, "Hotdog Rotation (°)", "procedural_particle_rotation", -360, 360, 1, false);
      toggle(hotdogRows, "Invert Template", "hotdog_invert");
      el("small", "Count is exact planned motifs. One is always centred. Spread 0% packs centres together; 100% spreads them across the grid. " +
        "Hotdog Size scales each template relative to a slot; Brush Size scales the whole stamp. " +
        "Position Jitter moves multiple motifs; set it and Size Jitter to 0 for orderly repeats. " +
        "Invert Template swaps motif coverage inside each template square. Mirror H/V and Brush Shape Rotation transform the completed stamp.", hotdogRows);
    }
    if (hotdogRows) hotdogRows.hidden = !active;
    for (const row of ordinaryScatter) row.hidden = active;
    proceduralInvert.hidden = active;
    proceduralHelp.hidden = active;
  }
  number(noiseRows, "Frequency (periods across tip)", "procedural_frequency", 1, 16);
  number(noiseRows, "Octaves", "procedural_octaves", 1, 4);
  number(noiseRows, "Persistence (%)", "procedural_persistence", 0, 100);
  for (const [label, key] of [["Noise Low (%)", "procedural_noise_low"], ["Noise High (%)", "procedural_noise_high"]])
    number(noiseRows, label, key, 0, 100, 1, true, n => n, paired(proceduralError, label, key));
  const proceduralInvert = toggle(proceduralGroup.details, "Invert Procedural Tip", "procedural_invert");
  const proceduralPrepared = el("div", null, proceduralGroup.details); proceduralPrepared.className = "procedural-prepared";
  const proceduralFrame = el("div", null, proceduralPrepared); proceduralFrame.className = "procedural-frame";
  const proceduralThumbnail = el("canvas", null, proceduralFrame); proceduralThumbnail.className = "procedural-thumbnail";
  proceduralThumbnail.setAttribute("aria-label", "Generated procedural tip");
  const proceduralCrop = el("div", null, proceduralFrame); proceduralCrop.className = "procedural-crop";
  el("small", "Generated tip 256×256 · kept as settings, not as an image", proceduralPrepared);
  const proceduralStatus = el("small", null, proceduralGroup.details); proceduralStatus.className = "procedural-status";
  const proceduralHelp = el("small", "Generation is the same every time; only settings are kept. Grid sets slots per side, Density the occupied share, " +
    "and Particle Size the longer side as a percentage of a slot. Every stamp uses the same tip: Auto spacing makes streaks. " +
    "Use Brush Behavior ▸ Spacing Custom, 100% or more, for separate stamps. Hardness fades the square edge; " +
    "the Value Profile still sets the target.", proceduralGroup.details);
  proceduralHelp.className = "procedural-help";
  let shownProceduralMask = null;
  number(shape.details, "Scale X", "scale_x", 0.1, 10, 0.1, false);
  number(shape.details, "Scale Y", "scale_y", 0.1, 10, 0.1, false);
  number(shape.details, "Rotation (°)", "rotation_degrees", -360, 360, 1, false);
  const follow = el("div", null, shape.details); follow.className = "bar";
  toggle(follow, "Follow Stroke Direction", "follow_direction").title =
    "Turns each stamp toward the direction the stroke travels, measured along the unscattered path; Rotation and Angle Jitter then turn it further. Moving right is 0°. The first stamp, before the stroke has a direction, uses Rotation alone. A plain round Disk looks the same at any angle, so it is not turned.";
  number(shape.details, "Angle Jitter (±°)", "angle_jitter", 0, 180).row.title =
    "Turns each stamp by a repeatable whole-degree amount, up to this many degrees either side of Rotation. 0: every stamp at Rotation. A plain round Disk looks the same at any angle, so it is not turned.";
  number(shape.details, "Size Jitter (%)", "size_jitter", 0, 100).row.title =
    "Resizes each stamp by a repeatable whole-percent amount, up to this much smaller or larger than its size (pen pressure and Minimum Size applied first), never below 1 cell. Spacing follows the unjittered size. 0: every stamp at its size.";
  number(shape.details, "Scatter (%)", "scatter", 0, 200).row.title =
    "Moves each stamp's centre by a repeatable amount in any direction, up to this percentage of its size (pen pressure, Minimum Size and Size Jitter applied first). Spacing and pressure follow the unscattered path. 0: every stamp on the path.";
  const jitterSeed = number(shape.details, "Jitter Seed", "jitter_seed", 0, 4294967295);
  jitterSeed.row.title = "Picks which repeatable pattern Angle, Size, Amount and Flow Jitter and Scatter draw. The stroke's path and spacing stay the same. 0: the original pattern.";
  const newJitterSeed = button(shape.details, "New Jitter Seed", () => {
    jitterSeed.commit();
    const drawn = globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
    session.settings.jitter_seed = drawn === session.settings.jitter_seed ? (drawn + 1) % 4294967296 : drawn;
    schedule();
  });
  newJitterSeed.title = "Pick a new random Jitter Seed. Strokes use the stored Seed, so typing it again reproduces the same jitter exactly.";
  const mirrors = el("div", null, shape.details); mirrors.className = "bar";
  toggle(mirrors, "Mirror H", "mirror_horizontal"); toggle(mirrors, "Mirror V", "mirror_vertical");
  for (const [label, key] of [["Crop Left (%)", "crop_left"], ["Crop Right (%)", "crop_right"],
    ["Crop Top (%)", "crop_top"], ["Crop Bottom (%)", "crop_bottom"]]) {
    number(shape.details, label, key, 0, 99, 1, true, n => n, paired(cropError, label, key));
  }
  el("small", "Order: crop, mirror, scale (the cropped area's longer side fits Size), rotate clockwise, place. " +
    "A custom tip is read, inverted and trimmed first.", shape.details);
  // E4: what each stamp paints across its footprint. Uniform keeps Influence (Paint) as before.
  const valueProfile = group(advanced, "Value Profile", "profile");
  choice(valueProfile.details, "Profile", "value_profile",
    [["uniform", "Uniform"], ["linear", "Linear Gradient"], ["radial", "Radial Gradient"], ["square", "Square Gradient"]]);
  const inactive = el("small", null, valueProfile.details);
  const gradientStart = number(valueProfile.details, "Start Value (0–255)", "gradient_start", 0, 255);
  const gradientEnd = number(valueProfile.details, "End Value (0–255)", "gradient_end", 0, 255);
  const swapRow = el("div", null, valueProfile.details); swapRow.className = "bar";
  button(swapRow, "Swap Start/End", () => {
    gradientStart.commit(); gradientEnd.commit();
    const s = session.settings;
    [s.gradient_start, s.gradient_end] = [s.gradient_end, s.gradient_start]; schedule();
  }).title = "Exchange the Start and End values. The geometry stays as it is.";
  const gradientCurve = number(valueProfile.details, "Curve (exponent)", "gradient_curve", 0.1, 10, 0.1, false);
  const ordered = (label, key, max) =>
    number(valueProfile.details, label, key, 0, max, 1, true, n => n, paired(profileError, label, key));
  const linearRows = [number(valueProfile.details, "Gradient Angle (°)", "gradient_angle", -360, 360, 1, false),
    ordered("Start Position (%)", "gradient_start_position", 100), ordered("End Position (%)", "gradient_end_position", 100)];
  const centredRows = [number(valueProfile.details, "Center X (%)", "gradient_center_x", 0, 100),
    number(valueProfile.details, "Center Y (%)", "gradient_center_y", 0, 100),
    ordered("Inner (%)", "gradient_inner", 300), ordered("Outer (%)", "gradient_outer", 300),
    number(valueProfile.details, "Aspect X", "gradient_aspect_x", 0.1, 10, 0.1, false),
    number(valueProfile.details, "Aspect Y", "gradient_aspect_y", 0.1, 10, 0.1, false),
    number(valueProfile.details, "Gradient Rotation (°)", "gradient_rotation", -360, 360, 1, false)];
  const gradientHelp = el("small", null, valueProfile.details);
  const reset = button(paintingControls, "Reset Brush", () => {
    if (["restore", "transfer", "balance"].includes(session.settings.tool)) { session.settings.tool = "paint"; anchor = null; }
    active.transferSource = null; clearTransferMessage();
    active.balancePartner = null; clearBalanceMessage(); active.balanceShare = BALANCE_DEFAULT_SHARE;
    Object.assign(session.settings, BRUSH_DEFAULTS, {amount: 100}); schedule();
  });
  reset.title = "Return Amount and every Brush Behavior (Pen Pressure included), Brush Shape & Transform (with how a custom tip is read and every Procedural Tip setting, Seed included) and " +
    "Value Profile setting to its default. An imported custom tip is kept; Clear Custom Tip removes it.";
  const fieldTools = group(advanced, "Field Tools", "fieldTools");
  el("div", "Selection", fieldTools.details);
  const selectionTools = ["rectangle", "ellipse"].map(tool => button(fieldTools.details,
    tool === "rectangle" ? "Rectangle Select" : "Ellipse Select", () => {
      if (session.selectTool !== tool) { cancelSelectionGesture(); anchor = null; }
      session.selectTool = tool; schedule();
    }));
  const selectionModes = el("div", "Mode", fieldTools.details); selectionModes.className = "bar";
  const modeButtons = SELECTION_MODES.map(mode => button(selectionModes, mode[0].toUpperCase() + mode.slice(1), () => {
    session.selectionMode = mode; schedule();
  }));
  button(fieldTools.details, "Select All", () => changeSelection(selectAll()));
  button(fieldTools.details, "Invert Selection", () => changeSelection(invertSelection(session.selection)));
  const clearSelection = button(fieldTools.details, "Clear Selection", () => {
    session.selection = null; clearFieldToolsMessage(); schedule();
  });
  el("small", "Drag on the field to select cells. Rectangle takes every cell from the first to the last; Ellipse takes the cells whose centres lie in the ellipse inside that rectangle. While a selection is active, strokes, Clear, Fill, Invert and imports change only selected cells. Undo never changes the selection. Selections end when the editor closes.", fieldTools.details);
  el("div", "Transform Whole Field", fieldTools.details);
  const transformButtons = FIELD_TRANSFORMS.map((name, i) => button(fieldTools.details, TRANSFORM_LABELS[i], () => edit(() => session.transform(name))));
  el("small", "Moves every cell exactly; codes are unchanged. Unavailable while a selection is active: Clear Selection first. For other angles, scaling or offsets, use the Field Transform node.", fieldTools.details);
  el("div", "Import Mask", fieldTools.details);
  const maskPicker = el("input", null, fieldTools.details); maskPicker.type = "file"; maskPicker.accept = "image/png"; maskPicker.hidden = true;
  button(fieldTools.details, "Import Mask…", () => { if (!gesture && !stroke && !closed && !libraryDialog) maskPicker.click(); });
  maskPicker.addEventListener("change", () => { importMask(maskPicker.files?.[0]); maskPicker.value = ""; });
  el("small", "PNG up to 4,096 pixels a side (16,777,216 in all) and 33,554,432 bytes, reduced or enlarged to 128×128 by exact area averaging, with a preview before anything changes. Field ▸ Import PNG… reads an exact 128×128 field PNG unchanged.", fieldTools.details);
  el("div", "View", advanced);
  const referencePicker = el("input", null, advanced);
  referencePicker.type = "file"; referencePicker.accept = "image/*"; referencePicker.hidden = true;
  button(advanced, "Load Reference Image…", () => referencePicker.click());
  referencePicker.addEventListener("change", () => { loadReference(referencePicker.files?.[0]); referencePicker.value = ""; });
  const referenceDrop = el("div", "Drop reference image here (session only; stretched to full field)", advanced);
  referenceDrop.className = "reference-drop";
  referenceDrop.addEventListener("dragover", event => { event.preventDefault(); event.stopPropagation(); });
  referenceDrop.addEventListener("drop", event => {
    event.preventDefault(); event.stopPropagation(); loadReference(event.dataTransfer?.files?.[0]);
  });
  button(advanced, "Remove Reference", clearReference);
  const opacityRow = el("label", "Reference Opacity (%)", advanced);
  const opacity = createNumberControl({label: "Reference Opacity (%)", value: 50, min: 0, max: 100,
    onChange: n => { view.referenceOpacity = n; schedule(); }});
  opacityRow.append(opacity.element); controls.push(opacity);
  const gridToggle = button(advanced, "Grid (at ≥8 px/cell)", () => { view.grid = !view.grid; schedule(); });
  const heatToggle = button(advanced, "Heat View", () => { view.heat = !view.heat; schedule(); });
  const compare = button(advanced, "Hold to Compare", () => {});
  compare.title = "Hold to reveal reference. Keyboard: focus this button and hold Space or Enter.";
  compare.addEventListener("pointerdown", event => {
    if (busy || !referenceUrl || event.button !== 0) return;
    event.preventDefault(); compare.focus(); compare.setPointerCapture(event.pointerId);
    comparePointer = event.pointerId; view.comparing = true; schedule();
  });
  function releaseCompare() { comparePointer = null; compareKey = null; view.comparing = false; schedule(); }
  compare.addEventListener("pointerup", event => {
    if (comparePointer !== event.pointerId) return;
    releaseCompare(); compare.releasePointerCapture(event.pointerId);
  });
  for (const name of ["pointercancel", "lostpointercapture", "blur"]) compare.addEventListener(name, releaseCompare);
  button(advanced, "Reset View", () => { clearReference(); Object.assign(view, createViewSession()); setContribution(false); schedule(); });
  el("small", "Alt-click: sample field Influence. Shift-click: line from last stroke endpoint. Drop field PNGs on canvas.", advanced);
  const message = el("div", null, layout); message.className = "error"; message.setAttribute("role", "alert");
  message.tabIndex = 0; // Keyboard users can scroll the complete, single-line error.

  // One eligibility check for every membership operation; asynchronous work stays field-bound.
  function canSwitch() { return !closed && !busy && !stroke && !gesture && !maskDialog && !libraryDialog && !chooserDialog; }
  function validSource(r) {
    return r.transferSource !== null && r.transferSource !== r && records.includes(r.transferSource) && isAvailable(r.transferSource);
  }
  function settleSource(r) { if (r.transferSource !== null && !validSource(r)) r.transferSource = null; }
  function transferRefusal() {
    if (session.settings.tool !== "transfer") return "";
    settleSource(active);
    if (records.length < 2) return "Transfer needs another field in this session. Add Field…, or choose Paint.";
    if (active.transferSource === null) return "Choose a field to transfer from: Advanced ▸ Brush Behavior ▸ Transfer from…";
    if (!isAvailable(active)) return `Cannot transfer into ${active.label}: it is no longer in this graph.`;
    return "";
  }
  function chooseTransferSource(r) {
    if (!canSwitch() || r === active || !records.includes(r) || !isAvailable(r)) return;
    if (session.settings.tool !== "transfer" || active.transferSource !== r || session.selectTool !== null) anchor = null;
    session.selectTool = null; session.settings.tool = "transfer"; active.transferSource = r;
    active.balancePartner = null;
    r.visible = true; clearTransferMessage(); clearBalanceMessage(); schedule();
  }
  function showTransferMessage(text, refusal = false) {
    message.textContent = message.title = text; transferMessage = {text, refusal};
  }
  function showTransferNote(text) { showTransferMessage(text); transferMessage.note = true; }
  function clearTransferMessage() {
    if (transferMessage && message.textContent === transferMessage.text) message.textContent = message.title = "";
    transferMessage = null;
  }
  // Balance's partner: like a Transfer source, an invalid one is cleared, never replaced.
  function validPartner(r) {
    return r.balancePartner !== null && r.balancePartner !== r && records.includes(r.balancePartner) && isAvailable(r.balancePartner);
  }
  function settlePartner(r) { if (r.balancePartner !== null && !validPartner(r)) r.balancePartner = null; }
  function balanceRefusal() {
    if (session.settings.tool !== "balance") return "";
    settlePartner(active);
    if (records.length < 2) return "Balance needs another field in this session. Add Field…, or choose Paint.";
    if (active.balancePartner === null) return "Choose a field to balance with: Advanced ▸ Brush Behavior ▸ Balance with…";
    if (!isAvailable(active)) return `Cannot balance ${active.label}: it is no longer in this graph.`;
    return "";
  }
  function chooseBalancePartner(r) {
    if (!canSwitch() || r === active || !records.includes(r) || !isAvailable(r)) return;
    if (session.settings.tool !== "balance" || active.balancePartner !== r || session.selectTool !== null) anchor = null;
    session.selectTool = null; session.settings.tool = "balance"; active.balancePartner = r; active.transferSource = null;
    r.visible = true; ensureBalanceControls(); clearBalanceMessage(); clearTransferMessage(); schedule();
  }
  function ensureBalanceControls() {
    if (shareRow) return;
    shareRow = el("label", "Active Share (%)", behavior.details); shareRow.className = "balance-share";
    shareControl = createNumberControl({label: "Active Share (%)", value: active.balanceShare, min: 0, max: 100,
      onChange: n => { if (busy) return; active.balanceShare = n; schedule(); }});
    shareRow.append(shareControl.element); controls.push(shareControl);
    balanceHelp = el("small", "Balance moves influence between this field and its partner, in either direction, until this field holds its Active Share of their total at each cell. Each cell's total of the two fields stays the same; where 0–255 cannot hold that share, Balance stops at the nearest split that fits. Amount is the share of the remaining distance that one stroke moves. Shape, Size, Hardness, Spacing, Build-up, Flow, pen pressure and this field's selection apply; Value Profile, Apply and Influence do not.", behavior.details);
    balanceHelp.className = "balance-help";
    balanceStatus = el("small", null, behavior.details); balanceStatus.className = "balance-status";
  }
  function showBalanceMessage(text, refusal = false) {
    message.textContent = message.title = text; balanceMessage = {text, refusal};
  }
  function showBalanceNote(text) { showBalanceMessage(text); balanceMessage.note = true; }
  function clearBalanceMessage() {
    if (balanceMessage && message.textContent === balanceMessage.text) message.textContent = message.title = "";
    balanceMessage = null;
  }
  function historyStep(kind) {
    // The kind is read before the step: a successful step changes the top entry.
    const word = links.kindOf(kind, active) === "balance" ? "Balance" : "Transfer";
    const show = word === "Balance" ? showBalanceMessage : showTransferMessage;
    const result = links.step(kind, active), action = kind === "undo" ? "Undo" : "Redo";
    if (result.state === "single" || result.state === "linked") { clearTransferMessage(); clearBalanceMessage(); }
    else if (result.state === "blocked") (word === "Balance" ? showBalanceNote : showTransferNote)(kind === "undo"
      ? `Undo ${word}: first undo the later edits of ${result.partner.label}.`
      : `Redo ${word}: first redo the earlier edits of ${result.partner.label}.`);
    else if (result.state === "broken") show(`${action} refused: a ${word} history link is inconsistent (${result.reason}). Nothing was changed.`);
    else if (result.state === "failed") show(`${action} stopped: an internal check failed. Nothing was changed.`);
  }
  function switchTo(r) {
    const unit = session.settings.influenceUnit;
    active = r; session = r.session;
    anchor = endpoint = null; message.textContent = message.title = "";
    rejection = ""; tipMessage = fieldToolsMessage = transferMessage = balanceMessage = null;
    settleSource(r); settlePartner(r);
    if (session.settings.influenceUnit !== unit) influenceControl();
    schedule();
  }
  function activate(r) {
    if (!canSwitch() || r === active || !records.includes(r) || !isAvailable(r)) return;
    for (const control of controls) control.commit();
    switchTo(r);
  }
  async function chooseField() {
    if (!canSwitch() || records.length >= MAX_SESSION_FIELDS) return;
    busy = true; message.textContent = message.title = "Reading fields…";
    try {
      const items = await host.fields.candidates();
      if (closed) return;
      message.textContent = message.title = "";
      chooserDialog = openFieldChooser({items, choose: addField,
        onClose: () => { chooserDialog = null; if (!closed) dialog.focus(); }});
    } catch (error) { message.textContent = message.title = error.message; }
    finally { busy = false; }
  }
  async function addField(item) {
    if (!canSwitch() || records.length >= MAX_SESSION_FIELDS || records.some(r => r.key === item.key)) return;
    busy = true;
    try {
      const joined = await host.fields.join(item.key);
      if (closed) { host.fields.leave(joined.key); return; }
      const r = record(joined, nextColorSlot(records.map(r => r.slot)));
      records.push(r); rebuildMembershipDom(); loadStoredTip(r); schedule();
    } catch (error) { message.textContent = message.title = `Cannot add ${item.label}: ${error.message}`; }
    finally { busy = false; }
  }
  function removeField(r) {
    if (!canSwitch() || records.length < 2 || !records.includes(r)) return;
    if (changed(r) && host.confirmRemove && !host.confirmRemove(r.label)) return;
    for (const control of controls) control.commit();
    const index = records.indexOf(r), next = activeIndexAfterRemoval(records.length, index, records.indexOf(active));
    records.splice(index, 1); host.fields?.leave(r.key);
    for (const other of records) if (other.transferSource === r) other.transferSource = null;
    for (const other of records) if (other.balancePartner === r) other.balancePartner = null;
    r.transferSource = null; r.balancePartner = null; links.forget(r);
    if (r === active) switchTo(records[next]);
    r.session.selection = null; r.session.selectTool = null;
    r.overlay?.remove(); r.overlay = null;
    rebuildMembershipDom(); schedule();
  }
  function copyFrom(r) {
    if (!canSwitch() || r === active || !records.includes(r) || !isAvailable(r)) return;
    edit(() => { session.replace("Copy Field", withinSelection(session.codes, r.session.codes, session.selection)); message.textContent = message.title = ""; });
  }
  function rebuildMembershipDom() {
    if (records.length >= 2 && !transferRow) {
      transferRow = el("div"); transferRow.className = "bar transfer-sources";
      transferHelp = el("small", "Transfer moves influence from the chosen field into the field you are editing, at the same cells. Amount is the share of what can move that one stroke moves. Shape, Size, Hardness, Spacing, Build-up, Flow, pen pressure and this field's selection apply; Value Profile, Apply and Influence do not.");
      transferHelp.className = "transfer-help";
      transferStatus = el("small"); transferStatus.className = "transfer-status";
      const children = [...behavior.details.children], index = children.indexOf(pressureGroup.details);
      behavior.details.replaceChildren(...children.slice(0, index), transferRow, transferHelp, transferStatus, ...children.slice(index));
      transferStrip = el("span"); transferStrip.className = "field-transfer";
    }
    // Balance follows Pen Pressure, so the retained Transfer and Pen Pressure positions hold.
    if (records.length >= 2 && !balanceRow) {
      balanceRow = el("div", null, behavior.details); balanceRow.className = "bar balance-partners";
      balanceStrip = el("span"); balanceStrip.className = "field-balance";
    }
    tabs = []; copies = []; transferButtons = []; balanceButtons = [];
    strip.replaceChildren(editing, profileNote, ...(transferStrip ? [transferStrip] : []), ...(balanceStrip ? [balanceStrip] : []));
    copyButtons.replaceChildren();
    transferRow?.replaceChildren(); balanceRow?.replaceChildren();
    if (records.length >= 2) for (const r of records) {
      const tab = el("div", null, strip); tab.className = "field-tab";
      const select = button(tab, "", () => activate(r)); select.className = "field-select";
      const swatch = el("span", null, select); swatch.className = "field-swatch";
      swatch.style.background = `rgb(${OVERLAY_COLORS[r.slot].join(",")})`; swatch.setAttribute("aria-hidden", "true");
      const name = el("span", r.label, select); name.className = "field-name";
      const mark = el("span", null, select); mark.className = "field-mark"; mark.setAttribute("aria-hidden", "true");
      const role = el("span", null, select); role.className = "field-role";
      const show = button(tab, "Show", () => { r.visible = !r.visible; schedule(); }); show.className = "field-show";
      show.title = "Show this field as a coloured overlay while another field is edited.";
      const remove = button(tab, "×", () => removeField(r)); remove.className = "field-remove";
      remove.title = `Remove ${r.label} from this session`; remove.setAttribute("aria-label", remove.title);
      tabs.push({r, tab, select, name, mark, role, show});
      const copy = button(copyButtons, `Copy from ${r.label}`, () => copyFrom(r)); copies.push({r, copy});
      const from = button(transferRow, `Transfer from ${r.label}`, () => chooseTransferSource(r));
      from.title = `Move influence from ${r.label} into this field where you paint. Each cell's total of the two fields stays the same. One undo step in both fields.`;
      transferButtons.push({r, from});
      const partner = button(balanceRow, `Balance with ${r.label}`, () => chooseBalancePartner(r));
      partner.title = `Move influence between this field and ${r.label}, in either direction, toward this field's Active Share of their total where you paint. Each cell's total of the two fields stays the same. One undo step in both fields.`;
      balanceButtons.push({r, partner});
      if (!r.overlay) { r.overlay = el("canvas"); r.overlay.className = "field-overlay"; r.overlay.width = r.overlay.height = 128; }
    }
    else for (const r of records) { r.overlay?.remove(); r.overlay = null; r.shownCodes = null; }
    if (add) strip.append(add);
    viewport.replaceChildren(reference, canvas, ...records.flatMap(r => r.overlay ? [r.overlay] : []), veil, preview, grid,
      selectionOutline.layer, selectionCandidate.layer, cell, outline);
  }
  function renderFields() {
    const moving = session.settings.tool === "transfer", source = active.transferSource;
    const balancing = session.settings.tool === "balance", partner = active.balancePartner;
    editing.textContent = `Editing: ${active.label}${isAvailable(active) ? "" : " (unavailable)"}`;
    if (add) {
      add.disabled = records.length >= MAX_SESSION_FIELDS;
      add.title = add.disabled ? "A session holds at most 4 fields. Remove one to add another."
        : "Add another Painted Field node from this graph. It joins as a visible reference; select its tab to edit it.";
    }
    for (const {r, tab, select, name, mark, role, show} of tabs) {
      const available = isAvailable(r), dirty = changed(r);
      tab.className = r === active ? "field-tab active" : "field-tab";
      select.setAttribute("aria-pressed", r === active); select.disabled = !available;
      select.title = r.label + (dirty ? " · changed" : "") + (available ? "" : " · no longer in this graph");
      role.textContent = moving && source === r ? "source" : balancing && partner === r ? "partner" : "";
      if (role.textContent) select.title += moving ? " · transfer source" : " · balance partner";
      name.textContent = r.label + (available ? "" : " (unavailable)"); mark.textContent = dirty ? "●" : "";
      show.hidden = r === active; show.setAttribute("aria-pressed", r.visible);
    }
    if (transferRow) {
      transferRow.hidden = transferHelp.hidden = records.length < 2;
      const refusal = transferRefusal();
      transferStatus.hidden = !refusal; transferStatus.textContent = refusal;
      transferStrip.hidden = !moving;
      const text = moving ? source ? `Transfer: ${source.label} → ${active.label}${source.visible ? "" : " · source hidden"}` : "Transfer: no source field" : "";
      if (transferStrip.textContent !== text) transferStrip.textContent = text;
      for (const {r, from} of transferButtons) {
        from.hidden = r === active || !isAvailable(r) || records.length < 2;
        from.setAttribute("aria-pressed", moving && source === r);
      }
    }
    if (balanceRow) {
      balanceRow.hidden = records.length < 2;
      balanceStrip.hidden = !balancing;
      const share = active.balanceShare;
      const text = balancing ? partner ? `Balance: ${active.label} ↔ ${partner.label} · ${share}:${100 - share}${partner.visible ? "" : " · partner hidden"}`
        : "Balance: no partner field" : "";
      if (balanceStrip.textContent !== text) balanceStrip.textContent = text;
      for (const {r, partner: choice} of balanceButtons) {
        choice.hidden = r === active || !isAvailable(r) || records.length < 2;
        choice.setAttribute("aria-pressed", balancing && partner === r);
      }
    }
    if (shareRow) {
      shareRow.hidden = balanceHelp.hidden = !balancing;
      const refusal = balanceRefusal();
      balanceStatus.hidden = !refusal; balanceStatus.textContent = refusal;
      if (shareControl.element.readOnly) shareControl.setValue(active.balanceShare);
    }
    for (const {r, copy} of copies) {
      copy.hidden = r === active; copy.disabled = !isAvailable(r);
      copy.title = copy.disabled ? `${r.label} is no longer in this graph.`
        : "Replace this field's cells with that field's current cells: every cell, or only the selected cells while a selection is active. One undo step.";
    }
    for (const r of records) if (r.overlay) {
      r.overlay.style.transform = canvas.style.transform;
      r.overlay.hidden = r === active || !r.visible || view.comparing || view.contribution;
      if (!r.overlay.hidden && r.shownCodes !== r.session.codes) {
        const context = r.overlay.getContext("2d"), pixels = context.createImageData(128, 128);
        pixels.data.set(overlayPixels(r.session.codes, OVERLAY_COLORS[r.slot]));
        context.putImageData(pixels, 0, 0); r.shownCodes = r.session.codes;
      }
    }
  }

  function render() {
    frame = null;
    if (closed) return;
    settleSource(active); settlePartner(active);
    if (stroke) {
      try {
        session.codes = stroke.result();
        if (transfer) transfer.source.session.codes = transferSource(transfer.sourceBefore, stroke.before, session.codes);
        if (balance) balance.partner.session.codes = balancePartner(balance.partnerBefore, stroke.before, session.codes, balance.target);
      } catch (error) {
        if (transfer) { abortStroke(); showTransferMessage("Transfer stopped: an internal check failed. Nothing was changed."); }
        else if (balance) { abortStroke(); showBalanceMessage("Balance stopped: an internal check failed. Nothing was changed."); }
        else throw error;
      }
    }
    refreshContribution();
    if (view.contribution) {
      const state = contributionState();
      if (state !== preparedState) { preparedWeights = drawContribution(canvas, state); preparedState = state; }
    } else { drawCodes(canvas, session.codes, view.heat); preparedState = preparedWeights = null; }
    for (const layer of [canvas, veil, preview, reference, grid, selectionOutline.layer, selectionCandidate.layer, outline])
      layer.style.transform = `translate(${panX}px,${panY}px) scale(${zoom})`;
    renderFields();
    const display = displayState(view, !!referenceUrl);
    canvas.style.opacity = String(view.contribution && !view.comparing ? 1 : display.fieldOpacity);
    reference.style.opacity = String(display.referenceOpacity);
    grid.style.display = gridVisible(view.grid, zoom) && !view.comparing ? "" : "none";
    gridLines.setAttribute("stroke-width", String(1 / zoom)); // One screen pixel under the shared CSS scale.
    gridToggle.setAttribute("aria-pressed", view.grid); heatToggle.setAttribute("aria-pressed", view.heat);
    compare.setAttribute("aria-pressed", view.comparing); compare.disabled = !referenceUrl;
    if (opacity.element.readOnly) opacity.setValue(view.referenceOpacity);
    const brush = session.settings;
    for (const [control, key] of synced)
      if (key !== "influence" && control.element.readOnly) control.setValue(brush[key]);
    if (influence.element.readOnly) influence.setValue(brush.influenceUnit === "percent"
      ? Math.round(brush.influence * 1000 / 255) / 10 : brush.influence);
    exact.textContent = `${brush.influence} / 255 · ${(brush.influence * 100 / 255).toFixed(1)}%`;
    paint.setAttribute("aria-pressed", session.selectTool === null && brush.tool === "paint");
    erase.setAttribute("aria-pressed", session.selectTool === null && brush.tool === "erase");
    restore.setAttribute("aria-pressed", session.selectTool === null && brush.tool === "restore");
    for (const refresh of refreshers) refresh();
    flow.row.hidden = flowJitter.row.hidden = !brush.build_up; spacing.row.hidden = brush.spacing !== "custom";
    // Only the chosen profile's rows show; Radial and Square share theirs.
    const kind = brush.value_profile, gradient = kind !== "uniform", painting = brush.tool === "paint";
    for (const control of [gradientStart, gradientEnd, gradientCurve]) control.row.hidden = !gradient;
    swapRow.hidden = gradientHelp.hidden = !gradient;
    for (const control of linearRows) control.row.hidden = kind !== "linear";
    for (const control of centredRows) control.row.hidden = kind !== "radial" && kind !== "square";
    gradientHelp.textContent = `${GRADIENT_HELP[kind === "linear" ? "linear" : "centred"]} ${GRADIENT_HELP.both}`;
    inactive.hidden = !gradient || painting;
    inactive.textContent = brush.tool === "erase" ? "Inactive: Erase targets 0. The gradient applies to Paint."
      : brush.tool === "transfer" ? "Inactive: Transfer moves influence from its source field. The gradient applies to Paint."
      : brush.tool === "balance" ? "Inactive: Balance moves this field and its partner toward the set share. The gradient applies to Paint."
      : "Inactive: Restore targets the field as it was when this field joined the session. The gradient applies to Paint.";
    profileNote.hidden = !gradient || !painting;
    if (gradient) profileNote.textContent =
      `Paint targets ${GRADIENTS[kind]} ${brush.gradient_start}→${brush.gradient_end} (Value Profile), not Influence.`;
    profileNote.title = profileNote.textContent;
    const procedural = brush.shape === "procedural" ? proceduralMask(brush) : null;
    const condition = tipCondition(), badges = brushBadges(brush, condition, procedural?.empty ? "empty" : "ready", active.balanceShare);
    // A refusal no longer describing the brush (now ready, another condition, or not Custom) is cleared.
    if (tipMessage?.refusal && tipMessage.text !== tipRefusal()) clearTipMessage();
    if (transferMessage?.refusal && transferMessage.text !== transferRefusal()) clearTransferMessage();
    if (balanceMessage?.refusal && balanceMessage.text !== balanceRefusal()) clearBalanceMessage();
    const note = owner => owner?.note && message.textContent === owner.text;
    message.style.color = note(transferMessage) || note(balanceMessage) ? "#cfd8e3" : "";
    renderTip(brush, condition);
    renderProcedural(brush, procedural);
    behavior.heading.textContent = [behavior.title, ...badges.behavior].join(" · ");
    const pressureNames = pressureLabels(brush);
    pressureGroup.heading.textContent = ["Pen Pressure", ...(brush.pressure_enabled ? (pressureNames.length ? pressureNames : ["no effect"]) : [])].join(" · ");
    pressureRow.hidden = !brush.pressure_enabled; pressureFlow.hidden = !brush.build_up;
    pressureNote.hidden = !brush.pressure_enabled || pressureNames.length > 0;
    pressureMin.row.hidden = !brush.pressure_enabled || !brush.pressure_size;
    shape.heading.textContent = [shape.title, ...badges.shape].join(" · ");
    valueProfile.heading.textContent = [valueProfile.title, ...badges.profile].join(" · ");
    const selected = selectionStats(session.selection), selectionBadges = [];
    const toolName = session.selectTool === "rectangle" ? "Rectangle Select" : "Ellipse Select";
    if (session.selectTool !== null) selectionBadges.push(toolName);
    if (session.selection !== null) selectionBadges.push(`Selection ${selected.count} cells`);
    fieldTools.heading.textContent = [fieldTools.title, ...selectionBadges].join(" · ");
    summary.textContent = ["Advanced", ...badges.behavior, ...badges.shape, ...badges.profile, ...selectionBadges].join(" · ");
    selectionTools.forEach((b, i) => b.setAttribute("aria-pressed", session.selectTool === ["rectangle", "ellipse"][i]));
    modeButtons.forEach((b, i) => b.setAttribute("aria-pressed", session.selectionMode === SELECTION_MODES[i]));
    clearSelection.disabled = session.selection === null;
    for (const b of transformButtons) {
      b.disabled = session.selection !== null; b.title = b.disabled ? TRANSFORM_DISABLED : "";
    }
    viewport.style.cursor = session.selectTool !== null ? "crosshair" : "";
    drawSelection();
    if (view.grid || view.heat || view.referenceOpacity !== 50 || referenceUrl) summary.textContent += " · View modified";
    advancedState.textContent = advancedState.title = summary.textContent;
    advancedState.hidden = summary.textContent === "Advanced";
    reset.hidden = !badges.behavior.length && !badges.shape.length && !badges.profile.length;
    undo.disabled = !session.history.undoEntries.length; redo.disabled = !session.history.redoEntries.length;
    const stats = fieldStatistics(session.codes), target = cellReadout(session.codes, cursor);
    let readout = "";
    if (target) {
      const {x, y, code, percent} = target;
      readout = `x ${x} y ${y} · ${code} (${percent.toFixed(1)}%) · `;
      if (session.selection !== null) readout += session.selection[y * 128 + x] ? "selected · " : "unselected · ";
      cell.style.left = `${panX + x * zoom}px`; cell.style.top = `${panY + y * zoom}px`;
      cell.style.width = cell.style.height = `${zoom}px`;
    }
    drawBrush(stroke instanceof PressureStroke && stroke.mappings.size
      ? {...brush, size: stroke.sizeAt(stroke.pressure)} : brush);
    cell.hidden = !target || zoom < 8 || space || view.comparing;
    if (candidate !== null) {
      const r = selectionRectangle(gesture.start, gesture.end);
      readout = `${session.selectTool === "rectangle" ? "Rectangle" : "Ellipse"} x ${r.x0}–${r.x1} · y ${r.y0}–${r.y1} · ${r.width}×${r.height} · ${selectionStats(candidate).count} cells · `;
    }
    const selectedText = session.selection === null ? "" : `selection ${selected.count} cells (${(selected.count * 100 / 16384).toFixed(1)}%) · x ${selected.left}–${selected.right} · y ${selected.top}–${selected.bottom} · `;
    status.textContent = `${session.selectTool !== null ? toolName + " · " : ""}${readout}${Math.round(zoom * 100)}% zoom · ${selectedText}${stats.total} cells · ${stats.nonzero} nonzero · ${stats.zero} zero · binary ${stats.binary ? "yes" : "no"} · min ${stats.min} · max ${stats.max} · mean ${stats.mean.toFixed(2)} · ${stats.distinct} distinct${stats.nonzero ? "" : " · no positive values"}`;
    let statusDetail = status.textContent;
    if (view.contribution) {
      preview.hidden = true; // Raw brush target colours are not contribution predictions.
      const state = contributionState();
      const prefix = "Contribution · prepared weight 0–100% · edits change raw field · ";
      // Grouped stacks only; ready/conflict states always belong to the current snapshot.
      const groups = previewSnapshot?.choice?.groups, group = groups?.compact ? `${groups.compact} · ` : "";
      if (state.status === "ready") {
        const weight = target && preparedWeights ? preparedWeights[target.y * 128 + target.x] : null;
        statusDetail = prefix + (state.disabled ? "layer disabled · " : "")
          + (weight === null ? "" : `x ${target.x} y ${target.y} · ${(weight * 100).toPrecision(7)}% · `)
          + `${Math.round(zoom * 100)}% zoom` + (groups ? ` · ${groups.detail}` : "");
        status.textContent = (state.disabled ? "Layer disabled · " : "")
          + (weight === null ? `Contribution · ${group}hover for weight` : `${(weight * 100).toPrecision(7)}% contribution · ${group}x ${target.x} y ${target.y}`);
      } else if (state.status === "conflict") {
        statusDetail = "Contribution unavailable · FIXED conflicts: "
          + state.pairs.map(p => `layers ${p.layers.join(" / ")} share ${p.count} cells`).join("; ")
          + (groups ? ` · ${groups.detail}` : "");
        status.textContent = `FIXED conflict · ${state.cells.length} cells · preview unavailable`;
      } else {
        statusDetail = state.status === "stale" ? "Preview stale · editing; recalculates after stroke"
          : state.status === "pending" ? "Preview pending · calculating prepared weights"
          : `Preview unavailable · ${state.message}`;
        status.textContent = state.status === "stale" ? "Preview stale · editing"
          : state.status === "pending" ? "Preview pending" : `Unavailable · ${state.message}`;
      }
    }
    if (stroke instanceof PressureStroke && !stroke.mouse) {
      const pressure = `pressure ${pressurePercent(stroke.pressure)}% · `;
      status.textContent = pressure + status.textContent; statusDetail = pressure + statusDetail;
    }
    status.title = statusDetail;
  }
  function drawSelection() {
    if (shownSelection !== session.selection) {
      shownSelection = session.selection;
      veil.width = veil.height = 128;
      const context = veil.getContext("2d"), pixels = context.createImageData(128, 128);
      if (shownSelection !== null) for (let i = 0; i < 16384; i++)
        if (!shownSelection[i]) pixels.data.set(SELECTION_VEIL, i * 4);
      context.putImageData(pixels, 0, 0);
      const d = selectionOutlinePath(shownSelection);
      for (const path of selectionOutline.paths) path.setAttribute("d", d);
    }
    if (shownCandidate !== candidate) {
      shownCandidate = candidate;
      const d = selectionOutlinePath(candidate);
      for (const path of selectionCandidate.paths) path.setAttribute("d", d);
    }
    veil.hidden = session.selection === null || view.comparing;
    selectionOutline.layer.style.display = veil.hidden ? "none" : "";
    selectionCandidate.layer.style.display = candidate === null || view.comparing ? "none" : "";
    for (const {paths} of [selectionOutline, selectionCandidate]) paths.forEach((path, i) => {
      path.setAttribute("stroke-width", String((i ? 1 : 3) / zoom));
      if (i) path.setAttribute("stroke-dasharray", `${4 / zoom} ${4 / zoom}`);
    });
  }
  function drawBrush(brush) {
    // The outline and tint come from the stamp a click at the cursor would make, including
    // its quantized, snapped anchor; both share the field's pan/zoom transform. The tint's
    // opacity is the coverage; a Paint gradient colors it with each cell's exact target code,
    // shown as the field shows codes (gray, or heat), so the preview never changes a target.
    let shown = null;
    if (cursor && !space && !view.comparing && session.selectTool === null) {
      const crossField = brush.tool === "transfer" || brush.tool === "balance";
      try { shown = stampPreview(128, 128, crossField ? transferEngineBrush(tipBrush(brush)) : tipBrush(brush), cursor.x, cursor.y); } catch { shown = null; }
    }
    outline.style.display = shown ? "" : "none";
    preview.hidden = !shown || !!stroke;
    if (!shown) return;
    const d = outlinePath(footprintOutline(shown.footprint), shown.anchor);
    outlinePaths.forEach((path, i) => { path.setAttribute("d", d); path.setAttribute("stroke-width", String((i ? 1 : 3) / zoom)); });
    if (stroke) return;
    preview.width = preview.height = 128;
    const context = preview.getContext("2d"), pixels = context.createImageData(128, 128), targets = shown.targets;
    shown.coverage.forEach((weight, i) => {
      if (!(weight > 0) || (session.selection !== null && !session.selection[i])) return;
      const color = !targets ? [64, 160, 255] : view.heat ? heatColor(targets[i]) : [targets[i], targets[i], targets[i]];
      pixels.data.set([...color, Math.max(1, Math.round(weight * 160))], i * 4);
    });
    context.putImageData(pixels, 0, 0); // Display only; never read back into field data.
  }
  function schedule() { if (frame === null && !closed) frame = requestAnimationFrame(render); }
  function showFieldToolsMessage(text) { message.textContent = message.title = fieldToolsMessage = text; }
  function clearFieldToolsMessage() {
    if (fieldToolsMessage !== null && message.textContent === fieldToolsMessage) message.textContent = message.title = "";
    fieldToolsMessage = null;
  }
  function changeSelection(next) {
    if (next === null) showFieldToolsMessage(EMPTY_SELECTION);
    else { session.selection = next; clearFieldToolsMessage(); }
    schedule();
  }
  function selectionPosition(p) {
    const end = selectionCell(p);
    if (candidate !== null && gesture.end.x === end.x && gesture.end.y === end.y) return;
    gesture.end = end;
    candidate = (session.selectTool === "rectangle" ? rectangleSelection : ellipseSelection)(gesture.start, end);
  }
  // E5. The engine's brush: the session settings and, once read, the decoded custom tip.
  function tipBrush(settings = session.settings) { return session.tip ? {...settings, tip: session.tip} : settings; }
  function currentMask() {
    const s = session.settings;
    return tipMask(session.tip, s.tip_channel, s.tip_invert, s.tip_trim);
  }
  function tipCondition() { return session.tip ? (currentMask().empty ? "empty" : "ready") : active.tipLoad; }
  function tipText(condition) {
    return {none: "No custom tip is loaded. Import a PNG under Custom Tip.",
      loading: "The stored custom tip is still loading.",
      error: `The stored custom tip cannot be read: ${active.tipError} Import a PNG or clear it.`,
      empty: "This custom tip is empty as read: every value is 0. Choose another channel or Invert Tip."}[condition] ?? "";
  }
  // Why the current brush cannot paint because of its tip, or "".
  function tipRefusal() {
    if (session.settings.shape === "procedural") return proceduralMask(session.settings).empty ? PROCEDURAL_EMPTY : "";
    return session.settings.shape === "custom" ? tipText(tipCondition()) : "";
  }
  function renderProcedural(s, mask) {
    renderHotdog(s);
    proceduralGroup.details.hidden = !mask;
    scatterRows.hidden = s.procedural_type !== "scatter"; noiseRows.hidden = s.procedural_type !== "noise";
    if (!mask) return;
    proceduralGroup.heading.textContent = [proceduralGroup.title, s.procedural_type === "scatter" ? "Scatter" : "Noise",
      ...proceduralModifiers(s), ...(mask.empty ? ["empty"] : [])].join(" · ");
    proceduralStatus.textContent = mask.empty ? PROCEDURAL_EMPTY : "";
    proceduralStatus.hidden = !mask.empty; proceduralStatus.style.color = mask.empty ? "#ffb5ab" : "";
    proceduralCrop.hidden = !(s.crop_left || s.crop_right || s.crop_top || s.crop_bottom);
    Object.assign(proceduralCrop.style, {left: `${s.crop_left}%`, right: `${s.crop_right}%`, top: `${s.crop_top}%`, bottom: `${s.crop_bottom}%`});
    if (mask === shownProceduralMask) return;
    shownProceduralMask = mask;
    proceduralThumbnail.width = proceduralThumbnail.height = 256;
    proceduralThumbnail.style.width = proceduralThumbnail.style.height = "96px";
    const context = proceduralThumbnail.getContext("2d"), pixels = context.createImageData(256, 256);
    for (let i = 0; i < mask.codes.length; i++) {
      pixels.data[i * 4] = pixels.data[i * 4 + 1] = pixels.data[i * 4 + 2] = mask.codes[i];
      pixels.data[i * 4 + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);
  }
  function showTipMessage(text, refusal = false) { message.textContent = message.title = text; tipMessage = {text, refusal}; }
  // Another message written since is left as it is.
  function clearTipMessage() {
    if (tipMessage && message.textContent === tipMessage.text) message.textContent = message.title = "";
    tipMessage = null;
  }
  function renderTip(s, condition) {
    const kept = !!s.custom_tip, custom = s.shape === "custom", mask = session.tip ? currentMask() : null;
    tipGroup.details.hidden = !custom && !kept;
    clearTipButton.hidden = tipReading.hidden = !kept;
    tipPrepared.hidden = tipFrame.hidden = tipCaption.hidden = !mask;
    if (mask) {
      drawTip(mask);
      cropBox.hidden = !(s.crop_left || s.crop_right || s.crop_top || s.crop_bottom);
      Object.assign(cropBox.style, {left: `${s.crop_left}%`, right: `${s.crop_right}%`, top: `${s.crop_top}%`, bottom: `${s.crop_bottom}%`});
      const {width, height} = session.tip, trimmed = mask.width !== width || mask.height !== height;
      tipCaption.textContent = `Prepared tip ${mask.width}×${mask.height}${trimmed ? ` (trimmed from ${width}×${height})` : ""}` +
        ` · ${(s.custom_tip.length / 1024).toFixed(1)} KB kept with the node`;
    }
    const notes = [tipText(condition)];
    if (condition === "ready" && s.tip_channel === "alpha" && active.tipOpaque)
      notes.push("This PNG has no transparency, so Alpha covers its whole rectangle; Luminance reads its gray values.");
    if (!custom && kept) notes.push("Kept with this node: choose Shape Custom to paint with it.");
    tipStatus.textContent = notes.filter(Boolean).join(" ");
    tipStatus.hidden = !tipStatus.textContent;
    tipStatus.style.color = custom && condition !== "ready" ? "#ffb5ab" : "";
    const state = mask ? [`${session.tip.width}×${session.tip.height}`, ...tipModifiers(s), ...(mask.empty ? ["empty"] : [])]
      : [{none: "none loaded", loading: "loading", error: "unreadable"}[condition]];
    tipGroup.heading.textContent = [tipGroup.title, ...state, ...(!custom && kept ? ["not in use"] : [])].join(" · ");
  }
  function drawTip(mask) { // Display only; never read back.
    if (mask === shownMask) return;
    shownMask = mask;
    const scale = 96 / Math.max(mask.width, mask.height);
    thumbnail.width = mask.width; thumbnail.height = mask.height;
    thumbnail.style.width = `${mask.width * scale}px`; thumbnail.style.height = `${mask.height * scale}px`;
    const context = thumbnail.getContext("2d"), pixels = context.createImageData(mask.width, mask.height);
    for (let i = 0; i < mask.codes.length; i++) {
      pixels.data[i * 4] = pixels.data[i * 4 + 1] = pixels.data[i * 4 + 2] = mask.codes[i];
      pixels.data[i * 4 + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);
  }
  function setTip(tip, target = active) { target.session.tip = tip; target.tipOpaque = tip.alpha.every(a => a === 255); }
  // A new tip replaces the old one, and its reading settings stay as they are. No field or history change.
  async function importTip(file) {
    if (!file || busy || stroke || closed) return;
    const target = active;
    busy = true;
    try {
      const {tip, value} = await importTipFile(file);
      if (closed) return;
      setTip(tip, target); target.session.settings.custom_tip = value; clearTipMessage(); schedule();
    } catch (error) { if (!closed) showTipMessage(`Cannot import the custom tip: ${error.message}`); }
    finally { busy = false; }
  }
  // Removes the tip and how it is read; Shape stays as it is. No field or history change.
  function clearTip() {
    delete session.settings.custom_tip; session.tip = null; active.tipLoad = "none";
    for (const key of ["tip_channel", "tip_invert", "tip_trim"]) session.settings[key] = BRUSH_DEFAULTS[key];
    clearTipMessage(); schedule();
  }
  function fit() {
    const rect = viewport.getBoundingClientRect();
    zoom = Math.max(0.25, Math.min(rect.width - 16, rect.height - 16) / 128);
    panX = (rect.width - 128 * zoom) / 2; panY = (rect.height - 128 * zoom) / 2; cursor = null; schedule();
  }
  function position(event) {
    return fieldPosition(event.clientX, event.clientY, viewport.getBoundingClientRect(), zoom, panX, panY);
  }
  function samples(event, release = false) {
    const coalesced = event.getCoalescedEvents?.();
    for (const sample of coalesced?.length ? [...coalesced, event] : [event]) {
      const p = position(sample);
      smoother.add(p.x, p.y, stroke instanceof PressureStroke ? (release ? stroke.pressure : pressureCode(sample.pressure)) : null);
      endpoint = p;
    }
    if (release) smoother.finish();
  }
  // Smoothed points reach the stroke here; Smoothing 0 passes the sampled path through unchanged.
  function smoothStroke(x, y, pressure) {
    const made = stroke;
    return made && new StrokeSmoother(session.settings.smoothing, x, y, pressure,
      (sx, sy, code) => { if (made instanceof PressureStroke) made.add(sx, sy, code); else made.add(sx, sy); });
  }
  function newStroke(x, y, pressure = null) {
    // A Custom brush without a usable tip says why and paints nothing.
    const problem = tipRefusal();
    if (problem) { showTipMessage(problem, true); return null; }
    settleSource(active); settlePartner(active);
    const moving = session.settings.tool === "transfer", balancing = session.settings.tool === "balance";
    if (moving) {
      const refusal = transferRefusal();
      if (refusal) { showTransferMessage(refusal, true); return null; }
    }
    if (balancing) {
      const refusal = balanceRefusal();
      if (refusal) { showBalanceMessage(refusal, true); return null; }
    }
    const brush = moving || balancing ? transferEngineBrush(tipBrush()) : tipBrush();
    // Balance's per-cell target is fixed here, from both fields at stroke start.
    const target = moving ? transferReach(active.transferSource.session.codes, session.codes)
      : balancing ? balanceTarget(session.codes, active.balancePartner.session.codes, active.balanceShare) : session.initial;
    let made;
    try {
      const jitter = stampJitterActive(brush);
      made = pressure === null && !(jitter && brush.amount_jitter > 0)
        ? new (jitter ? JitterStroke : Stroke)(session.codes, 128, 128, brush, x, y, target, session.selection)
        : new (jitter ? JitterPressureStroke : PressureStroke)(session.codes, 128, 128, brush, x, y, target, session.selection, pressure);
    }
    catch (error) { message.textContent = message.title = error.message; return null; }
    transfer = moving ? {source: active.transferSource, sourceBefore: active.transferSource.session.codes.slice()} : null;
    balance = balancing ? {partner: active.balancePartner, partnerBefore: active.balancePartner.session.codes.slice(),
      target, share: active.balanceShare} : null;
    if (moving) clearTransferMessage();
    if (balancing) clearBalanceMessage();
    clearTipMessage(); return made; // A stroke that starts leaves no earlier tip refusal or failed import shown.
  }
  function endStroke() {
    if (!stroke) return;
    try {
      const after = stroke.result();
      if (transfer) {
        const sourceAfter = transferSource(transfer.sourceBefore, stroke.before, after);
        const moved = links.record(active, transfer.source, stroke.before, after, transfer.sourceBefore, sourceAfter);
        if (!moved) { session.codes = after; transfer.source.session.codes = sourceAfter; }
        if (!moved && nothingMovable(stroke.coverage, stroke.selection, transfer.sourceBefore, stroke.before))
          showTransferMessage(`Nothing to transfer under the brush: ${transfer.source.label} is 0 or ${active.label} is 255 there.`);
        transfer = null;
      } else if (balance) {
        // The binding, never the current partner or share; the final buffers are installed even for a no-op.
        const partnerAfter = balancePartner(balance.partnerBefore, stroke.before, after, balance.target);
        const moved = links.recordBalance(active, balance.partner, stroke.before, after, balance.partnerBefore, partnerAfter, balance.target);
        if (!moved) { session.codes = after; balance.partner.session.codes = partnerAfter; }
        if (!moved && balanceSettled(stroke.coverage, stroke.selection, balance.target, stroke.before))
          showBalanceMessage(`Nothing to balance under the brush: ${active.label} and ${balance.partner.label} are already at ${balance.share}:${100 - balance.share} there, as closely as whole 0–255 codes allow.`);
        balance = null;
      } else { session.codes = after; session.history.record("Stroke", stroke.before, session.codes); }
    } catch (error) {
      if (transfer) { abortStroke(); showTransferMessage("Transfer stopped: an internal check failed. Nothing was changed."); return; }
      if (!balance) throw error;
      abortStroke(); showBalanceMessage("Balance stopped: an internal check failed. Nothing was changed."); return;
    }
    anchor = cellReadout(session.codes, endpoint) ? {...endpoint} : null;
    stroke = null; gesture = null; schedule();
  }
  function abortStroke() {
    if (stroke) session.codes = stroke.before.slice();
    if (transfer) transfer.source.session.codes = transfer.sourceBefore.slice();
    if (balance) balance.partner.session.codes = balance.partnerBefore.slice();
    transfer = null; balance = null;
    stroke = null; gesture = null; candidate = null; schedule();
  }
  function cancelSelectionGesture() {
    if (!gesture?.select) return;
    const id = gesture.id;
    abortStroke();
    viewport.releasePointerCapture(id);
  }
  viewport.addEventListener("pointerdown", event => {
    if (busy || gesture || maskDialog || libraryDialog || chooserDialog || ![0, 1].includes(event.button)) return;
    event.preventDefault();
    cursor = position(event);
    if (!space && event.button === 0 && session.selectTool !== null) {
      if (!onField(cursor)) return;
      gesture = {id: event.pointerId, select: true, start: selectionCell(cursor)};
      selectionPosition(cursor); viewport.setPointerCapture(event.pointerId); schedule(); return;
    }
    if (!space && event.button === 0 && event.altKey) {
      const target = cellReadout(session.codes, cursor);
      if (target) session.settings.influence = target.code;
      schedule(); return;
    }
    if (!space && event.button === 0 && event.shiftKey && anchor && cellReadout(session.codes, cursor)) {
      stroke = newStroke(anchor.x, anchor.y);
      if (stroke) { stroke.add(cursor.x, cursor.y); endpoint = cursor; endStroke(); }
      return;
    }
    viewport.setPointerCapture(event.pointerId);
    gesture = {id: event.pointerId, x: event.clientX, y: event.clientY, panX, panY, pan: space || event.button === 1};
    if (!gesture.pan) {
      const pressure = event.pointerType === "pen" && pressureMappings(session.settings) ? pressureCode(event.pressure) : null;
      endpoint = cursor; stroke = newStroke(cursor.x, cursor.y, pressure); smoother = smoothStroke(cursor.x, cursor.y, pressure);
    }
    schedule();
  });
  viewport.addEventListener("pointermove", event => {
    cursor = position(event);
    if (gesture?.id === event.pointerId) {
      if (gesture.pan) { panX = gesture.panX + event.clientX - gesture.x; panY = gesture.panY + event.clientY - gesture.y; cursor = position(event); }
      else if (gesture.select) selectionPosition(cursor);
      else if (stroke) samples(event);
    }
    schedule();
  });
  viewport.addEventListener("pointerup", event => {
    if (gesture?.id !== event.pointerId) return;
    if (gesture.select) {
      selectionPosition(position(event));
      changeSelection(combineSelection(session.selection, candidate, session.selectionMode)); candidate = null;
    }
    if (stroke) { samples(event, true); endStroke(); }
    gesture = null; viewport.releasePointerCapture(event.pointerId); schedule();
  });
  viewport.addEventListener("pointercancel", abortStroke);
  viewport.addEventListener("lostpointercapture", () => { if (gesture) abortStroke(); });
  viewport.addEventListener("pointerleave", () => { if (!gesture) { cursor = null; schedule(); } });
  viewport.addEventListener("wheel", event => {
    event.preventDefault();
    if (stroke || gesture?.select || busy || maskDialog) return;
    const p = position(event), next = Math.max(0.25, Math.min(64, zoom * (event.deltaY < 0 ? 1.2 : 1 / 1.2)));
    panX += p.x * (zoom - next); panY += p.y * (zoom - next); zoom = next; cursor = p; schedule();
  }, {passive: false});
  function clearReference() {
    referenceRevision++;
    for (const url of pendingReferences) URL.revokeObjectURL(url);
    pendingReferences.clear();
    if (referenceUrl) URL.revokeObjectURL(referenceUrl);
    referenceUrl = null; reference.removeAttribute("src"); reference.hidden = true; releaseCompare();
  }
  async function loadReference(file) {
    if (!file || busy || stroke || closed) return;
    const revision = ++referenceRevision, url = URL.createObjectURL(file);
    pendingReferences.add(url);
    const decoded = document.createElement("img");
    try {
      decoded.src = url; await decoded.decode();
      if (closed || revision !== referenceRevision) { URL.revokeObjectURL(url); return; }
      if (referenceUrl) URL.revokeObjectURL(referenceUrl);
      referenceUrl = url; reference.src = url; reference.hidden = false;
      message.textContent = message.title = ""; schedule();
    } catch (error) {
      URL.revokeObjectURL(url);
      if (!closed && revision === referenceRevision) message.textContent = message.title = `Cannot load reference image: ${error.message}`;
    } finally { pendingReferences.delete(url); }
  }
  async function importFile(file) {
    if (!file || busy || stroke || gesture || maskDialog || libraryDialog || chooserDialog || closed) return;
    const target = active;
    busy = true;
    try {
      if (file.size > 65536) throw new Error("PNG exceeds 65,536 bytes.");
      const imported = await decodeFieldPng(new Uint8Array(await file.arrayBuffer()));
      if (!closed) { target.session.replace("Import", withinSelection(target.session.codes, imported, target.session.selection)); anchor = null; message.textContent = message.title = ""; schedule(); }
    } catch (error) { message.textContent = message.title = `${error.message} For another size or format, use Advanced ▸ Field Tools ▸ Import Mask…`; }
    finally { busy = false; }
  }
  async function importMask(file) {
    if (!file || busy || stroke || gesture || closed || maskDialog || libraryDialog || chooserDialog) return;
    const target = active;
    busy = true; showFieldToolsMessage("Reading PNG…");
    try {
      const source = await readMaskFile(file);
      if (closed) return;
      clearFieldToolsMessage(); space = false; releaseCompare();
      const heat = view.heat;
      maskDialog = openMaskImport({source, codes: target.session.codes, selection: target.session.selection, options: maskOptions,
        draw: (canvas, codes) => drawCodes(canvas, codes, heat),
        apply: next => { if (closed || active !== target) return; target.session.replace("Import Mask", next); anchor = null; schedule(); },
        onClose: () => { maskDialog = null; clearFieldToolsMessage(); if (!closed) dialog.focus(); }});
    } catch (error) { if (!closed) showFieldToolsMessage(`Cannot import the mask: ${error.message}`); }
    finally { busy = false; }
  }
  dialog.addEventListener("dragover", event => { event.preventDefault(); event.stopPropagation(); });
  dialog.addEventListener("drop", event => { event.preventDefault(); event.stopPropagation(); importFile(event.dataTransfer?.files?.[0]); });
  function cancel() {
    if (busy || maskDialog) return;
    if (stroke || gesture?.select) { abortStroke(); return; }
    const count = records.filter(changed).length;
    if (count > 0 && !host.confirmDiscard(count)) return;
    onCancel?.(); close();
  }
  function keyboard(event) {
    // Capture above host graph handlers, including when focus leaves our controls.
    event.stopImmediatePropagation();
    if (chooserDialog) { chooserDialog.keyboard(event); return; }
    if (libraryDialog) { libraryDialog.keyboard(event); return; }
    if (maskDialog) { maskDialog.keyboard(event); return; }
    if (event.target === contextChoice) return; // Preserve native select keyboard behavior.
    // The window capture handler isolates the editor from host shortcuts. Activate
    // these disclosure controls explicitly; Space must not start canvas panning.
    if (([advancedToggle, summary, field.children[0], influenceSummary, fieldsView, contributionView].includes(event.target) ||
        (event.target.tagName === "BUTTON" && paintingOptions.contains(event.target))) && [" ", "Enter"].includes(event.key)) {
      event.preventDefault();
      if (!event.repeat && ((event.key === "Enter" && event.type === "keydown") ||
          (event.key === " " && event.type === "keyup"))) event.target.click();
      return;
    }
    if (event.type === "keyup" && event.key === compareKey) { event.preventDefault(); releaseCompare(); return; }
    if (event.target === compare && [" ", "Enter"].includes(event.key)) {
      event.preventDefault(); compareKey = event.key;
      view.comparing = event.type === "keydown" && !!referenceUrl && !busy; schedule(); return;
    }
    const control = controls.find(c => c.element === event.target);
    if (control) { if (event.type === "keydown") control.keydown(event); return; }
    if (event.key === "Escape" && influenceMenu.open) {
      event.preventDefault();
      if (event.type === "keydown") { closeInfluenceMenu(); influenceSummary.focus(); }
      return;
    }
    if (event.key === " ") { event.preventDefault(); space = event.type === "keydown"; schedule(); }
    if (event.type !== "keydown" || busy) return;
    const key = event.key.toLowerCase();
    const command = event.ctrlKey || event.metaKey;
    if (key === "escape") { event.preventDefault(); cancel(); return; }
    if (stroke) return;
    // Tool shortcuts share the button transition, including selection cancellation.
    if (!command && (key === "b" || key === "e")) {
      setTool(key === "b" ? "paint" : "erase"); return;
    }
    if (gesture?.select) return;
    if (command) {
      event.preventDefault();
      if (key === "z") edit(() => historyStep(event.shiftKey ? "redo" : "undo"));
      if (key === "y") edit(() => historyStep("redo"));
    } else if (key === "f") fit();
    else if (["[", "]", "{", "}"].includes(key) || ["BracketLeft", "BracketRight"].includes(event.code)) {
      const k = event.shiftKey ? "hardness" : "size", low = event.shiftKey ? 0 : 1, high = event.shiftKey ? 100 : 128;
      const lower = event.code === "BracketLeft" || key === "[" || key === "{";
      session.settings[k] = Math.max(low, Math.min(high, session.settings[k] + (lower ? -1 : 1)));
    } else if (/^[0-9]$/.test(key)) session.settings.influence = percentToCode(key === "0" ? 100 : Number(key) * 10);
    schedule();
  }
  function close() {
    if (closed) return;
    closed = true;
    previewEpoch++; previewQueue?.dispose();
    if (previewPoll !== null) clearInterval(previewPoll);
    libraryDialog?.dispose(); libraryDialog = null;
    maskDialog?.dispose(); maskDialog = null; clearFieldToolsMessage();
    chooserDialog?.dispose(); chooserDialog = null;
    for (const r of records) { r.session.selection = null; r.session.selectTool = null; }
    candidate = null;
    clearReference();
    if (frame !== null) cancelAnimationFrame(frame);
    window.removeEventListener("keydown", keyboard, true); window.removeEventListener("keyup", keyboard, true);
    window.removeEventListener("resize", fit); window.removeEventListener("blur", blur);
    dialog.close(); dialog.remove();
  }
  function blur() { space = false; releaseCompare(); abortStroke(); }
  dialog.addEventListener("cancel", event => { event.preventDefault(); cancel(); });
  for (const name of ["pointerdown", "pointerup", "click", "dblclick", "contextmenu"])
    dialog.addEventListener(name, event => event.stopPropagation());
  function loadStoredTip(r) {
    const storedTip = r.session.settings.custom_tip;
    if (!storedTip) return;
    r.tipLoad = "loading";
    const current = apply => value => {
      if (closed || !records.includes(r) || r.session.tip || r.tipLoad !== "loading" || r.session.settings.custom_tip !== storedTip) return;
      apply(value); schedule();
    };
    decodeTipDataUrl(storedTip).then(current(tip => setTip(tip, r)),
      current(error => { r.tipLoad = "error"; r.tipError = error.message; }));
  }
  rebuildMembershipDom(); loadStoredTip(active);
  document.body.append(dialog); dialog.showModal();
  window.addEventListener("keydown", keyboard, true); window.addEventListener("keyup", keyboard, true);
  window.addEventListener("resize", fit); window.addEventListener("blur", blur);
  fit();
  return {get session() { return active.session; }, cancel,
    fields: () => records.map(r => ({key: r.key, label: r.label, slot: r.slot, visible: r.visible,
      active: r === active, available: isAvailable(r), changed: changed(r), session: r.session,
      transferFrom: r.transferSource?.key ?? null, balanceWith: r.balancePartner?.key ?? null, balanceShare: r.balanceShare}))};
}
