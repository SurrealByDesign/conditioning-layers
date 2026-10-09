import {filterBrushPresets, createPresetThumbnails, prepareBrushPreset} from "./brush_library.js";

// Created only from Advanced. All controls and selection state belong to this dialog, never a workflow.
export function openBrushLibrary({library, currentBrush, apply, confirmDelete, onClose}) {
  const el = (tag, text, parent) => {
    const item = document.createElement(tag); if (text) item.textContent = text;
    parent?.append(item); return item;
  };
  const dialog = el("dialog"); dialog.className = "cl-brush-library";
  dialog.setAttribute("aria-label", "Brush Library");
  el("style", `
    .cl-brush-library {width:min(680px,90vw);max-height:85vh;overflow:auto;padding:20px;
      background:#24262b;color:#eee;border:1px solid #888;border-radius:8px;}
    .cl-brush-library::backdrop {background:#0009;}
    .cl-brush-library .library-bar {display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0;}
    .cl-brush-library input,.cl-brush-library select {min-width:0;padding:7px;background:#16181c;color:#fff;border:1px solid #777;}
    .cl-brush-library label {display:flex;gap:6px;align-items:center;}
    .cl-brush-library button {padding:7px;cursor:pointer;}
    .cl-brush-library button[aria-pressed=true] {outline:2px solid #79aeff;}
    .cl-brush-library .preset-row {display:flex;align-items:center;gap:10px;padding:6px;border-bottom:1px solid #555;}
    .cl-brush-library .preset-select {flex:1;text-align:left;overflow-wrap:anywhere;}
    .cl-brush-library canvas {width:48px;height:48px;flex-shrink:0;background:repeating-conic-gradient(#555 0% 25%,#333 0% 50%) 0/12px 12px;}
    .cl-brush-library .library-status {white-space:pre-wrap;overflow-wrap:anywhere;}
    .cl-brush-library [hidden] {display:none;}
  `, dialog);
  el("h2", "Brush Library", dialog);
  el("p", "Saved for your ComfyUI user across nodes and workflows. Library changes save immediately, including when the field editor is cancelled.", dialog);
  const filters = el("div", null, dialog); filters.className = "library-bar";
  const input = (parent, title, type = "text") => {
    const label = el("label", title, parent), field = el("input", null, label);
    field.type = type; field.setAttribute("aria-label", title); return field;
  };
  const search = input(filters, "Search", "search");
  const categoryLabel = el("label", "Category filter", filters), categories = el("select", null, categoryLabel);
  categories.setAttribute("aria-label", "Category filter");
  const status = el("div", null, dialog); status.className = "library-status"; status.setAttribute("role", "status");
  const list = el("div", null, dialog); list.setAttribute("aria-label", "Saved presets");
  const paging = el("div", null, dialog); paging.className = "library-bar";
  const selected = el("p", "Select a preset to manage it.", dialog);
  const fields = el("div", null, dialog); fields.className = "library-bar";
  const name = input(fields, "Preset name"), category = input(fields, "Preset category");
  name.maxLength = category.maxLength = 80;
  const actions = el("div", null, dialog); actions.className = "library-bar";
  const files = el("div", null, dialog); files.className = "library-bar";
  const buttons = [], needsSelection = [];
  let state = {presets: [], warnings: []}, id = null, favorites = false, page = 0;
  let busy = false, closed = false, revision = 0;
  const thumbnail = createPresetThumbnails();
  const button = (parent, title, action, needs = false) => {
    const b = el("button", title, parent); b.type = "button";
    b.addEventListener("click", () => { if (!busy && !closed) action(); });
    buttons.push(b); if (needs) needsSelection.push(b); return b;
  };
  const favoriteFilter = button(filters, "Favorites only", () => { favorites = !favorites; page = 0; render(); });
  button(paging, "Previous", () => { page = Math.max(0, page - 1); render(); });
  const pageLabel = el("span", null, paging);
  button(paging, "Next", () => { page++; render(); });
  const chosen = () => state.presets.find(p => p.id === id);
  function select(preset) {
    id = preset.id; name.value = preset.name; category.value = preset.category; render();
  }
  function controls() {
    for (const b of buttons) b.disabled = busy || (needsSelection.includes(b) && !chosen());
  }
  async function run(action, message = "") {
    if (busy || closed) return;
    busy = true; controls(); status.textContent = "Working…";
    try {
      const result = await action();
      if (closed) return;
      if (result?.presets) {
        state = result;
        if (Object.hasOwn(result, "id")) id = result.id;
        if (chosen()) { name.value = chosen().name; category.value = chosen().category; }
      }
      status.textContent = [message, ...state.warnings].filter(Boolean).join("\n"); render();
    } catch (error) { if (!closed) status.textContent = `Operation failed: ${error.message}`; }
    finally { busy = false; if (!closed) controls(); }
  }
  function render() {
    let selectedCategory = categories.value || "all";
    if (selectedCategory.startsWith("category:") && !state.presets.some(p => `category:${p.category}` === selectedCategory))
      selectedCategory = "all";
    categories.replaceChildren();
    for (const [value, title] of [["all", "All categories"], ["empty", "Uncategorized"],
      ...[...new Set(state.presets.map(p => p.category).filter(Boolean))].sort().map(c => [`category:${c}`, c])]) {
      const option = el("option", title, categories); option.value = value;
    }
    categories.value = selectedCategory;
    const group = selectedCategory === "all" ? null : selectedCategory === "empty" ? "" : selectedCategory.slice(9);
    const matches = filterBrushPresets(state.presets, {search: search.value, category: group, favorites});
    page = Math.min(page, Math.max(0, Math.ceil(matches.length / 24) - 1));
    const shown = matches.slice(page * 24, (page + 1) * 24), token = ++revision;
    list.replaceChildren();
    if (!shown.length) el("p", "No matching presets. Save your current brush to get started.", list);
    for (const preset of shown) {
      const row = el("div", null, list); row.className = "preset-row";
      const canvas = el("canvas", null, row); canvas.width = canvas.height = 48;
      canvas.setAttribute("aria-label", `${preset.name} preview`);
      const pick = el("button", `${preset.name} · ${preset.category || "Uncategorized"}`, row);
      pick.type = "button"; pick.className = "preset-select"; pick.setAttribute("aria-pressed", preset.id === id);
      pick.addEventListener("click", () => { if (!busy) select(preset); });
      const star = el("button", preset.favorite ? "★" : "☆", row); star.type = "button";
      star.setAttribute("aria-label", `Favorite ${preset.name}`); star.setAttribute("aria-pressed", preset.favorite);
      star.addEventListener("click", () => run(() => library.metadata(preset.id, {favorite: !preset.favorite}), "Favorite saved."));
      thumbnail(preset).then(({side, pixels}) => {
        if (closed || token !== revision) return;
        const context = canvas.getContext("2d"), image = context.createImageData(side, side);
        image.data.set(pixels); context.putImageData(image, 0, 0);
      }).catch(error => { if (!closed && token === revision) canvas.setAttribute("aria-label", `Preview unavailable: ${error.message}`); });
    }
    favoriteFilter.setAttribute("aria-pressed", favorites);
    pageLabel.textContent = `${matches.length} presets · page ${page + 1}`;
    selected.textContent = chosen() ? `Selected: ${chosen().name} · ${chosen().category || "Uncategorized"}` : "Select a preset to manage it.";
    controls();
  }
  button(actions, "Save As New", () => run(() => library.save(currentBrush(), name.value, category.value), "Brush saved."));
  button(actions, "Apply", () => run(async () => {
    const prepared = await prepareBrushPreset(chosen());
    if (!closed) apply(prepared);
  }, "Brush applied. Current tool preserved."), true);
  button(actions, "Update from Current Brush", () => run(() => library.update(id, currentBrush()), "Brush updated; name, category and favorite retained."), true);
  button(actions, "Rename / Set Category", () => run(() => library.metadata(id, {name: name.value, category: category.value}), "Metadata saved."), true);
  button(actions, "Duplicate", () => run(() => library.duplicate(id), "Preset duplicated."), true);
  button(actions, "Delete", () => {
    if (confirmDelete(chosen().name)) run(() => library.remove(id), "Preset deleted. Current brush kept.");
  }, true);
  const picker = el("input", null, files); picker.type = "file"; picker.accept = ".json,application/json"; picker.hidden = true;
  picker.addEventListener("change", () => {
    const file = picker.files?.[0]; picker.value = "";
    if (file) run(async () => library.importPreset(await file.text()), "Preset imported as a new identity.");
  });
  button(files, "Import Preset JSON…", () => picker.click());
  button(files, "Export Preset JSON", () => run(async () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(chosen())], {type: "application/json"}));
    const link = el("a", null, dialog); link.href = url; link.download = "brush-preset.json";
    try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 0); }
  }, "Preset exported."), true);
  button(files, "Refresh", () => run(() => library.load()));
  button(files, "Close Library", close);
  search.addEventListener("input", () => { page = 0; render(); });
  categories.addEventListener("change", () => { page = 0; render(); });
  function close() {
    if (busy || closed) return;
    dispose(); onClose?.();
  }
  function dispose() { closed = true; revision++; dialog.close(); dialog.remove(); }
  dialog.addEventListener("cancel", e => { e.preventDefault(); close(); });
  for (const type of ["pointerdown", "pointerup", "click", "dblclick", "contextmenu", "drop", "dragover"])
    dialog.addEventListener(type, e => { e.stopPropagation(); if (type === "drop" || type === "dragover") e.preventDefault(); });
  document.body.append(dialog); dialog.showModal();
  void run(() => library.load());
  return {dispose, keyboard(event) {
    // Parent window capture owns graph isolation; text and selection keys keep their native defaults.
    if (event.type === "keydown" && event.key === "Escape") { event.preventDefault(); close(); }
  }};
}
