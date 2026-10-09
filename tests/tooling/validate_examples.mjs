// Offline brush/codec checks for the Conditioning Layers examples.
// node tests/tooling/validate_examples.mjs
import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {syncBuiltinESMExports} from 'node:module';

const root = resolve(import.meta.dirname, '../..');
const pack = join(root, 'examples/conditioning-layers');
{ // Validation is always offline; no host/browser entry point is shipped.
  const deny = () => { throw Error('Example validation: network/process forbidden'); };
  for (const [name, methods] of [
    ['net', ['connect', 'createConnection', 'createServer']], ['tls', ['connect', 'createServer']],
    ['http', ['request', 'get', 'createServer']], ['https', ['request', 'get', 'createServer']],
    ['http2', ['connect', 'createServer', 'createSecureServer']], ['dgram', ['createSocket']],
    ['dns', ['lookup', 'resolve']],
    ['child_process', ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']],
  ]) {
    const api = (await import(`node:${name}`)).default;
    for (const method of methods) api[method] = deny;
  }
  const net = (await import('node:net')).default;
  net.Socket.prototype.connect = deny; net.Server.prototype.listen = deny;
  globalThis.fetch = deny; globalThis.WebSocket = class { constructor() { deny(); } };
  syncBuiltinESMExports();
}
const core = pathToFileURL(join(root, 'web/js/field_editor') + '/');
const {decodeFieldDataUrl} = await import(new URL('png_codec.js', core));
const {decodeTipDataUrl} = await import(new URL('custom_tip.js', core));
const {resolveBrush, prepareFootprint} = await import(new URL('brush.js', core));
const {Stroke} = await import(new URL('engine.js', core));
const {editorSettings} = await import(new URL('editor_ui.js', core));
const {validateBrushPreset} = await import(new URL('brush_library.js', core));

// Hotdog fields were authored as single clicks at these anchors with the stored settings.
// Re-stamping them from an empty field must reproduce the stored codes exactly.
const HOTDOG_ANCHORS = {
  '05_patterns_and_templates': {'L5 · Neon hotdog sign (field)': [[83, 86]]},
  '07_advanced_brushes': {'L4 · Hotdog constellation (field)': [[44, 40]], 'L5 · Meteor shower (field)': [[84, 86]],
    'L6 · Stencil signboards (field)': [[104, 20], [22, 110]]},
  '09_nine_layer_showcase': {'L8 · Chrome hotdogs (field)': [[62, 26], [108, 44]]},
};
const isHotdog = s => s.shape === 'procedural' && s.procedural_particle_shape === 'hotdog';
const nonzero = codes => codes.reduce((n, v) => n + (v > 0), 0);

const files = (await readdir(pack)).filter(f => f.endsWith('.json')).sort();
assert.equal(files.length, 10);
const workflows = [];
for (const file of files) {
  const stem = file.replace('.json', '');
  const graph = JSON.parse(await readFile(join(pack, file), 'utf8'));
  const fields = graph.nodes.filter(n => n.type === 'ConditioningLayersPaintedField');
  const stored = new Map();
  for (const n of fields) {
    const codes = await decodeFieldDataUrl(n.widgets_values[0]);
    assert.equal(codes.length, 16384); assert(codes.some(v => v > 0));
    const s = n.properties.fieldEditor;
    assert.deepEqual(editorSettings(s), s, 'Settings must survive the retained editor without repair');
    const tip = s.shape === 'custom' ? await decodeTipDataUrl(s.custom_tip) : null;
    prepareFootprint({...s, ...(tip ? {tip} : {})});
    resolveBrush(s);
    assert(!Object.keys(s).some(k => /selection|history|session|overlay|transfer|normalize|balance|share/i.test(k)));
    stored.set(n.title, {codes, s});
    if (isHotdog(s)) {
      const anchors = HOTDOG_ANCHORS[stem]?.[n.title];
      assert(anchors, `${file}: unlisted Hotdog field ${n.title}`);
      let again = new Uint8Array(16384);
      for (const [x, y] of anchors) again = new Stroke(again, 128, 128, {...s, tool: 'paint'}, x, y).result();
      assert(again.every((v, i) => v === codes[i]), `${file}: ${n.title} is not the stored Hotdog brush at its anchors`);
    }
  }
  for (const title of Object.keys(HOTDOG_ANCHORS[stem] ?? {})) assert(isHotdog(stored.get(title).s), `${file}: ${title} must be a Hotdog field`);
  const hot = fields.map(n => n.properties.fieldEditor).filter(isHotdog).map(resolveBrush);
  if (stem.startsWith('07')) {
    const all = fields.map(n => resolveBrush(n.properties.fieldEditor));
    assert(fields.some(n => n.properties.fieldEditor.shape === 'custom'), '07 Custom Tip');
    assert(all.some(s => s.shape === 'procedural' && s.procedural_type === 'noise'), '07 Procedural Noise');
    assert(hot.some(s => s.hotdog_count === 1 && s.procedural_particle_size !== 60 && s.procedural_particle_rotation !== 0), '07 Hotdog Count 1');
    assert(hot.some(s => s.hotdog_count > 1 && s.hotdog_spread > 0 && s.procedural_rotation_jitter > 0 && s.mirror_horizontal), '07 Hotdog scatter');
    assert(hot.some(s => s.hotdog_invert), '07 Invert Template');
  }
  if (stem.startsWith('08')) {
    assert.equal(fields.length, 4);
    assert.equal(new Set(fields.map(n => JSON.stringify(n.properties.fieldEditor))).size, 4, '08 per-field brushes');
  }
  if (stem.startsWith('09')) {
    const editors = fields.map(n => n.properties.fieldEditor);
    assert(editors.some(s => s.shape === 'custom') && editors.some(s => s.pressure_enabled === true), '09 custom tip and pressure');
    assert(hot.some(s => s.hotdog_count > 1 && s.hotdog_spread > 0 && s.procedural_rotation_jitter > 0), '09 Hotdog scatter');
  }
  workflows.push({file, graph, stored});
  console.log(`PASS brush/codec ${file}: ${fields.length} Painted Fields${hot.length ? `, ${hot.length} Hotdog field(s) re-stamped exactly` : ''}`);
}
const start = workflows.find(w => w.file.startsWith('06a')).stored.get('L1 · Rune glow (field)');
const done = workflows.find(w => w.file.startsWith('06b')).stored.get('L1 · Rune glow (field)');
assert(nonzero(start.codes) < nonzero(done.codes) && JSON.stringify(start.s) === JSON.stringify(done.s), '06 start/completed pair');
assert(start.codes.every((v, i) => v === 0 || done.codes[i] > 0), '06B keeps the 06A starter mark');
console.log(`PASS 06 pair: starter ${nonzero(start.codes)} cells, completed ${nonzero(done.codes)} cells, same brush`);
for (const filename of ['hotdog_meteor_shower.brush.json', 'sparkle_glints.brush.json']) {
  const preset = await validateBrushPreset(JSON.parse(await readFile(join(pack, 'presets', filename), 'utf8')));
  const matched = workflows.filter(({file, graph}) => file.startsWith('07') &&
    graph.nodes.some(n => n.properties.fieldEditor && JSON.stringify(editorSettings(preset.brush)) === JSON.stringify(n.properties.fieldEditor)));
  assert.equal(matched.length, 1, 'Reusable preset must match a wired Painted Field in 07');
  console.log(`PASS reusable preset ${filename} v${preset.version}`);
}
