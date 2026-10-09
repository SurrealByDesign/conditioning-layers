// A single text input supports horizontal drag and exact typed entry.
export function createNumberControl({label, value, min, max, step = 1, integer = true, onChange}) {
  const input = document.createElement("input");
  input.type = "text"; input.inputMode = "decimal"; input.readOnly = true;
  input.setAttribute("aria-label", label);
  input.title = "Drag to adjust; click to type. Shift: fine, Ctrl/Command: coarse. Enter: commit, Esc: revert.";
  let current = value, saved = value, pointer = null, typing = false;
  const normalize = n => {
    n = Math.max(min, Math.min(max, n));
    return integer ? Math.round(n) : Math.round(n * 10) / 10;
  };
  const show = () => { input.value = String(current); };
  const set = n => {
    if (!Number.isFinite(n)) { show(); return; }
    current = normalize(n); show(); onChange(current);
  };
  const finish = commit => {
    if (!typing) return;
    typing = false; input.readOnly = true;
    if (commit && input.value.trim() !== "" && Number.isFinite(Number(input.value))) set(Number(input.value));
    else { current = saved; show(); }
  };
  function keydown(event) {
    event.stopPropagation();
    if (event.key === "Enter") { event.preventDefault(); finish(true); }
    else if (event.key === "Escape") { event.preventDefault(); finish(false); }
    else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      if (typing) finish(true);
      set(current + (event.key === "ArrowUp" ? step : -step));
    }
  }
  input.addEventListener("keydown", keydown);
  input.addEventListener("blur", () => finish(true));
  input.addEventListener("pointerdown", event => {
    event.stopPropagation();
    if (event.button !== 0 || typing) return;
    event.preventDefault(); input.focus();
    pointer = {id: event.pointerId, x: event.clientX, value: current, dragged: false};
    input.setPointerCapture(event.pointerId);
  });
  input.addEventListener("pointermove", event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    const delta = event.clientX - pointer.x;
    if (Math.abs(delta) >= 3) pointer.dragged = true;
    if (!pointer.dragged) return;
    const scale = event.shiftKey ? 0.1 : (event.ctrlKey || event.metaKey) ? 10 : 1;
    set(pointer.value + delta * step * scale);
  });
  input.addEventListener("pointerup", event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    const dragged = pointer.dragged; pointer = null;
    input.releasePointerCapture(event.pointerId);
    if (!dragged) { saved = current; typing = true; input.readOnly = false; input.focus(); input.select(); }
  });
  input.addEventListener("pointercancel", () => {
    if (pointer) { set(pointer.value); pointer = null; }
  });
  show();
  return {element: input, keydown, commit: () => finish(true),
    setValue(n) { current = normalize(n); show(); }, get value() { return current; }};
}
