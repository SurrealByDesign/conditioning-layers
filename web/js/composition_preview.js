// Optional native-stack reader. No host imports, graph writes or normalization.
// Only the adapter supplies graph access, decoding and the preview transport.
const LAYER = "ConditioningLayersLayer", ADD = "ConditioningLayersAddLayer";
const COMPOSE = "ConditioningLayersCompose", GROUPED = "ConditioningLayersComposeGroups";
const PAINTED = "ConditioningLayersPaintedField";
const composeLabel = node => `${node.type === GROUPED ? "Blend Groups" : "Compose"} #${id(node)}`;
const fail = message => { throw new Error(message); };
const id = node => String(node.id);
function ordinary(node) {
  if (!node || (node.mode !== undefined && node.mode !== 0)) fail("Muted/bypassed or missing node");
  return node;
}
function input(node, name) {
  const found = node.inputs?.filter(i => i.name === name) ?? [];
  if (found.length !== 1) fail(`Node #${id(node)}: unresolved ${name} input`);
  return found[0];
}
function upstream(graph, node, name, optional = false, firstOutput = true) {
  const socket = input(node, name);
  if (socket.link == null) {
    if (optional) return null;
    fail(`Node #${id(node)}: ${name} is disconnected`);
  }
  const link = graph.links?.get?.(socket.link) ?? graph.links?.[socket.link];
  const slot = node.inputs.indexOf(socket);
  if (!link || String(link.target_id) !== id(node) || link.target_slot !== slot
      || !Number.isInteger(link.origin_slot) || link.origin_slot < 0 || (firstOutput && link.origin_slot !== 0))
    fail("Incomplete or unsupported link topology");
  const source = ordinary(graph.getNodeById(link.origin_id));
  if (source.graph !== graph) fail("Cross-graph connections are unsupported");
  return source;
}
function metadata(node, name) {
  const sockets = node.inputs?.filter(i => i.name === name) ?? [];
  if (sockets.some(i => i.link != null)) fail(`Layer #${id(node)}: dynamic ${name}`);
  // Native frontend widgets also have sockets. Only an explicit, unconnected
  // widget association can use the literal; a bare socket is not a fallback.
  if (sockets.length > 1 || sockets.some(i => i.link !== null || i.widget?.name !== name))
    fail(`Layer #${id(node)}: unresolved ${name}`);
  const widgets = node.widgets?.filter(w => w.name === name) ?? [];
  if (widgets.length !== 1) fail(`Layer #${id(node)}: unresolved ${name}`);
  return widgets[0].value;
}
// Optional input: with neither socket nor widget it is omitted, i.e. the default group.
// Python's LayerDescriptor remains the only validator of the literal key.
function blendGroup(node) {
  if (!node.inputs?.some(i => i.name === "blend_group") && !node.widgets?.some(w => w.name === "blend_group")) return "";
  const value = metadata(node, "blend_group");
  if (typeof value !== "string") fail(`Layer #${id(node)}: invalid Blend Group`);
  return value;
}
const groupName = key => key === "" ? "default group" : `group ${JSON.stringify(key)}`;
// Display only: names membership in first-occurrence order; no composition arithmetic.
function groupDiagnostics(layers, selected) {
  const groups = new Map(), fixed = [], disabled = [];
  for (const layer of layers) {
    if (!layer.enabled) disabled.push(layer.id);
    else if (layer.mode === "FIXED") fixed.push(layer.id);
    else groups.set(layer.group, [...groups.get(layer.group) ?? [], layer.id]);
  }
  const mark = ids => ids.map(layer => `#${layer}${layer === selected ? " (selected)" : ""}`).join(", ");
  const own = layers.find(layer => layer.id === selected);
  return {
    compact: !own.enabled ? null : own.mode === "FIXED" ? "FIXED · global" : groupName(own.group),
    detail: ["Compose Blend Groups", ...[...groups].map(([key, ids]) => `${groupName(key)}: ${mark(ids)}`),
      ...(fixed.length ? [`FIXED, global across groups: ${mark(fixed)}`] : []),
      ...(disabled.length ? [`disabled: ${mark(disabled)}`] : [])].join(" · "),
  };
}
function stack(graph, compose) {
  ordinary(compose);
  let add = upstream(graph, compose, "layers");
  const nodes = [], visited = new Set(), layers = new Set();
  while (add) {
    if (add.type !== ADD || visited.has(id(add))) fail("Unsupported or cyclic Add Layer chain");
    visited.add(id(add));
    const layer = upstream(graph, add, "layer");
    if (layer.type !== LAYER || layers.has(id(layer))) fail("Unsupported or repeated layer identity");
    layers.add(id(layer)); nodes.push(layer);
    add = upstream(graph, add, "layers", true);
  }
  return nodes.reverse();
}

