const PNG_MIME = "image/png";
const MAX_FIELD_BYTES = 8 * 1024 * 1024;

function defaultIdentity() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `row-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export class DraftTransportError extends Error {}

export const NO_OVERLAP = "conditioning-layers.composition-policy.require-no-overlap.v1";
export const BLEND = "conditioning-layers.composition-policy.normalized-blend.v1";

function readPolicy(record) {
  if (!("document_version" in record) && !("composition_policy" in record)) return null;
  const version = record.document_version;
  const policy = record.composition_policy;
  if (!version || Object.keys(version).sort().join() !== "major,minor"
    || version.major !== 2 || version.minor !== 0 || !policy
    || Object.keys(policy).sort().join() !== "policy_identifier,policy_version"
    || ![NO_OVERLAP, BLEND].includes(policy.policy_identifier) || policy.policy_version !== 1) {
    throw new DraftTransportError("The document requires a supported explicit Composition Policy.");
  }
  return Object.freeze({ policy_identifier: policy.policy_identifier, policy_version: 1 });
}

function policyPayload(policy) {
  return policy === null || policy === undefined ? {} : {
    document_version: { major: 2, minor: 0 }, composition_policy: { ...policy },
  };
}

export class SaveAcknowledgementError extends Error {
  constructor(detail) {
    super(`Save could not be safely confirmed: invalid acknowledgement (${detail}). Your current edits are preserved. The server may have saved the document; check the saved copy before retrying.`);
  }
}

// This checks the current panel response, not Python's document/asset validity.
// No live editor state is consulted or changed while checking the entire reply.
function validateSaveAcknowledgement(snapshot, record, { documentKey, documentId, saveAs }) {
  const require = (valid, detail) => {
    if (!valid) throw new SaveAcknowledgementError(detail);
  };
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const identity = (value) => typeof value === "string" && value.length >= 1 && value.length <= 128
    && !/[^A-Za-z0-9._-]/.test(value);
  require(object(record), "missing document record");
  require(typeof record.document_key === "string"
    && /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/.test(record.document_key)
    && !/[^a-z0-9-]/.test(record.document_key), "invalid document key");
  require(identity(record.document_id), "invalid document identity");
  const displayName = record.document_key.split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
  require(record.display_name === displayName, "document name does not match its key");
  if (documentKey && !saveAs) {
    require(record.document_key === documentKey && record.document_id === documentId,
      "Save changed document ownership");
  } else {
    require(record.document_key !== documentKey && record.document_id !== documentId,
      "Save As did not create independent ownership");
    // Python owns Unicode casefold/name normalization. Only compare a target
    // name here when ASCII makes that relationship directly checkable.
    if (!/[^\x00-\x7f]/.test(snapshot.displayName)) {
      const targetKey = snapshot.displayName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "").slice(0, 80).replace(/-+$/, "");
      require(record.document_key === targetKey, "Save As returned a different document name");
    }
  }
  require(record.base_prompt === snapshot.basePrompt, "Base Prompt does not match the submitted Save");
  let policy;
  try { policy = readPolicy(record); } catch (_error) { require(false, "invalid Composition Policy"); }
  require(JSON.stringify(policy) === JSON.stringify(snapshot.compositionPolicy ?? null),
    "Composition Policy does not match the submitted Save");
  require(Array.isArray(record.layers) && record.layers.length === snapshot.layers.length,
    "layer count does not match the submitted Save");
  const identities = new Set();
  const rows = new Set();
  const bindings = snapshot.layers.map((saved, index) => {
    const persisted = record.layers[index];
    require(!rows.has(saved.rowId), "ambiguous submitted row identity");
    rows.add(saved.rowId);
    require(object(persisted), `invalid layer ${index + 1}`);
    require(identity(persisted.layer_id), `missing or invalid layer ${index + 1} identity`);
    require(!identities.has(persisted.layer_id), "duplicate layer identity");
    identities.add(persisted.layer_id);
    require(saved.layerId === null || persisted.layer_id === saved.layerId,
      `layer ${index + 1} changed identity`);
    // The response has no row_id: its ordered content and any existing layer ID
    // must agree with the captured submission before binding to a local row ID.
    require(persisted.name === saved.name && persisted.prompt_text === saved.promptText
      && persisted.strength === saved.strength && persisted.active === saved.active,
      `layer ${index + 1} does not match the submitted Save`);
    require(persisted.field_persisted === true && persisted.field_url
      === `/conditioning-layers/documents/${record.document_key}/fields/${persisted.layer_id}`,
      `layer ${index + 1} has an invalid persisted field binding`);
    return { rowId: saved.rowId, fieldKey: saved.fieldKey,
      layerId: persisted.layer_id, fieldUrl: persisted.field_url };
  });
  return { documentKey: record.document_key, documentId: record.document_id,
    displayName: record.display_name, bindings };
}

const PRESET_ID = /^(?:two|three)-layer\.[a-z0-9-]+\.v1:[ABC]$/;
const validPresetId = (id) => typeof id === "string" && id.length <= 130
  && !/[\r\n]/.test(id) && PRESET_ID.test(id);

export async function loadPresetCatalog(fetchApi) {
  const response = await fetchApi("/conditioning-layers/starter-fields");
  if (!response.ok) throw new DraftTransportError("Preset catalog unavailable. Custom PNG import remains available.");
  const payload = await response.json();
  const seen = new Set();
  if (!Array.isArray(payload?.presets) || payload.presets.length > 192
    || payload.presets.some((preset) => {
      if (!preset || !validPresetId(preset.id) || seen.has(preset.id)
        || typeof preset.display_name !== "string" || !preset.display_name.trim()
        || preset.display_name.length > 180) return true;
      seen.add(preset.id);
      return false;
    })) throw new DraftTransportError("Preset catalog is invalid. Custom PNG import remains available.");
  return payload.presets.map(({ id, display_name }) => Object.freeze({ id, display_name }));
}

export async function loadPresetField(presetId, presets, fetchApi) {
  const preset = presets.find((item) => item.id === presetId);
  if (!validPresetId(presetId) || !preset) throw new DraftTransportError("Unknown Influence Field preset.");
  const response = await fetchApi(`/conditioning-layers/starter-fields/${encodeURIComponent(presetId)}`);
  if (!response.ok) {
    throw new DraftTransportError("Preset unavailable. Try again or import a Custom PNG.");
  }
  const blob = await response.blob();
  if (blob.type !== PNG_MIME || !blob.size || blob.size > MAX_FIELD_BYTES) {
    throw new DraftTransportError("Preset could not be loaded as a supported PNG.");
  }
  return new File([blob], `${preset.display_name}.png`, { type: PNG_MIME });
}

export function createLayerStore(identityFactory = defaultIdentity) {
  const layers = [];
  let labelSequence = 0;
  let fieldSequence = 0;
  const fileKeys = new WeakMap();
  const fieldKeys = new Map();
  let compositionPolicy = null;
  let legacyOrigin = true;

  function selectComposition(identifier) {
    if (![NO_OVERLAP, BLEND].includes(identifier)) throw new DraftTransportError("Unsupported Composition Policy.");
    compositionPolicy = identifier === NO_OVERLAP && legacyOrigin ? null
      : Object.freeze({ policy_identifier: identifier, policy_version: 1 });
  }

  function addLayer() {
    labelSequence += 1;
    const layer = {
      rowId: identityFactory(),
      layerId: null,
      name: `Layer ${labelSequence}`,
      promptText: "",
      strength: 1.0,
      active: true,
      field: null,
      persistedField: false,
      fieldUrl: null,
      presetId: null,
    };
    layers.push(layer);
    return layer;
  }

  function removeLayer(rowId) {
    const index = layers.findIndex((layer) => layer.rowId === rowId);
    if (index === -1) return false;
    layers[index].field = null;
    layers[index].persistedField = false;
    layers[index].presetId = null;
    fieldKeys.delete(rowId);
    layers.splice(index, 1);
    return true;
  }

  function moveLayer(rowId, offset) {
    const index = layers.findIndex((layer) => layer.rowId === rowId);
    const destination = index + offset;
    if (index === -1 || destination < 0 || destination >= layers.length) return false;
    const [layer] = layers.splice(index, 1);
    layers.splice(destination, 0, layer);
    return true;
  }

  function assignField(rowId, file, presetId = null) {
    const layer = layers.find((item) => item.rowId === rowId);
    if (!layer || !file) return false;
    if (presetId !== null && !validPresetId(presetId)) throw new DraftTransportError("Unknown Influence Field preset.");
    layer.field = file;
    layer.presetId = presetId;
    layer.persistedField = false;
    layer.fieldUrl = null;
    if (!fileKeys.has(file)) fileKeys.set(file, `upload-${++fieldSequence}`);
    fieldKeys.set(rowId, fileKeys.get(file));
    return true;
  }

  function layerPayload(layer) {
    return {
      row_id: layer.rowId,
      layer_id: layer.layerId,
      name: layer.name,
      prompt_text: layer.promptText,
      strength: layer.strength,
      active: layer.active,
      field_part: layer.persistedField ? null : `field-${layer.rowId}`,
      retained_field: layer.persistedField,
    };
  }

  function toRequest(basePrompt, idempotencyKey, documentState = {}, seed) {
    const request = {
      ...policyPayload(compositionPolicy),
      base_prompt: basePrompt,
      idempotency_key: idempotencyKey,
      document_id: documentState.documentId ?? null,
      document_key: documentState.documentKey ?? null,
      layers: layers.map(layerPayload),
    };
    if (seed !== undefined) request.seed = seed;
    return request;
  }

  function validateFields(rows = layers) {
    for (const layer of rows) {
      if (layer.presetId !== null && layer.presetId !== undefined
        && (!validPresetId(layer.presetId) || layer.persistedField || !layer.field)) {
        throw new DraftTransportError(`${layer.name} has a conflicting Influence Field selection.`);
      }
      if (layer.persistedField) continue;
      if (!layer.field) {
        throw new DraftTransportError(`${layer.name} requires a PNG Influence Field.`);
      }
      if (layer.field.type !== PNG_MIME) {
        throw new DraftTransportError(`${layer.name} Influence Field must be a PNG.`);
      }
      if (layer.field.size > MAX_FIELD_BYTES) {
        throw new DraftTransportError(`${layer.name} Influence Field exceeds 8 MiB.`);
      }
    }
  }

  function appendUploads(form, rows = layers) {
    for (const layer of rows) {
      if (layer.field) form.append(`field-${layer.rowId}`, layer.field, "field.png");
    }
  }

  function toMultipart(basePrompt, idempotencyKey, documentState = {}, seed) {
    const form = new FormData();
    const request = toRequest(basePrompt, idempotencyKey, documentState, seed);
    validateFields();
    form.append(
      "request",
      new Blob([JSON.stringify(request)], { type: "application/json" }),
      "request.json",
    );
    appendUploads(form);
    return form;
  }

  function toDocumentMultipart(basePrompt, displayName, documentState = {}, snapshot = capture(basePrompt, displayName)) {
    const form = new FormData();
    validateFields(snapshot.layers);
    const request = {
      ...policyPayload(snapshot.compositionPolicy),
      display_name: snapshot.displayName,
      source_document_key: documentState.documentKey ?? null,
      document_id: documentState.documentId ?? null,
      base_prompt: snapshot.basePrompt,
      layers: snapshot.layers.map(layerPayload),
    };
    form.append(
      "request",
      new Blob([JSON.stringify(request)], { type: "application/json" }),
      "request.json",
    );
    appendUploads(form, snapshot.layers);
    return form;
  }

  function replaceFromDocument(documentRecord) {
    const policy = readPolicy(documentRecord);
    compositionPolicy = policy;
    legacyOrigin = policy === null;
    layers.splice(0, layers.length);
    fieldKeys.clear();
    labelSequence = 0;
    for (const record of documentRecord.layers ?? []) {
      labelSequence += 1;
      layers.push({
        rowId: identityFactory(),
        layerId: record.layer_id,
        name: record.name,
        promptText: record.prompt_text,
        strength: record.strength,
        active: record.active,
        field: null,
        persistedField: record.field_persisted === true,
        fieldUrl: typeof record.field_url === "string" ? record.field_url : null,
        presetId: null,
      });
      fieldKeys.set(layers.at(-1).rowId, `opened-${++fieldSequence}`);
    }
  }

  // Files are immutable. Local tokens compare field assignments without hashing
  // bytes asynchronously or confusing persistence/preview URLs with content.
  function capture(basePrompt, displayName) {
    return {
      basePrompt,
      displayName,
      compositionPolicy,
      layers: layers.map((layer) => ({ ...layer, fieldKey: fieldKeys.get(layer.rowId) ?? null })),
    };
  }

  function fingerprint(snapshot) {
    const values = [
      snapshot.basePrompt, snapshot.displayName,
      snapshot.layers.map((layer) => [
        layer.rowId, layer.name, layer.promptText,
        Number.isFinite(layer.strength) ? layer.strength : String(layer.strength),
        layer.active, layer.fieldKey,
      ]),
    ];
    if (snapshot.compositionPolicy) values.push(policyPayload(snapshot.compositionPolicy));
    return JSON.stringify(values);
  }

  function acceptSaved(snapshot, record, ownership) {
    const acknowledged = validateSaveAcknowledgement(snapshot, record, ownership);
    if (snapshot.compositionPolicy) {
      legacyOrigin = false;
      // A policy-bearing Save has become the source. Preserve a concurrent
      // deliberate No Overlap edit explicitly instead of stripping that source.
      if (compositionPolicy === null) selectComposition(NO_OVERLAP);
    }
    acknowledged.bindings.forEach((saved) => {
      const layer = layers.find((item) => item.rowId === saved.rowId);
      if (!layer) return;
      layer.layerId = saved.layerId;
      if (fieldKeys.get(layer.rowId) === saved.fieldKey) {
        layer.field = null;
        layer.persistedField = true;
        layer.fieldUrl = saved.fieldUrl;
        layer.presetId = null;
      }
    });
    return acknowledged;
  }

  function clear() {
    compositionPolicy = null;
    legacyOrigin = true;
    for (const layer of layers) layer.field = null;
    layers.splice(0, layers.length);
    fieldKeys.clear();
    labelSequence = 0;
  }

  return {
    layers,
    get compositionPolicy() { return compositionPolicy; },
    selectComposition,
    addLayer,
    removeLayer,
    moveLayer,
    assignField,
    toRequest,
    toMultipart,
    toDocumentMultipart,
    replaceFromDocument,
    capture,
    fingerprint,
    acceptSaved,
    clear,
  };
}
