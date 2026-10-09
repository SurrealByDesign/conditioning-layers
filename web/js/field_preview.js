const MAX_LABEL_LENGTH = 80;

function defaultCreateUrl(file) {
  return URL.createObjectURL(file);
}

function defaultRevokeUrl(url) {
  URL.revokeObjectURL(url);
}

function boundedLabel(value) {
  if (typeof value !== "string" || !value.trim()) return "Influence Field";
  return value.trim().slice(0, MAX_LABEL_LENGTH);
}

/**
 * Browser-temporary preview state keyed by layer rowId.
 *
 * Preview records are informational only: they never enter request payloads
 * or persisted documents, and a displayable preview never implies that the
 * field is executable. Python validation remains authoritative.
 *
 * States: "none" | "loading" | "valid" | "invalid".
 * Sources: "upload" (revocable object URL) | "persisted" (server route URL).
 */
export function createPreviewRegistry(createUrl = defaultCreateUrl, revokeUrl = defaultRevokeUrl) {
  const records = new Map();

  function releaseUrl(record) {
    if (record && record.source === "upload" && record.url) revokeUrl(record.url);
  }

  function setUpload(rowId, file) {
    releaseUrl(records.get(rowId));
    const record = {
      state: "loading",
      source: "upload",
      url: createUrl(file),
      label: boundedLabel(file?.name),
      width: null,
      height: null,
      message: null,
    };
    records.set(rowId, record);
    return record;
  }

  function setPersisted(rowId, url, label = "Saved Influence Field") {
    releaseUrl(records.get(rowId));
    const record = {
      state: "loading",
      source: "persisted",
      url,
      label: boundedLabel(label),
      width: null,
      height: null,
      message: null,
    };
    records.set(rowId, record);
    return record;
  }

  function markLoaded(rowId, url, width, height) {
    const record = records.get(rowId);
    if (!record || record.url !== url || record.state !== "loading") return null;
    record.state = "valid";
    record.width = Number.isFinite(width) ? width : null;
    record.height = Number.isFinite(height) ? height : null;
    return record;
  }

  function markFailed(rowId, url, message) {
    const record = records.get(rowId);
    if (!record || record.url !== url || record.state !== "loading") return null;
    record.state = "invalid";
    record.message = boundedLabel(message ?? "Preview could not be displayed.");
    return record;
  }

  function clearField(rowId) {
    releaseUrl(records.get(rowId));
    records.set(rowId, {
      state: "none",
      source: null,
      url: null,
      label: null,
      width: null,
      height: null,
      message: null,
    });
  }

  function release(rowId) {
    releaseUrl(records.get(rowId));
    records.delete(rowId);
  }

  function releaseAll() {
    for (const record of records.values()) releaseUrl(record);
    records.clear();
  }

  function get(rowId) {
    return records.get(rowId) ?? null;
  }

  return { setUpload, setPersisted, markLoaded, markFailed, clearField, release, releaseAll, get };
}
