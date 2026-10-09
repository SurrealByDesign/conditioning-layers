// Host-free, session-only chooser. Candidate codes are already decoded by the adapter.
export function openFieldChooser({items, choose, onClose}) {
  let closed = false;
  const el = (tag, text, parent) => {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    parent?.append(item); return item;
  };
  const dialog = el("dialog"); dialog.className = "cl-field-chooser";
  dialog.setAttribute("aria-label", "Add Field");
  const style = el("style", null, dialog);
  style.textContent = `
    .cl-field-chooser {background:#24262b;color:#eee;border:1px solid #777;border-radius:8px;padding:16px;max-height:80vh;overflow:auto;}
    .cl-field-chooser::backdrop {background:#0009;}
    .cl-field-chooser .field-candidate {display:flex;align-items:center;gap:12px;margin:8px 0;padding:6px;}
    .cl-field-chooser canvas {width:48px;height:48px;image-rendering:pixelated;}
  `;
  el("h2", "Add Field", dialog);
  el("p", "Painted Field nodes in this graph. The chosen field joins as a visible reference; nothing changes until Done.", dialog);
  for (const item of items) {
    const row = el("button", null, dialog); row.type = "button"; row.className = "field-candidate";
    row.disabled = !item.codes;
    if (item.codes) {
      const canvas = el("canvas", null, row); canvas.width = canvas.height = 128;
      const context = canvas.getContext("2d"), pixels = context.createImageData(128, 128);
      for (let i = 0; i < 16384; i++) {
        pixels.data[i * 4] = pixels.data[i * 4 + 1] = pixels.data[i * 4 + 2] = item.codes[i];
        pixels.data[i * 4 + 3] = 255;
      }
      context.putImageData(pixels, 0, 0);
    }
    el("span", item.codes ? item.label : `${item.label} — cannot be read: ${item.error}`, row);
    row.addEventListener("click", () => {
      if (closed || row.disabled) return;
      dispose(); choose(item);
    });
  }
  if (!items.length) el("p", "No other Painted Field node in this graph.", dialog);
  const close = el("button", "Close", dialog); close.type = "button";
  close.addEventListener("click", dispose);
  function dispose() {
    if (closed) return;
    closed = true; dialog.close(); dialog.remove(); dialog.replaceChildren(); onClose?.();
  }
  function keyboard(event) {
    event.stopImmediatePropagation();
    if (event.type === "keydown" && event.key === "Escape") { event.preventDefault(); dispose(); }
  }
  dialog.addEventListener("cancel", event => { event.preventDefault(); dispose(); });
  for (const name of ["pointerdown", "pointermove", "pointerup", "click", "contextmenu", "dragover", "drop"])
    dialog.addEventListener(name, event => { event.stopPropagation(); if (["dragover", "drop"].includes(name)) event.preventDefault(); });
  document.body.append(dialog); dialog.showModal();
  return {dispose, keyboard};
}