export function createCompositionPreview({graph, currentGraph, decode, request, validateEdits}) {
  const identities = new WeakMap(); let serial = 0;
  const token = object => { if (!identities.has(object)) identities.set(object, ++serial); return identities.get(object); };
  let cache = new Map();
  function inspect(activeKey, edits, selected) {
    if (currentGraph() !== graph) fail("The active graph changed; reopen the editor");
    validateEdits(edits);
    if (!Array.isArray(graph.nodes)) fail("Graph discovery is unavailable");
    const choices = [];
    for (const compose of graph.nodes.filter(n => n.graph === graph && [COMPOSE, GROUPED].includes(n.type))) {
      try {
        const nodes = stack(graph, compose);
        const layers = nodes.map(node => {
          const strength = metadata(node, "strength"), mode = metadata(node, "mode"), enabled = metadata(node, "enabled");
          if (!Number.isFinite(strength) || strength < 0 || strength > 1 || !["FIXED", "BLENDED"].includes(mode)
              || typeof enabled !== "boolean") fail(`Layer #${id(node)}: invalid metadata`);
          const group = blendGroup(node);
          // Legacy Compose fails on any saved assignment, even disabled or FIXED. Short enough for the compact readout.
          if (compose.type === COMPOSE && group !== "")
            fail(`Layer #${id(node)}: group ${JSON.stringify(group)} needs Compose Blend Groups`);
          // A disabled layer's field does not participate. Resolve it only for optional selection identity.
          let field = null;
          if (enabled) {
            // Check the wire exists, without evaluating or inspecting prompt contents.
            upstream(graph, node, "conditioning", false, false);
            field = upstream(graph, node, "mask");
          }
          else { try { field = upstream(graph, node, "mask"); } catch { /* No disabled field required. */ } }
          if (enabled && field.type !== PAINTED) fail(`Layer #${id(node)}: field-processing chains are unsupported`);
          const fieldId = field?.type === PAINTED ? id(field) : null;
          let codes = null, stored = null;
          if (enabled) {
            const widgets = field.widgets?.filter(w => w.type === "CONDITIONING_LAYERS_PAINTED_FIELD") ?? [];
            if (widgets.length !== 1) fail(`Field #${fieldId}: unresolved widget`);
            codes = edits.get(fieldId) ?? null;
            stored = codes ? null : widgets[0].value;
            if (!codes && typeof stored !== "string") fail(`Field #${fieldId}: unresolved value`);
          }
          return {id: id(node), strength, mode, enabled, group, fieldId, codes, stored,
            identity: [token(node), field ? token(field) : null]};
        });
        for (const layer of layers.filter(l => l.fieldId === activeKey)) choices.push({
          key: JSON.stringify([id(compose), layer.id]), label: `${composeLabel(compose)} · Layer #${layer.id}`,
          layers, selected: layer.id, composeToken: token(compose), compose: compose.type,
          groups: compose.type === GROUPED ? groupDiagnostics(layers, layer.id) : null});
      } catch (error) {
        // Keep an explicitly selected layer addressable while its stack is
        // invalid, so its validation error wins and recovery needs no reselection.
        let context;
        try { context = JSON.parse(selected); } catch { /* Unknown selection stays unresolved. */ }
        const retained = Array.isArray(context) && context.length === 2
          && context[0] === id(compose) && typeof context[1] === "string";
        choices.push({key: retained ? selected : JSON.stringify([id(compose), null]),
          label: retained ? `${composeLabel(compose)} · Layer #${context[1]}` : `${composeLabel(compose)} · unavailable`,
          error: error.message});
      }
    }
    const key = selected ?? (choices.length === 1 ? choices[0].key : null);
    const choice = choices.find(c => c.key === key);
    if (!choice || choice.error) return {choices, key, error: choice?.error ?? (choices.length
      ? "Select a Compose/layer context" : "No direct Compose stack contains this field"), fingerprint: JSON.stringify([key, choices.map(c => [c.key, c.label, c.error])])};
    const fingerprint = JSON.stringify([choice.key, choice.composeToken, choice.compose, choice.layers.map(l =>
      [l.id, l.identity, l.strength, l.mode, l.enabled, l.group, l.fieldId, l.codes ? token(l.codes) : l.stored])]);
    return {choices, key, fingerprint, choice};
  }
  async function calculate(snapshot) {
    const nextCache = new Map(), layers = [];
    for (const layer of snapshot.choice.layers) {
      let codes = layer.codes;
      if (layer.enabled && !codes) {
        const text = layer.stored;
        codes = cache.get(text) ?? await decode(text);
        nextCache.set(text, codes);
      }
      layers.push({id: layer.id, strength: layer.strength, mode: layer.mode, enabled: layer.enabled,
        group: layer.group, codes: layer.enabled ? Array.from(codes) : null});
    }
    cache = nextCache;
    return request({compose: snapshot.choice.compose, layers, selected: snapshot.choice.selected});
  }
  return {inspect, calculate};
}

// Latest snapshot wins. One request at a time; visual redraws never enqueue work.
export function createPreviewQueue(calculate, notify, delay = 100) {
  let revision = 0, fingerprint = null, timer = null, running = false, pending = null, disposed = false;
  let state = {status: "pending"};
  async function run() {
    timer = null;
    if (running || !pending || disposed) return;
    const job = pending; pending = null; running = true;
    try {
      const result = await calculate(job.snapshot);
      if (!disposed && revision === job.revision) { state = result; notify(); }
    } catch (error) {
      if (!disposed && revision === job.revision) { state = {status: "unavailable", message: error.message}; notify(); }
    } finally {
      running = false;
      if (!disposed && pending) timer = setTimeout(run, delay);
    }
  }
  return {
    get state() { return state; },
    update(snapshot, defer = false) {
      if (disposed) return;
      if (snapshot.fingerprint === fingerprint && !defer) return;
      fingerprint = snapshot.fingerprint; revision++;
      if (timer !== null) clearTimeout(timer);
      timer = null; pending = null;
      if (snapshot.error) state = {status: "unavailable", message: snapshot.error};
      else {
        state = {status: defer ? "stale" : "pending"};
        if (defer) fingerprint = null;
        else { pending = {snapshot, revision}; timer = setTimeout(run, delay); }
      }
    },
    dispose() { disposed = true; revision++; pending = null; if (timer !== null) clearTimeout(timer); },
  };
}
