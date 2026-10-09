import {app} from "../../../scripts/app.js";

// Register independently of the core. The stored value never depends on decoding.
const ADVANCED = "ConditioningLayers.InfluenceFieldEditor.AdvancedExpanded";
// Nested Advanced groups, keyed as the editor names them. UI preferences only, never node state.
const GROUPS = {
  behavior: {id: "ConditioningLayers.InfluenceFieldEditor.BrushBehaviorExpanded", name: "Brush Behavior"},
  shape: {id: "ConditioningLayers.InfluenceFieldEditor.BrushShapeExpanded", name: "Brush Shape & Transform"},
  profile: {id: "ConditioningLayers.InfluenceFieldEditor.ValueProfileExpanded", name: "Value Profile"},
  fieldTools: {id: "ConditioningLayers.InfluenceFieldEditor.FieldToolsExpanded", name: "Field Tools"},
  tip: {id: "ConditioningLayers.InfluenceFieldEditor.CustomTipExpanded", name: "Custom Tip"},
  procedural: {id: "ConditioningLayers.InfluenceFieldEditor.ProceduralTipExpanded", name: "Procedural Tip"},
  pressure: {id: "ConditioningLayers.InfluenceFieldEditor.PenPressureExpanded", name: "Pen Pressure"},
};
const editors = new WeakMap();
let sessionToken = null;
function fieldWidget(node) {
  const widgets = node?.widgets?.filter(w => w.type === "CONDITIONING_LAYERS_PAINTED_FIELD") ?? [];
  return widgets.length === 1 ? widgets[0] : null;
}
function fieldLabel(node) {
  const title = Array.from(typeof node.title === "string" && node.title.trim() ? node.title.trim() : "Painted Field");
  return `${title.length > 40 ? title.slice(0, 39).join("") + "…" : title.join("")} #${node.id}`;
}
function compareNodeIds(a, b) {
  // Digit-only strings (including leading zeros) compare exactly, without
  // changing node identity. Equal representations retain the stable list order.
  const integer = id => typeof id === "number" && Number.isInteger(id) && id >= 0
    ? BigInt(id) : typeof id === "string" && /^\d+$/.test(id) ? BigInt(id) : null;
  const left = integer(a), right = integer(b);
  if (left !== null && right !== null) return left < right ? -1 : left > right ? 1 : 0;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number") return -1;
  if (typeof b === "number") return 1;
  return String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0;
}
let brushLibrary = null;
// Public user-data API, loaded only on request: core registration never depends on library storage.
async function getBrushLibrary() {
  if (!brushLibrary) brushLibrary = (async () => {
    const {api} = await import("../../../scripts/api.js");
    const {createBrushLibrary, LIBRARY_FILE} = await import("./field_editor/brush_library.js");
    return createBrushLibrary({
      async read() {
        const response = await api.getUserData(LIBRARY_FILE);
        if (response.status === 404) return null;
        if (!response.ok) throw new Error(`Cannot read brush library (${response.status}).`);
        return response.text();
      },
      async write(text) {
        const response = await api.storeUserData(LIBRARY_FILE, text,
          {overwrite: true, stringify: false, throwOnError: true});
        if (!response.ok) throw new Error(`Cannot save brush library (${response.status}).`);
      },
    });
  })().catch(error => { brushLibrary = null; throw error; });
  return brushLibrary;
}

