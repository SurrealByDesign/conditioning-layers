import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { DraftTransportError, SaveAcknowledgementError, createLayerStore, loadPresetCatalog, loadPresetField } from "./layer_draft.js";
import { createPreviewRegistry } from "./field_preview.js";

const EXTENSION_NAME = "conditioning-layers.artist-sidebar";
const EXECUTION_ENDPOINT = "/conditioning-layers/executions";
const DOCUMENT_ENDPOINT = "/conditioning-layers/documents";

export function registerSidebarCompatibility(extensionManager, definition) {
  const current = extensionManager?.sidebarTab?.registerSidebarTab;
  if (typeof current === "function") {
    current.call(extensionManager.sidebarTab, definition);
    return "sidebarTab.registerSidebarTab";
  }
  const compatible = extensionManager?.registerSidebarTab;
  if (typeof compatible === "function") {
    compatible.call(extensionManager, definition);
    return "registerSidebarTab";
  }
  throw new Error("Conditioning Layers requires the validated ComfyUI sidebar contract.");
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function labelledControl(labelText, control) {
  const label = element("label", "cl-field");
  label.append(element("span", "cl-label", labelText), control);
  return label;
}

function installStylesheet() {
  const id = "conditioning-layers-styles";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = new URL("../conditioning_layers.css", import.meta.url).href;
  document.head.append(link);
}

const PREVIEW_DISCLAIMER = "Preview only. Python validation decides whether this field can execute.";

function renderFieldPreview(previews, layer) {
  const block = element("figure", "cl-preview");
  const record = previews.get(layer.rowId);
  const caption = element("figcaption", "cl-preview-meta");
  if (!record || record.state === "none") {
    block.classList.add("cl-preview-none");
    block.append(element("span", "cl-preview-placeholder", "No Influence Field selected."));
    return block;
  }
  if (record.state === "invalid") {
    block.classList.add("cl-preview-invalid");
    block.append(element("span", "cl-preview-placeholder", record.message ?? "Preview unavailable."));
    caption.textContent = PREVIEW_DISCLAIMER;
    block.append(caption);
    return block;
  }
  const image = document.createElement("img");
  image.className = "cl-preview-img";
  image.alt = `Influence Field preview for ${layer.name}`;
  image.decoding = "async";
  const describe = (current) => {
    const size = current.width !== null && current.height !== null
      ? ` — ${current.width}×${current.height} px`
      : "";
    const origin = current.source === "persisted"
      ? "Saved field (verified when opened)"
      : current.label;
    caption.textContent = `${origin}${size}. ${PREVIEW_DISCLAIMER}`;
  };
  if (record.state === "loading") {
    caption.textContent = `Loading preview… ${PREVIEW_DISCLAIMER}`;
  } else {
    describe(record);
  }
  const url = record.url;
  image.addEventListener("load", () => {
    const updated = previews.markLoaded(layer.rowId, url, image.naturalWidth, image.naturalHeight);
    if (updated) {
      block.classList.remove("cl-preview-loading");
      describe(updated);
    }
  });
  image.addEventListener("error", () => {
    const updated = previews.markFailed(
      layer.rowId,
      url,
      record.source === "persisted"
        ? "The saved Influence Field could not be loaded."
        : "This file could not be displayed as a PNG.",
    );
    if (updated) {
      block.classList.add("cl-preview-invalid");
      image.remove();
      block.prepend(element("span", "cl-preview-placeholder", updated.message));
      caption.textContent = PREVIEW_DISCLAIMER;
    }
  });
  if (record.state === "loading") block.classList.add("cl-preview-loading");
  image.src = url;
  block.append(image, caption);
  return block;
}

function renderPanel(container) {
  const store = createLayerStore();
  const previews = createPreviewRegistry();
  const fieldSelections = new WeakMap();
  const state = {
    pending: false,
    blocked: false,
    executionId: null,
    idempotencyKey: null,
    disposed: false,
    documentKey: null,
    documentId: null,
    documentName: null,
    guidance: null,
    presets: [],
    presetMessage: "Loading presets…",
    pendingKind: null,
    operation: 0,
    listOperation: 0,
    baseline: null,
    lastRun: null,
    lastSuccessfulSeed: null,
  };
  const root = element("section", "conditioning-layers-panel");
  const header = element("header", "cl-header");
  header.append(
    element("h2", "cl-title", "Conditioning Layers"),
    element("p", "cl-experimental", "Prediction Mixing is Experimental."),
  );
  const basePrompt = document.createElement("textarea");
  basePrompt.rows = 5;
  basePrompt.placeholder = "Describe the overall scene";
  const composition = document.createElement("select");
  composition.setAttribute("aria-label", "Composition");
  const compositionGuidance = element("p", "cl-guidance");
  const stack = element("div", "cl-stack");
  const activeGuidance = element("p", "cl-guidance", "Loading Active Layer capability…");
  const orderGuidance = element("p", "cl-guidance");
  const capabilityDetails = element("details", "cl-capabilities");
  capabilityDetails.open = true;
  const capabilitySummary = element("summary", "cl-label", "Current backend limitations");
  const profileGuidance = element("p", "cl-guidance");
  const overlapGuidance = element("p", "cl-guidance");
  const capabilityFindings = element("ul", "cl-findings");
  capabilityDetails.append(capabilitySummary, profileGuidance, overlapGuidance, capabilityFindings);
  const documentControls = element("div", "cl-document-controls");
  const newButton = element("button", "cl-button cl-button-secondary", "New Document");
  newButton.type = "button";
  const saveButton = element("button", "cl-button cl-button-secondary", "Save");
  saveButton.type = "button";
  const saveAsButton = element("button", "cl-button cl-button-secondary", "Save As");
  saveAsButton.type = "button";
  const documentName = document.createElement("input");
  documentName.type = "text";
  documentName.placeholder = "Document name";
  documentName.setAttribute("aria-label", "Document name");
  documentName.title = "To change a saved document's name, enter a new name and use Save As.";
  const documentStatus = element("p", "cl-document-status");
  documentStatus.setAttribute("role", "status");
  const nameGuidance = element("p", "cl-guidance", "Name changes to saved documents use Save As.");
  const documentPicker = document.createElement("select");
  documentPicker.setAttribute("aria-label", "Saved Conditioning Layers document");
  const openButton = element("button", "cl-button cl-button-secondary", "Open");
  openButton.type = "button";
  documentControls.append(
    newButton,
    saveButton,
    saveAsButton,
    documentName,
    documentPicker,
    openButton,
  );
  const addButton = element("button", "cl-button cl-button-secondary", "Add Layer");
  addButton.type = "button";
  const generateButton = element("button", "cl-button cl-button-primary", "Generate");
  generateButton.type = "button";
  const status = element("p", "cl-status", "Ready.");
  status.setAttribute("role", "status");
  const findings = element("ul", "cl-findings");
  const output = element("div", "cl-output");
  const seedMode = document.createElement("select");
  seedMode.setAttribute("aria-label", "Next generation seed");
  const newSeed = element("option", "", "New seed each run");
  newSeed.value = "new";
  const reuseSeed = element("option", "", "Reuse last successful seed");
  reuseSeed.value = "reuse";
  reuseSeed.disabled = true;
  seedMode.append(newSeed, reuseSeed);
  seedMode.value = "new";
  const seedSummary = element("p", "cl-seed-summary");
  const lastRun = element("p", "cl-last-run");

  function captureEditor() {
    return store.capture(basePrompt.value, documentName.value);
  }

  function editorFingerprint() { return store.fingerprint(captureEditor()); }
  // The storage-derived display name is not part of generated document intent.
  function runFingerprint() { return store.fingerprint({ ...captureEditor(), displayName: "" }); }
  function isDirty() { return editorFingerprint() !== state.baseline; }
  function currentOperation(token) { return !state.disposed && token === state.operation; }

  function renderDocumentState() {
    if (state.disposed) return;
    const dirty = isDirty();
    documentStatus.dataset.dirty = String(dirty);
    documentStatus.textContent = dirty ? "Unsaved changes."
      : state.documentKey ? "Clean — all changes saved." : "Clean — new document (not saved yet).";
    reuseSeed.disabled = state.lastSuccessfulSeed === null;
    seedSummary.textContent = seedMode.value === "reuse" && state.lastSuccessfulSeed !== null
      ? `Next seed: ${state.lastSuccessfulSeed} — reuse last successful seed.`
      : "Next seed: automatic — a new seed for each Generate.";
    lastRun.textContent = state.lastRun
      ? `Last run: ${state.lastRun.status}. Seed: ${state.lastRun.seed ?? "not available"}. ${
        runFingerprint() === state.lastRun.fingerprint
          ? "Document matches this run." : "Document changed since this run."
      }`
      : "No run for this document in this panel session.";
  }

  function confirmDiscard() {
    return !isDirty() || globalThis.confirm("Discard unsaved changes to this Conditioning Document?");
  }

  function resetRun() {
    state.lastRun = null;
    state.lastSuccessfulSeed = null;
    seedMode.value = "new";
    showOutput(null);
  }

  function renderActiveGuidance() {
    const count = store.layers.filter((layer) => layer.active).length;
    activeGuidance.textContent = state.guidance
      ? `${count} Active. ${state.guidance.active_guidance}`
      : "Active Layer capability unavailable. Python validates before generation.";
    const selected = store.compositionPolicy?.policy_identifier
      ?? "conditioning-layers.composition-policy.require-no-overlap.v1";
    composition.replaceChildren();
    for (const policy of state.guidance?.composition_policies ?? []) {
      const available = policy.supported_active_layer_counts.length > 0;
      const option = element("option", "", policy.display_name + (available ? "" : " — Save only"));
      option.value = policy.policy_identifier;
      composition.append(option);
    }
    composition.value = selected;
    composition.disabled = !state.guidance?.composition_policies;
    compositionGuidance.textContent = selected.endsWith("normalized-blend.v1")
      ? (state.guidance?.blend_guidance ?? "Blend generation is unavailable. Policy is preserved for Save.")
      : store.compositionPolicy ? state.guidance?.explicit_no_overlap_guidance ?? "Explicit No Overlap generation is unavailable."
      : "No Overlap: overlapping Influence Fields are rejected before generation.";
  }

  function renderRows() {
    renderActiveGuidance();
    renderDocumentState();
    stack.replaceChildren();
    if (store.layers.length === 0) {
      stack.append(element("p", "cl-empty", "No Prompt Layers. Add one or Generate to see Python validation."));
      return;
    }
    store.layers.forEach((layer, index) => {
      const row = element("article", "cl-layer");
      row.dataset.rowId = layer.rowId;
      const heading = element("div", "cl-layer-heading");
      heading.append(element("strong", "cl-order", `${index + 1}`));
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = layer.active;
      active.addEventListener("change", () => {
        layer.active = active.checked;
        renderActiveGuidance();
        renderDocumentState();
      });
      heading.append(labelledControl("Active", active));
      const up = element("button", "cl-icon-button", "Up");
      up.type = "button";
      up.disabled = index === 0;
      up.addEventListener("click", () => { store.moveLayer(layer.rowId, -1); renderRows(); });
      const down = element("button", "cl-icon-button", "Down");
      down.type = "button";
      down.disabled = index === store.layers.length - 1;
      down.addEventListener("click", () => { store.moveLayer(layer.rowId, 1); renderRows(); });
      const remove = element("button", "cl-icon-button cl-remove", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => {
        previews.release(layer.rowId);
        store.removeLayer(layer.rowId);
        renderRows();
      });
      heading.append(up, down, remove);

      const name = document.createElement("input");
      name.className = "cl-editor";
      name.dataset.control = "name";
      name.type = "text";
      name.value = layer.name;
      name.addEventListener("input", () => { layer.name = name.value; renderDocumentState(); });
      const prompt = document.createElement("textarea");
      prompt.className = "cl-editor";
      prompt.dataset.control = "prompt";
      prompt.rows = 3;
      prompt.value = layer.promptText;
      prompt.placeholder = "Describe this spatial prompt influence";
      prompt.addEventListener("input", () => { layer.promptText = prompt.value; renderDocumentState(); });
      const strength = document.createElement("input");
      strength.className = "cl-editor";
      strength.dataset.control = "strength";
      strength.type = "number";
      strength.step = "0.01";
      strength.value = String(layer.strength);
      strength.addEventListener("input", () => { layer.strength = strength.valueAsNumber; renderDocumentState(); });
      const file = document.createElement("input");
      file.type = "file";
      file.accept = "image/png";
      const presetSelect = element("select", "cl-preset-select");
      const unselected = element("option", "", "Select preset");
      unselected.value = "";
      unselected.disabled = true;
      presetSelect.append(unselected);
      for (const preset of state.presets) {
        const option = element("option", "", preset.display_name);
        option.value = preset.id;
        presetSelect.append(option);
      }
      presetSelect.value = layer.presetId ?? "";
      presetSelect.disabled = state.pending || state.presets.length === 0;
      presetSelect.addEventListener("change", async () => {
        if (state.pending) return;
        const presetId = presetSelect.value;
        const selection = {};
        fieldSelections.set(layer, selection);
        setPending(true);
        status.textContent = "Loading Influence Field preset…";
        try {
          const field = await loadPresetField(presetId, state.presets, (url) => api.fetchApi(url));
          // A removed row or a newer custom selection must win over this fetch.
          if (state.disposed || fieldSelections.get(layer) !== selection || !store.layers.includes(layer)) return;
          assignField(field, presetId);
          renderRows();
          status.textContent = "Influence Field preset selected.";
        } catch (error) {
          if (!state.disposed) status.textContent = error instanceof DraftTransportError
            ? error.message
            : "Preset could not be loaded. Try again or import a Custom PNG.";
        } finally {
          if (fieldSelections.get(layer) === selection) fieldSelections.delete(layer);
          if (!state.disposed) {
            presetSelect.value = layer.presetId ?? "";
            setPending(false);
          }
        }
      });
      const selected = element(
        "span",
        "cl-file-name",
        layer.presetId
          ? `Selected preset: ${state.presets.find((item) => item.id === layer.presetId)?.display_name ?? "Unavailable"}`
          : layer.field
          ? `Selected: ${layer.field.name}`
          : layer.persistedField
            ? "Saved Influence Field"
            : "No PNG selected",
      );
      let preview = renderFieldPreview(previews, layer);
      const replacePreview = () => {
        const replacement = renderFieldPreview(previews, layer);
        preview.replaceWith(replacement);
        preview = replacement;
      };
      const assignField = (field, presetId = null) => {
        if (!store.assignField(layer.rowId, field, presetId)) return;
        fieldSelections.delete(layer);
        presetSelect.value = presetId ?? "";
        previews.setUpload(layer.rowId, field);
        selected.textContent = `Selected: ${field.name}`;
        replacePreview();
        renderDocumentState();
      };
      file.addEventListener("change", () => {
        const field = file.files?.[0];
        if (!field) return;
        assignField(field);
        status.textContent = "Custom PNG selected.";
      });
      row.append(
        heading,
        labelledControl("Layer name", name),
        labelledControl("Prompt", prompt),
        labelledControl("Strength", strength),
        element("p", "cl-guidance", state.guidance?.strength_guidance ?? "Strength guidance unavailable."),
        element("span", "cl-label", "Influence Field"),
        labelledControl("Preset", presetSelect),
        element("p", "cl-guidance", state.presetMessage),
        labelledControl("Custom PNG", file),
        selected,
        preview,
        element("p", "cl-guidance", "White = stronger influence. Black = weaker/no influence. Field values request spatial influence, not exact visual coverage."),
      );
      stack.append(row);
    });
  }

  function showFindings(items = []) {
    findings.replaceChildren();
    for (const item of items) {
      // Persistent capability notices stay visible above Generate after a run.
      if (item.severity === "warning" && !item.layer
        && state.guidance?.findings.some((notice) => notice.code === item.code)) continue;
      const prefix = item.layer ? `${item.layer}: ` : "";
      const entry = element("li", `cl-finding cl-${item.severity}`, `${prefix}${item.message}`);
      entry.dataset.code = item.code;
      findings.append(entry);
    }
  }

  function showOutput(record) {
    output.replaceChildren();
    if (!record?.view_url) return;
    const image = document.createElement("img");
    image.alt = "Conditioning Layers generated result";
    image.src = record.view_url;
    image.loading = "lazy";
    const link = element("a", "cl-output-link", "Open result");
    link.href = record.view_url;
    link.target = "_blank";
    link.rel = "noopener";
    output.append(image, link);
  }

  function setPending(value, kind = null) {
    state.pending = value;
    state.pendingKind = value ? kind : null;
    generateButton.disabled = value || state.blocked;
    addButton.disabled = value && kind !== "save" && kind !== "open";
    // An older disk write must finish before another document is opened.
    // Open itself is read-only and may safely be superseded by New/Open.
    const replacingDocument = kind === "open";
    newButton.disabled = value && !replacingDocument;
    saveButton.disabled = value;
    saveAsButton.disabled = value;
    openButton.disabled = value && !replacingDocument;
    documentPicker.disabled = value && !replacingDocument;
    seedMode.disabled = value;
    stack.querySelectorAll(".cl-preset-select").forEach((select) => {
      select.disabled = value || state.presets.length === 0;
    });
  }

  function documentState() {
    return { documentKey: state.documentKey, documentId: state.documentId };
  }

  function applyDocument(record) {
    // Validate policy before changing document ownership or any editor content.
    store.replaceFromDocument(record);
    state.documentKey = record.document_key;
    state.documentId = record.document_id;
    state.documentName = record.display_name;
    documentName.value = record.display_name;
    basePrompt.value = record.base_prompt;
    previews.releaseAll();
    for (const layer of store.layers) {
      if (layer.persistedField && layer.fieldUrl) {
        previews.setPersisted(layer.rowId, layer.fieldUrl);
      }
    }
    state.baseline = editorFingerprint();
    resetRun();
    renderRows();
    status.textContent = `Opened ${record.display_name}.`;
    showFindings([]);
  }

  async function refreshDocuments(selectedKey) {
    const listToken = ++state.listOperation;
    const response = await api.fetchApi(DOCUMENT_ENDPOINT);
    const payload = await response.json();
    if (state.disposed || listToken !== state.listOperation) return;
    if (!response.ok) throw new Error("Saved documents could not be listed.");
    const selection = selectedKey ?? (documentPicker.value || state.documentKey);
    documentPicker.replaceChildren();
    const placeholder = element("option", "", "Select a saved document");
    placeholder.value = "";
    documentPicker.append(placeholder);
    for (const record of payload.documents ?? []) {
      const option = element("option", "", record.display_name);
      option.value = record.document_key;
      option.selected = record.document_key === selection;
      documentPicker.append(option);
    }
  }

  function newDocument() {
    if (state.disposed || (state.pending && state.pendingKind !== "open")) return;
    if (!confirmDiscard()) return;
    state.operation += 1;
    setPending(false);
    state.documentKey = null;
    state.documentId = null;
    state.documentName = null;
    documentName.value = "";
    basePrompt.value = "";
    previews.releaseAll();
    store.clear();
    store.addLayer();
    state.baseline = editorFingerprint();
    resetRun();
    renderRows();
    documentPicker.value = "";
    status.textContent = "New unsaved document.";
    showFindings([]);
  }

  async function persistDocument(saveAs) {
    if (state.pending || state.disposed) return;
    let displayName = state.documentName;
    if (!saveAs && state.documentKey && documentName.value !== state.documentName) {
      status.textContent = "Use Save As to save with a different document name, or restore the current name.";
      return;
    }
    if (saveAs || !state.documentKey) {
      displayName = documentName.value.trim();
      if (!displayName) {
        status.textContent = "Enter a document name before using Save As.";
        showFindings([]);
        return;
      }
    }
    const snapshot = captureEditor();
    const submitted = { ...snapshot, displayName };
    const ownership = { ...documentState(), saveAs };
    let body;
    try {
      body = store.toDocumentMultipart(basePrompt.value, displayName, ownership, submitted);
    } catch (error) {
      if (error instanceof DraftTransportError) {
        status.textContent = error.message;
        showFindings([]);
        return;
      }
      throw error;
    }
    const token = ++state.operation;
    setPending(true, "save");
    status.textContent = "Saving document…";
    showFindings([]);
    try {
      const endpoint = saveAs || !state.documentKey
        ? DOCUMENT_ENDPOINT
        : `${DOCUMENT_ENDPOINT}/${encodeURIComponent(state.documentKey)}`;
      const response = await api.fetchApi(endpoint, {
        method: saveAs || !state.documentKey ? "POST" : "PUT",
        body,
      });
      const payload = await response.json();
      if (!currentOperation(token)) return;
      if (!response.ok) {
        showFindings(payload.findings);
        status.textContent = payload.findings?.[0]?.message ?? "Save failed.";
        return;
      }
      // Bind server identities to the captured rows, never replace newer content.
      const acknowledged = store.acceptSaved(submitted, payload, ownership);
      state.documentKey = acknowledged.documentKey;
      state.documentId = acknowledged.documentId;
      state.documentName = acknowledged.displayName;
      if (documentName.value === snapshot.displayName) documentName.value = acknowledged.displayName;
      state.baseline = store.fingerprint({ ...snapshot, displayName: acknowledged.displayName });
      previews.releaseAll();
      for (const layer of store.layers) {
        if (layer.field) previews.setUpload(layer.rowId, layer.field);
        else if (layer.persistedField && layer.fieldUrl) previews.setPersisted(layer.rowId, layer.fieldUrl);
      }
      const focused = document.activeElement;
      const focusedRow = focused?.closest?.(".cl-layer")?.dataset.rowId;
      const selection = [focused?.selectionStart, focused?.selectionEnd];
      renderRows();
      // A Save acknowledgement must not interrupt typing into a surviving row.
      if (focusedRow && focused.dataset.control) {
        const row = [...stack.querySelectorAll(".cl-layer")].find((item) => item.dataset.rowId === focusedRow);
        const control = [...(row?.querySelectorAll(".cl-editor") ?? [])]
          .find((item) => item.dataset.control === focused.dataset.control);
        control?.focus();
        if (control && selection.every((value) => typeof value === "number")) {
          control.setSelectionRange(...selection);
        }
      }
      status.textContent = isDirty()
        ? `Saved ${acknowledged.displayName}. Newer edits remain unsaved.`
        : `Saved ${acknowledged.displayName}.`;
      try {
        await refreshDocuments(acknowledged.documentKey);
      } catch (_error) {
        if (currentOperation(token)) status.textContent += " Saved document list could not be refreshed.";
      }
    } catch (error) {
      if (currentOperation(token)) status.textContent = error instanceof SaveAcknowledgementError
        ? error.message : "Save could not be confirmed. Your current edits are preserved.";
    } finally {
      if (currentOperation(token)) setPending(false);
    }
  }

  async function openSelectedDocument() {
    if (state.disposed || !documentPicker.value
      || (state.pending && state.pendingKind !== "open")) return;
    if (!confirmDiscard()) return;
    const selectedKey = documentPicker.value;
    const fingerprint = editorFingerprint();
    const token = ++state.operation;
    setPending(true, "open");
    status.textContent = "Opening document…";
    showFindings([]);
    try {
      const response = await api.fetchApi(
        `${DOCUMENT_ENDPOINT}/${encodeURIComponent(selectedKey)}`,
        { headers: { "X-Conditioning-Layers-Policy-Editor": "1" } },
      );
      const payload = await response.json();
      if (!currentOperation(token)) return;
      if (!response.ok) {
        showFindings(payload.findings);
        status.textContent = payload.findings?.[0]?.message ?? "Open failed.";
        return;
      }
      if (editorFingerprint() !== fingerprint) {
        status.textContent = "Open cancelled because you edited while it was loading. Your edits are preserved; choose Open again when ready.";
        return;
      }
      applyDocument(payload);
    } catch (_error) {
      if (currentOperation(token)) status.textContent = "Open failed. Your current document is preserved.";
    } finally {
      if (currentOperation(token)) setPending(false);
    }
  }

  function recordRun(payload, fingerprint) {
    // uint64 seeds never cross the browser boundary as Numbers.
    const seed = typeof payload.seed === "string" && /^(0|[1-9][0-9]{0,19})$/.test(payload.seed)
      && BigInt(payload.seed) <= 18446744073709551615n ? payload.seed : null;
    state.lastRun = {
      status: payload.state || "unknown", seed, fingerprint,
    };
    if (payload.terminal && payload.state === "completed" && seed !== null) {
      state.lastSuccessfulSeed = seed;
    }
    renderDocumentState();
  }

  async function poll(executionId, token, fingerprint) {
    // One read recovery budget belongs to this known execution, not each poll.
    // Submission and its irreversible request identity never enter this path.
    let reobserveAvailable = true;
    const seed = state.lastRun?.seed;
    if (typeof executionId !== "string" || executionId.length !== 32
      || !/^[a-f0-9]{32}$/.test(executionId) || seed === null) {
      throw new Error("Execution association unavailable.");
    }
    while (currentOperation(token)) {
      let response;
      let transportFailed = false;
      try {
        response = await api.fetchApi(`${EXECUTION_ENDPOINT}/${executionId}`);
      } catch (_error) {
        transportFailed = true;
      }
      if (!currentOperation(token)) return;
      if (transportFailed || (response.status >= 500 && response.status <= 599)) {
        if (!reobserveAvailable) throw new Error("Execution state unavailable.");
        reobserveAvailable = false;
        status.textContent = "Execution observation interrupted. Checking the same run once…";
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (!currentOperation(token)) return;
        // No catch around this second acquisition: any failure fails closed.
        response = await api.fetchApi(`${EXECUTION_ENDPOINT}/${executionId}`);
        if (!currentOperation(token)) return;
      }
      // Parsing, authoritative state validation and rendering are never retried.
      if (!response.ok) throw new Error("Execution state unavailable.");
      const payload = await response.json();
      if (!currentOperation(token)) return;
      validateObservation(payload, executionId, seed);
      recordRun(payload, fingerprint);
      status.textContent = payload.state || "Unknown state";
      showFindings(payload.findings);
      if (payload.terminal) {
        if (payload.state === "completed") showOutput(payload.output);
        state.idempotencyKey = null;
        state.executionId = null;
        setPending(false);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  function validateObservation(payload, executionId, seed) {
    const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
    const terminal = ["completed", "failed", "rejected"];
    if (typeof executionId !== "string" || executionId.length !== 32 || !/^[a-f0-9]{32}$/.test(executionId)
      || !object(payload) || payload.execution_id !== executionId
      || !["accepted", "validating", "preparing", "executing", ...terminal].includes(payload.state)
      || payload.terminal !== terminal.includes(payload.state)
      || !Array.isArray(payload.findings) || payload.findings.some((finding) => !object(finding)
        || typeof finding.code !== "string" || typeof finding.message !== "string"
        || !["error", "warning", "information"].includes(finding.severity)
        || (finding.layer !== undefined && typeof finding.layer !== "string"))
      || typeof payload.seed !== "string" || payload.seed.trim() !== payload.seed
      || !/^(0|[1-9][0-9]{0,19})$/.test(payload.seed)
      || BigInt(payload.seed) > 18446744073709551615n
      || (seed !== null && payload.seed !== seed)) {
      throw new Error("Execution state unavailable.");
    }
    if (payload.state !== "completed") {
      if (payload.output !== undefined) throw new Error("Unexpected execution output.");
      return;
    }
    // The Python execution authority owns history association; verify that its
    // projected locator still names this exact execution before applying success.
    const record = payload.output;
    if (!object(record) || record.type !== "output" || record.subfolder !== "conditioning-layers-panel"
      || typeof record.filename !== "string" || !record.filename.startsWith(`${executionId}_`)
      || !record.filename.endsWith(".png") || !/^[0-9]+_\.png$/.test(record.filename.slice(executionId.length + 1))
      || typeof record.view_url !== "string" || !record.view_url.startsWith("/view?")) {
      throw new Error("Execution output association unavailable.");
    }
    const url = new URL(record.view_url, "http://localhost");
    if (url.pathname !== "/view" || url.hash || [...url.searchParams].length !== 3
      || ["filename", "subfolder", "type"].some((key) => url.searchParams.get(key) !== record[key])) {
      throw new Error("Execution output association unavailable.");
    }
  }

  async function generateOnce() {
    if (state.pending || state.blocked) return;
    if (state.disposed) return;
    state.idempotencyKey = crypto.randomUUID();
    const fingerprint = runFingerprint();
    const selectedSeed = seedMode.value === "reuse" && state.lastSuccessfulSeed !== null
      ? state.lastSuccessfulSeed : undefined;
    let body;
    try {
      body = store.toMultipart(basePrompt.value, state.idempotencyKey, documentState(), selectedSeed);
    } catch (error) {
      if (error instanceof DraftTransportError) {
        status.textContent = error.message;
        showFindings([]);
        state.idempotencyKey = null;
        return;
      }
      throw error;
    }
    const token = ++state.operation;
    setPending(true, "generate");
    state.lastRun = { status: "submitting", seed: selectedSeed ?? null, fingerprint };
    renderDocumentState();
    status.textContent = "Submitting once…";
    showFindings([]);
    showOutput(null);
    try {
      const response = await api.fetchApi(EXECUTION_ENDPOINT, { method: "POST", body });
      const payload = await response.json();
      if (!currentOperation(token)) return;
      // A successful acknowledgement must establish authoritative association
      // before it can update seed state or become eligible for read recovery.
      if (response.ok) validateObservation(payload, payload?.execution_id, selectedSeed ?? null);
      recordRun(payload, fingerprint);
      showFindings(payload.findings);
      if (!response.ok || !payload.execution_id) {
        status.textContent = payload.state || "Request rejected";
        state.idempotencyKey = null;
        setPending(false);
        return;
      }
      state.executionId = payload.execution_id;
      status.textContent = payload.state;
      await poll(payload.execution_id, token, fingerprint);
    } catch (_error) {
      if (!currentOperation(token)) return;
      state.blocked = true;
      status.textContent = "Submission state is unknown. Reload the panel before generating again.";
      if (state.lastRun) state.lastRun.status = "unknown";
      renderDocumentState();
      setPending(false);
    }
  }

  addButton.addEventListener("click", () => { store.addLayer(); renderRows(); });
  newButton.addEventListener("click", newDocument);
  saveButton.addEventListener("click", () => persistDocument(false));
  saveAsButton.addEventListener("click", () => persistDocument(true));
  openButton.addEventListener("click", openSelectedDocument);
  generateButton.addEventListener("click", generateOnce);
  basePrompt.addEventListener("input", renderDocumentState);
  composition.addEventListener("change", () => {
    store.selectComposition(composition.value);
    renderActiveGuidance();
    renderDocumentState();
  });
  documentName.addEventListener("input", renderDocumentState);
  seedMode.addEventListener("change", renderDocumentState);
  store.addLayer();
  state.baseline = editorFingerprint();
  renderRows();
  root.append(
    header,
    documentControls,
    nameGuidance,
    documentStatus,
    labelledControl("Base Prompt", basePrompt),
    labelledControl("Composition", composition),
    compositionGuidance,
    element("h3", "cl-section-title", "Prompt Layers"),
    activeGuidance,
    orderGuidance,
    stack,
    addButton,
    capabilityDetails,
    labelledControl("Next generation seed", seedMode),
    seedSummary,
    lastRun,
    generateButton,
    status,
    findings,
    output,
  );
  container.replaceChildren(root);
  const initialOperation = state.operation;
  refreshDocuments().catch(() => {
    if (currentOperation(initialOperation)) status.textContent = "Saved documents could not be listed.";
  });
  loadPresetCatalog((url) => api.fetchApi(url)).then((presets) => {
    if (state.disposed) return;
    state.presets = presets;
    state.presetMessage = presets.length ? ""
      : "No product presets available. Custom PNG import remains available.";
    renderRows();
  }).catch(() => {
    if (state.disposed) return;
    state.presetMessage = "Preset catalog unavailable. Reload the sidebar to retry, or import a Custom PNG.";
    renderRows();
  });
  api.fetchApi("/conditioning-layers/capabilities").then(async (response) => {
    if (!response.ok) throw new Error("Capability guidance unavailable.");
    const guidance = await response.json();
    if (state.disposed) return;
    state.guidance = guidance;
    orderGuidance.textContent = guidance.order_guidance;
    profileGuidance.textContent = guidance.profile_guidance;
    overlapGuidance.textContent = guidance.overlap_guidance;
    for (const finding of guidance.findings) {
      const entry = element("li", "cl-finding cl-warning", finding.message);
      entry.dataset.code = finding.code;
      capabilityFindings.append(entry);
    }
    renderRows();
  }).catch(() => {
    if (state.disposed) return;
    renderActiveGuidance();
    profileGuidance.textContent = "Capability guidance could not be loaded. Reload the sidebar to retry.";
  });
  return () => {
    state.disposed = true;
    state.operation += 1;
    previews.releaseAll();
    container.replaceChildren();
  };
}

app.registerExtension({
  name: EXTENSION_NAME,
  setup() {
    installStylesheet();
    registerSidebarCompatibility(app.extensionManager, {
      id: "conditioning-layers",
      icon: "pi pi-clone",
      title: "Conditioning Layers",
      tooltip: "Author experimental Prompt Layers",
      type: "custom",
      render: renderPanel,
    });
  },
});
