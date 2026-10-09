import {maskPlacement, reduceMask} from "./field_import.js";
import {withinSelection} from "./engine.js";

// The source and result belong only to this modal. Disposal drops every retained reference.
export function openMaskImport({source, codes, selection, options, draw, apply, onClose}) {
  const el = (tag, text, parent) => {
    const item = document.createElement(tag); if (text) item.textContent = text;
    parent?.append(item); return item;
  };
  const dialog = el("dialog"); dialog.className = "cl-mask-import";
  dialog.setAttribute("aria-label", "Import Mask");
  el("style", `
    .cl-mask-import {width:min(620px,90vw);max-height:85vh;overflow:auto;padding:20px;
      background:#24262b;color:#eee;border:1px solid #888;border-radius:8px;}
    .cl-mask-import::backdrop {background:#0009;}
    .cl-mask-import .import-bar {display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0;}
    .cl-mask-import button {padding:7px;cursor:pointer;}
    .cl-mask-import button[aria-pressed=true] {outline:2px solid #79aeff;}
    .cl-mask-import .import-notes {white-space:pre-line;font-size:12px;}
    .cl-mask-import .import-preview {width:256px;height:256px;image-rendering:pixelated;}
  `, dialog);
  el("h2", "Import Mask", dialog);
  const transparent = anyTransparent(source.alpha), width = source.width, height = source.height;
  el("p", `Source ${width}×${height} pixels · ${transparent ? "with transparency" : "opaque"}`, dialog).className = "import-source";
  let closed = false, result = null;
  const refreshers = [];
  const button = (parent, text, action) => {
    const b = el("button", text, parent); b.type = "button";
    b.addEventListener("click", () => { if (!closed) action(); }); return b;
  };
  function choice(label, key, values) {
    const row = el("div", null, dialog); row.className = "import-bar"; el("span", label, row);
    for (const [value, label] of values) {
      const b = button(row, label, () => { options[key] = value; render(); });
      refreshers.push(() => b.setAttribute("aria-pressed", options[key] === value));
    }
  }
  choice("Read", "read", [["luminance", "Luminance"], ["alpha", "Alpha"], ["alpha_luminance", "Alpha × Luminance"]]);
  choice("Placement", "placement", [["stretch", "Stretch"], ["fit", "Fit (pad 0)"], ["fill", "Fill (crop)"]]);
  choice("Result", "binary", [[false, "Graded"], [true, "Binary"]]);
  const invert = button(dialog, "Invert Mask", () => { options.invert = !options.invert; render(); });
  const notes = el("p", null, dialog); notes.className = "import-notes";
  const preview = el("canvas", null, dialog); preview.className = "import-preview";
  preview.setAttribute("aria-label", "Field after Apply");
  const summary = el("p", null, dialog); summary.className = "import-summary";
  const actions = el("div", null, dialog); actions.className = "import-bar";
  button(actions, "Apply Import", () => { apply(withinSelection(codes, result, selection)); dispose(); });
  button(actions, "Cancel Import", dispose);

  function render() {
    result = reduceMask(source, options);
    const next = withinSelection(codes, result, selection);
    draw(preview, next);
    for (const refresh of refreshers) refresh();
    invert.setAttribute("aria-pressed", options.invert);
    const {x0, y0, sw, ox, oy, rw, rh} = maskPlacement(width, height, options.placement);
    const lines = [options.placement === "stretch"
      ? `Stretch: all ${width}×${height} pixels fill the 128×128 field${width === height ? "" : " (aspect changes)"}, as a reference image is shown.`
      : options.placement === "fit" ? `Fit: all ${width}×${height} pixels fill ${rw}×${rh} cells at x ${ox}, y ${oy}; the other cells are 0.`
      : `Fill: the centred ${sw}×${sw} pixels at x ${x0}, y ${y0} fill the field; the rest of the image is not used.`];
    if (transparent && options.read === "luminance") lines.push("This PNG has transparency, which Luminance ignores. Alpha or Alpha × Luminance reads it.");
    if (!transparent && options.read !== "luminance") lines.push("This PNG has no transparency: Alpha is 255 everywhere.");
    lines.push("Graded: each cell is its exact area average. Binary: 255 where that average is at least 127.5, otherwise 0.");
    if (options.invert) lines.push("Inverted before averaging; Fit's empty cells stay 0.");
    notes.textContent = lines.join("\n");
    const changed = next.reduce((n, v, i) => n + (v !== codes[i] ? 1 : 0), 0);
    summary.textContent = selection === null ? `Apply replaces all 16384 cells; ${changed} change.`
      : `Apply replaces only the ${selection.reduce((n, v) => n + v, 0)} selected cells; ${changed} change.`;
  }
  function dispose() {
    if (closed) return;
    closed = true; source = codes = selection = result = null;
    dialog.close(); dialog.remove(); onClose();
  }
  function keyboard(event) {
    if (event.key === "Escape") { event.preventDefault(); if (event.type === "keydown") dispose(); }
  }
  dialog.addEventListener("cancel", event => { event.preventDefault(); dispose(); });
  for (const name of ["pointerdown", "pointerup", "click", "dblclick", "contextmenu", "dragover", "drop"])
    dialog.addEventListener(name, event => { event.stopPropagation(); if (name === "drop" || name === "dragover") event.preventDefault(); });
  render(); document.body.append(dialog); dialog.showModal();
  return {dispose, keyboard};
}

// Exact transparency test, including a nonopaque final sample.
function anyTransparent(alpha) {
  for (let i = 0; i < alpha.length; i++) if (alpha[i] !== 255) return true;
  return false;
}