function paintedWidget(node, inputName, inputData) {
  let value = inputData[1]?.default ?? "", opening = false, thumbnailRevision = 0;
  const container = document.createElement("div");
  const thumbnail = document.createElement("canvas");
  thumbnail.width = thumbnail.height = 128;
  thumbnail.style.cssText = "width:96px;height:96px;image-rendering:pixelated;display:block;background:black";
  thumbnail.setAttribute("aria-label", "Influence Field thumbnail; double-click to edit");
  const edit = document.createElement("button"); edit.textContent = "Edit Field…"; edit.type = "button";
  const status = document.createElement("div"); status.setAttribute("role", "status");
  container.append(thumbnail, edit, status);

  async function refresh() {
    const revision = ++thumbnailRevision, snapshot = value;
    try {
      const codec = await import("./field_editor/png_codec.js");
      const codes = await codec.decodeFieldDataUrl(snapshot);
      if (revision !== thumbnailRevision) return;
      const context = thumbnail.getContext("2d"), pixels = context.createImageData(128, 128);
      for (let i = 0; i < codes.length; i++) {
        pixels.data[i * 4] = pixels.data[i * 4 + 1] = pixels.data[i * 4 + 2] = codes[i];
        pixels.data[i * 4 + 3] = 255;
      }
      context.putImageData(pixels, 0, 0); status.textContent = "";
    } catch (error) {
      if (revision === thumbnailRevision) {
        thumbnail.getContext("2d").clearRect(0, 0, 128, 128);
        status.textContent = `Field preview unavailable: ${error.message}. Stored value preserved.`;
      }
    }
  }
  const widget = node.addDOMWidget(inputName, "CONDITIONING_LAYERS_PAINTED_FIELD", container, {
    socketless: true,
    getValue: () => value,
    setValue: incoming => { value = incoming; void refresh(); },
  });
  async function open() {
    if (opening) return;
    opening = true;
    let token = null;
    const release = () => { if (token && sessionToken === token) { sessionToken = null; opening = false; } };
    try {
      if (sessionToken) throw new Error("another Influence Field Editor is open");
      // Graph restoration can replace nodes/widgets while retaining the visible DOM.
      // Resolve the executable widget afresh; this launcher's closure is not field authority.
      const graph = app.canvas?.graph, currentNode = graph?.getNodeById(node.id);
      const currentWidget = currentNode?.widgets?.find(candidate =>
        candidate.name === inputName && candidate.type === "CONDITIONING_LAYERS_PAINTED_FIELD");
      if (!currentWidget) throw new Error("The current Painted Field widget is unavailable. Reopen the node.");
      const original = currentWidget.value;
      const codec = await import("./field_editor/png_codec.js");
      const ui = await import("./field_editor/editor_ui.js");
      const originalCodes = await codec.decodeFieldDataUrl(original);
      if (sessionToken) throw new Error("another Influence Field Editor is open");
      const openingKey = String(currentNode.id);
      const members = new Map([[openingKey, {node: currentNode, widget: currentWidget, original,
        originalCodes, label: fieldLabel(currentNode)}]]);
      const graphError = () => new Error("The active graph changed while editing. Cancel and reopen.");
      const available = key => {
        const m = members.get(key);
        return !!m && app.canvas?.graph === graph && m.node.graph === graph
          && graph?.getNodeById(m.node.id) === m.node && m.node.widgets?.includes(m.widget) === true;
      };
      const conflict = (m, when) => new Error(members.size === 1
        ? `The stored field changed while ${when}. Cancel and reopen.`
        : `${m.label}: the stored field changed while ${when}. Remove it from this session to keep the other changes, or Cancel and reopen.`);
      async function commitFields(offer) {
        // Resolve and encode every offer before touching any host state.
        const plan = offer.map(item => {
          const m = members.get(item.key);
          if (!m) throw new Error("Unknown session field.");
          return {...item, ...m, changed: item.codes.some((c, i) => c !== m.originalCodes[i])};
        });
        for (const w of plan) if (w.widget.value !== w.original) throw conflict(w, "editing");
        for (const w of plan) if (w.changed) w.encoded = await codec.encodeFieldDataUrl(w.codes);
        for (const w of plan) if (w.widget.value !== w.original) throw conflict(w, "saving");
        const writes = plan.filter(w => w.changed || JSON.stringify(w.node.properties?.fieldEditor) !== JSON.stringify(w.settings));
        if (writes.length) {
          const canvas = app.canvas;
          if (canvas?.graph !== graph) throw graphError();
          for (const w of writes) if (!available(w.key)) throw members.size === 1 ? graphError()
            : new Error(`${w.label}: the field is no longer in this graph. Remove it from this session to keep the other changes, or Cancel and reopen.`);
          const bracket = writes.some(w => w.changed);
          if (bracket && (typeof canvas.emitBeforeChange !== "function" || typeof canvas.emitAfterChange !== "function"))
            throw new Error("Graph undo notifications are unavailable. Stored value preserved.");
          const remembered = [], notifications = [];
          let failure = null;
          // No await inside this bracket: the host captures one whole-graph snapshot.
          if (bracket) canvas.emitBeforeChange();
          try {
            for (const w of writes) {
              remembered.push({w, hadKey: Object.hasOwn(w.node.properties ?? {}, "fieldEditor"),
                settings: w.node.properties?.fieldEditor, value: w.widget.value});
              w.node.properties ??= {};
              w.node.properties.fieldEditor = {...w.settings};
              if (w.changed) {
                try { w.widget.value = w.encoded; }
                catch (error) { notifications.push(error); }
              }
            }
            const refused = writes.find(w => w.changed && w.widget.value !== w.encoded);
            if (refused) {
              for (const old of remembered.reverse()) {
                if (old.hadKey) old.w.node.properties.fieldEditor = old.settings;
                else delete old.w.node.properties.fieldEditor;
                if (old.w.widget.value !== old.value) {
                  try { old.w.widget.value = old.value; } catch { /* Stored value precedes callback. */ }
                }
              }
              failure = new Error(`${members.size > 1 ? refused.label + ": the" : "The"} stored value did not take the new field. Nothing was changed.`);
            }
          } finally {
            if (bracket) canvas.emitAfterChange();
            for (const w of writes) w.node.setDirtyCanvas?.(true, true);
          }
          if (failure) throw failure;
          if (notifications.length) throw members.size === 1 ? notifications[0]
            : new Error(`Saved, but a host notification failed: ${notifications[0].message} Cancel closes the editor; graph Undo reverts the save.`);
        }
        release();
      }
      const fields = {
        openingKey, openingLabel: members.get(openingKey).label, available, commit: commitFields,
        leave: key => { members.delete(key); },
        async candidates() {
          if (app.canvas?.graph !== graph) throw graphError();
          if (!Array.isArray(graph.nodes)) throw new Error("Field discovery is unavailable on this host.");
          const candidates = graph.nodes.filter(n => n.graph === graph && fieldWidget(n) && !members.has(String(n.id)))
            .sort((a, b) => compareNodeIds(a.id, b.id));
          const items = [];
          for (const n of candidates) {
            const item = {key: String(n.id), label: fieldLabel(n), codes: null, error: null};
            try { item.codes = await codec.decodeFieldDataUrl(fieldWidget(n).value); }
            catch (error) { item.error = error.message; }
            items.push(item);
          }
          return items;
        },
        async join(key) {
          if (members.has(key)) throw new Error(`${members.get(key).label} is already in this session.`);
          if (members.size >= 4) throw new Error("A session holds at most 4 fields.");
          if (app.canvas?.graph !== graph) throw graphError();
          const n = graph.getNodeById(key), w = fieldWidget(n);
          if (!w || n.graph !== graph) throw new Error("The field is no longer in this graph.");
          const value = w.value, decoded = await codec.decodeFieldDataUrl(value);
          if (w.value !== value) throw new Error("The stored field changed while it was being read.");
          const label = fieldLabel(n);
          members.set(key, {node: n, widget: w, original: value, originalCodes: decoded, label});
          return {key, label, codes: decoded.slice(), settings: n.properties?.fieldEditor};
        },
      };
      token = {}; sessionToken = token;
      ui.openInfluenceFieldEditor({codes: originalCodes, settings: currentNode.properties?.fieldEditor,
        host: {
          fields,
          getBrushLibrary,
          getAdvancedExpanded: () => app.ui.settings.getSettingValue(ADVANCED, false),
          setAdvancedExpanded: expanded => app.ui.settings.setSettingValue(ADVANCED, expanded),
          getGroupExpanded: group => app.ui.settings.getSettingValue(GROUPS[group].id, false),
          setGroupExpanded: (group, expanded) => app.ui.settings.setSettingValue(GROUPS[group].id, expanded),
          confirmDiscard: count => window.confirm(count > 1 ? `Discard changes to ${count} fields and their brush settings?` : "Discard field and brush-setting changes?"),
          confirmRemove: label => window.confirm(`Remove ${label} from this session and discard its changes?`),
        },
        onCancel: release,
        onDone: async (codes, settings) => commitFields([{key: openingKey, codes, settings}]),
      });
      status.textContent = "";
    } catch (error) {
      release();
      status.textContent = `Cannot open Influence Field Editor: ${error.message}. Stored value preserved.`;
      opening = false;
    }
  }
  edit.addEventListener("click", event => { event.stopPropagation(); void open(); });
  thumbnail.addEventListener("dblclick", event => { event.stopPropagation(); void open(); });
  editors.set(node, open);
  // Initial thumbnail is the empty default. Restoration calls setValue lazily.
  return {widget};
}

app.registerExtension({
  name: "conditioning-layers.influence-field-editor",
  settings: [{id: ADVANCED, name: "Influence Field Editor: expand Advanced", type: "boolean", defaultValue: false},
    ...Object.values(GROUPS).map(({id, name}) =>
      ({id, name: `Influence Field Editor: expand ${name}`, type: "boolean", defaultValue: false}))],
  getCustomWidgets() { return {CONDITIONING_LAYERS_PAINTED_FIELD: paintedWidget}; },
  getNodeMenuItems(node) {
    return editors.has(node) ? [{content: "Edit Influence Field…", callback: () => editors.get(node)()}] : [];
  },
});
