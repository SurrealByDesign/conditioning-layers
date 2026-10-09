import {sameCodes} from "./engine.js";

// Optional, session-local discard observer; instance properties and JSON stay unchanged.
const OBSERVERS = new WeakMap();
export function observeHistory(history, onDiscard) { OBSERVERS.set(history, onDiscard); }

export class FieldHistory {
  constructor() { this.undoEntries = []; this.redoEntries = []; }
  record(label, before, after) {
    if (sameCodes(before, after)) return false;
    this.undoEntries.push({label, before: before.slice(), after: after.slice()});
    const evicted = this.undoEntries.length > 100 ? this.undoEntries.shift() : null;
    const cleared = this.redoEntries;
    this.redoEntries = [];
    OBSERVERS.get(this)?.(cleared, evicted);
    return true;
  }
  undo() {
    const entry = this.undoEntries.pop();
    if (!entry) return null;
    this.redoEntries.push(entry);
    return entry.before.slice();
  }
  redo() {
    const entry = this.redoEntries.pop();
    if (!entry) return null;
    this.undoEntries.push(entry);
    return entry.after.slice();
  }
}
