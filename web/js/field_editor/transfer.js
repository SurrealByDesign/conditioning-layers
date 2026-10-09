// Pairwise field-code arithmetic and linked local history. No brush coverage lives here.
export const TRANSFER_LABEL = "Transfer";

function equal(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

export function transferReach(source, destination) {
  const reach = new Uint8Array(destination.length);
  for (let i = 0; i < reach.length; i++) reach[i] = Math.min(255, source[i] + destination[i]);
  return reach;
}

export function transferEngineBrush(settings) { return {...settings, tool: "restore", apply_mode: "normal"}; }

export function transferSource(sourceBefore, destinationBefore, destinationAfter) {
  if (sourceBefore.length !== destinationBefore.length || destinationAfter.length !== destinationBefore.length)
    throw new Error("Transfer out of range.");
  const source = new Uint8Array(sourceBefore.length);
  for (let i = 0; i < source.length; i++) {
    const moved = destinationAfter[i] - destinationBefore[i];
    if (!Number.isInteger(moved) || moved < 0 || moved > Math.min(sourceBefore[i], 255 - destinationBefore[i]))
      throw new Error("Transfer out of range.");
    source[i] = sourceBefore[i] - moved;
  }
  return source;
}

export function nothingMovable(coverage, selection, sourceBefore, destinationBefore) {
  let covered = false;
  for (let i = 0; i < coverage.length; i++) if (coverage[i] > 0 && (selection === null || selection[i])) {
    covered = true;
    if (Math.min(sourceBefore[i], 255 - destinationBefore[i]) > 0) return false;
  }
  return covered;
}

// Pairwise Balance: the active field's share of each cell's pair total, conserved exactly.
export const BALANCE_LABEL = "Balance";
export const BALANCE_DEFAULT_SHARE = 50;

// Per cell, the integer in [max(0, T − 255), min(255, T)] nearest T·share/100, T = active + partner.
// An exact half goes toward the active value, so either field's view names the same split.
export function balanceTarget(active, partner, share) {
  if (!Number.isInteger(share) || share < 0 || share > 100 || active.length !== partner.length)
    throw new Error("Balance out of range.");
  const target = new Uint8Array(active.length);
  for (let i = 0; i < target.length; i++) {
    const total = active[i] + partner[i], n = total * share, r = n % 100, q = (n - r) / 100;
    const nearest = r > 50 || (r === 50 && active[i] > q) ? q + 1 : q;
    target[i] = Math.min(Math.min(255, total), Math.max(Math.max(0, total - 255), nearest));
  }
  return target;
}

// The exact complement. Any cell that moved away from or past its target, or left 0–255, throws.
export function balancePartner(partnerBefore, activeBefore, activeAfter, target) {
  if (partnerBefore.length !== activeBefore.length || activeAfter.length !== activeBefore.length
      || target.length !== activeBefore.length) throw new Error("Balance out of range.");
  const partner = new Uint8Array(partnerBefore.length);
  for (let i = 0; i < partner.length; i++) {
    const moved = activeAfter[i] - activeBefore[i], room = target[i] - activeBefore[i], next = partnerBefore[i] - moved;
    if (!Number.isInteger(moved) || (room < 0 ? moved > 0 || moved < room : moved < 0 || moved > room)
        || activeAfter[i] < 0 || activeAfter[i] > 255 || next < 0 || next > 255)
      throw new Error("Balance out of range.");
    partner[i] = next;
  }
  return partner;
}

export function balanceSettled(coverage, selection, target, activeBefore) {
  let covered = false;
  for (let i = 0; i < coverage.length; i++) if (coverage[i] > 0 && (selection === null || selection[i])) {
    covered = true;
    if (target[i] !== activeBefore[i]) return false;
  }
  return covered;
}

const stack = (record, kind) => record.session.history[`${kind}Entries`];
const broken = reason => ({state: "broken", reason});
// Each row holds its kind and its two sides by role name, in role order.
const ROLES = {transfer: ["destination", "source"], balance: ["active", "partner"]};
const sides = row => ROLES[row.kind].map(role => row[role]);

export class TransferLinks {
  constructor(members) {
    this.members = members;
    this.transactions = new Map();
    this.nextTransaction = 1;
  }

  // FieldHistory calls this after changing both stacks. Removing a prefix preserves
  // linear history; following every removed link computes the full paired closure.
  discarded = (cleared, evicted) => {
    const pending = cleared.map(entry => ({entry, kind: "redo"}));
    if (evicted) pending.push({entry: evicted, kind: "undo"});
    while (pending.length) {
      const {entry, kind} = pending.pop(), transaction = entry.link?.transaction;
      if (!entry.link) continue;
      const pair = this.transactions.get(transaction);
      if (!pair) throw new Error("Unknown Transfer transaction.");
      const [first, second] = sides(pair);
      const own = first.entry === entry ? first : second.entry === entry ? second : null;
      if (!own) throw new Error("Transfer transaction mismatch.");
      const partner = own === first ? second : first;
      this.transactions.delete(transaction);
      const entries = stack(partner.record, kind), index = entries.indexOf(partner.entry);
      // The partner may already be in this operation's removed set (Redo clearing).
      if (index < 0) {
        if (!pending.some(item => item.entry === partner.entry && item.kind === kind))
          throw new Error("Missing Transfer partner entry.");
        pending.splice(pending.findIndex(item => item.entry === partner.entry && item.kind === kind), 1);
        continue;
      }
      for (const removed of entries.splice(0, index + 1))
        if (removed !== partner.entry) pending.push({entry: removed, kind});
    }
  };

  checkpoint() {
    return {fields: this.members().map(record => ({record, codes: record.session.codes,
      undo: stack(record, "undo").slice(), redo: stack(record, "redo").slice()})),
    transactions: new Map(this.transactions)};
  }

  restore(checkpoint) {
    for (const {record, codes, undo, redo} of checkpoint.fields) {
      record.session.codes = codes;
      record.session.history.undoEntries = undo; record.session.history.redoEntries = redo;
    }
    this.transactions = checkpoint.transactions;
  }

  record(destination, source, destinationBefore, destinationAfter, sourceBefore, sourceAfter) {
    if (destination === source || !this.members().includes(destination) || !this.members().includes(source)
        || !equal(sourceAfter, transferSource(sourceBefore, destinationBefore, destinationAfter)))
      throw new Error("Transfer out of range.");
    const moved = !equal(destinationBefore, destinationAfter);
    if (moved !== !equal(sourceBefore, sourceAfter)) throw new Error("Transfer out of range.");
    if (!moved) return false;
    const checkpoint = this.checkpoint(), transaction = this.nextTransaction++;
    try {
      if (!destination.session.history.record(TRANSFER_LABEL, destinationBefore, destinationAfter)
          || !source.session.history.record(TRANSFER_LABEL, sourceBefore, sourceAfter))
        throw new Error("Transfer recording failed.");
      const de = stack(destination, "undo").at(-1), se = stack(source, "undo").at(-1);
      de.link = Object.freeze({transaction, kind: "transfer", role: "destination", partner: source.key});
      se.link = Object.freeze({transaction, kind: "transfer", role: "source", partner: destination.key});
      this.transactions.set(transaction, {kind: "transfer", destination: {record: destination, entry: de}, source: {record: source, entry: se}});
      destination.session.codes = destinationAfter; source.session.codes = sourceAfter;
      return true;
    } catch (error) { this.restore(checkpoint); throw error; }
  }

  // One Balance in both histories, active first, with the next id; false for a no-op. A prepare
  // refusal takes no id. A later exception restores the checkpoint and is rethrown.
  recordBalance(active, partner, activeBefore, activeAfter, partnerBefore, partnerAfter, target) {
    if (active === partner || !this.members().includes(active) || !this.members().includes(partner)
        || !equal(partnerAfter, balancePartner(partnerBefore, activeBefore, activeAfter, target)))
      throw new Error("Balance out of range.");
    const moved = !equal(activeBefore, activeAfter);
    if (moved !== !equal(partnerBefore, partnerAfter)) throw new Error("Balance out of range.");
    if (!moved) return false;
    const checkpoint = this.checkpoint(), transaction = this.nextTransaction++;
    try {
      if (!active.session.history.record(BALANCE_LABEL, activeBefore, activeAfter)
          || !partner.session.history.record(BALANCE_LABEL, partnerBefore, partnerAfter))
        throw new Error("Balance recording failed.");
      const ae = stack(active, "undo").at(-1), pe = stack(partner, "undo").at(-1);
      ae.link = Object.freeze({transaction, kind: "balance", role: "active", partner: partner.key});
      pe.link = Object.freeze({transaction, kind: "balance", role: "partner", partner: active.key});
      this.transactions.set(transaction, {kind: "balance", active: {record: active, entry: ae}, partner: {record: partner, entry: pe}});
      active.session.codes = activeAfter; partner.session.codes = partnerAfter;
      return true;
    } catch (error) { this.restore(checkpoint); throw error; }
  }

  // Wording only: the kind of the row holding the top entry, else its link's kind, else Transfer.
  kindOf(kind, record) {
    const entry = stack(record, kind).at(-1);
    if (!entry) return null;
    for (const row of this.transactions.values()) if (sides(row).some(side => side.entry === entry)) return row.kind;
    return entry.link?.kind === "balance" ? "balance" : "transfer";
  }

  classify(kind, record) {
    const entry = stack(record, kind).at(-1);
    if (!entry) return {state: "empty"};
    // Identity also detects a removed or forged link on a still-live table entry.
    const identity = [...this.transactions.entries()].find(([, pair]) =>
      sides(pair).some(side => side.entry === entry));
    if (!Object.hasOwn(entry, "link")) return identity ? broken("transaction mismatch") : {state: "single"};
    const link = entry.link, pair = this.transactions.get(link?.transaction);
    if (!pair) return broken(identity ? "transaction mismatch" : "unknown transaction");
    const [first, second] = sides(pair), roles = ROLES[pair.kind];
    const own = first.record === record ? first : second.record === record ? second : null;
    if (!own || own.entry !== entry) return broken("transaction mismatch");
    const partner = own === first ? second : first;
    if (partner.record === record || !this.members().includes(record) || !this.members().includes(partner.record))
      return broken("missing partner");
    for (const [side, other, role] of [[first, second, roles[0]], [second, first, roles[1]]]) {
      const metadata = side.entry.link;
      if (!metadata || !Number.isSafeInteger(metadata.transaction) || metadata.transaction <= 0
          || metadata.transaction !== link.transaction || metadata.kind !== pair.kind
          || metadata.role !== role || metadata.partner !== other.record.key)
        return broken("transaction mismatch");
    }
    const entries = stack(partner.record, kind), index = entries.indexOf(partner.entry);
    if (index < 0) return broken("missing partner entry");
    const current = kind === "undo" ? "after" : "before";
    if (!equal(record.session.codes, entry[current]) || !equal(partner.record.session.codes, entries.at(-1)[current]))
      return broken("buffer mismatch");
    return {state: index === entries.length - 1 ? "linked" : "blocked", partner: partner.record};
  }

  step(kind, record) {
    const classification = this.classify(kind, record);
    if (classification.state === "single") { record.session[kind](); return classification; }
    if (classification.state !== "linked") return classification;
    let checkpoint;
    try {
      const pair = sides(this.transactions.get(stack(record, kind).at(-1).link.transaction));
      const target = kind === "undo" ? "before" : "after", other = kind === "undo" ? "redo" : "undo";
      const codes = pair.map(side => side.entry[target].slice());
      checkpoint = this.checkpoint();
      for (const side of pair) stack(side.record, other).push(stack(side.record, kind).pop());
      pair.forEach((side, i) => { side.record.session.codes = codes[i]; });
      return classification;
    } catch { if (checkpoint) this.restore(checkpoint); return {state: "failed"}; }
  }

  forget(record) {
    for (const [transaction, pair] of this.transactions) if (sides(pair).some(side => side.record === record)) {
      for (const side of sides(pair)) delete side.entry.link;
      this.transactions.delete(transaction);
    }
  }
}
