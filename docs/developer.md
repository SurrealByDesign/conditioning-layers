# Contributor and maintenance guide

Start with the [public guide](../README.md) and [architecture](architecture.md).
Keep changes bounded to Krea 2, prompt-based Conditioning Layers and the native field
format. Propose an ADR before changing durable semantics. Add no placeholders
for future layer types or backends. Never regenerate identity fixtures to make
a behavior change pass.

## Source layout

- `__init__.py`: ComfyUI loader, independent registration boundaries.
- `src/conditioning_layers/domain`, `assets`, `persistence`, `capabilities`:
  intent, strict field codecs, saved documents and declared behavior.
- `src/conditioning_layers/adapters`: translation and deterministic contracts.
- `src/conditioning_layers/comfyui`: field nodes, layer composition and host boundaries.
- `src/conditioning_layers/integrations`: sidebar routes and readiness.
- `web/js/field_editor`: host-independent editor, arithmetic, codecs and history.
- `web/js/painted_field_node.js`: public ComfyUI frontend adapter.
- `tests/unit`: public maintenance tests; `tests/tooling`: offline runners
  and example validators.
- Library, Pattern Field and twelve legacy `node-workflows/phase1/fields`
  fixture paths remain unchanged because readers and identities depend on them.

## Environments

The tested Windows environments are developer **CPython 3.10.11** and
host-dependency **CPython 3.12.11**. Keep them separate; other Python versions
have not been tested by this suite. Node.js is required for inline
frontend tests and the JavaScript example validator, not for user installation.
The validator uses modern Node APIs including `import.meta.dirname`.

The four `tests/requirements-*.txt` and `tests/constraints-*.txt` files preserve
observed dependency pins. They are Windows baseline declarations, not a universal
lockfile or runtime installer. Provision an isolated test environment deliberately;
do not upgrade a working ComfyUI environment to satisfy contributor tests.
The host lane needs real Torch, aiohttp, multidict, Pillow, NumPy and PyAV as
declared. The legacy optional Blend component checks Torch **2.8.0+cu129**,
NumPy **2.4.6** and PyAV **17.0.1**. Those checks are not a universal installation
recipe or a dependency requirement for the backend-neutral core.

## Commands

Run from the public package root. `python` below means the interpreter of the
stated lane. `-B` prevents bytecode writes and `-W error` makes warnings visible
as failures. The runners insert the package's source path themselves.

Developer lane (run each group in a separate process):

```text
python -X utf8 -B -W error tests/tooling/public_offline.py domain
python -X utf8 -B -W error tests/tooling/public_offline.py persistence
python -X utf8 -B -W error tests/tooling/public_offline.py assets
python -X utf8 -B -W error tests/tooling/public_offline.py capabilities
python -X utf8 -B -W error tests/tooling/public_offline.py translation
python -X utf8 -B -W error tests/tooling/public_offline.py graph
python -X utf8 -B -W error tests/tooling/public_offline.py library
python -X utf8 -B -W error tests/tooling/public_offline.py field-editor
python -X utf8 -B -W error tests/tooling/public_offline.py hotdog-template
node tests/tooling/validate_examples.mjs
```

Host-dependency lane (no running ComfyUI host or model needed):

```text
python -X utf8 -B -W error tests/tooling/public_offline.py nodes
python -X utf8 -B -W error tests/tooling/public_offline.py node-runtime
python -X utf8 -B -W error tests/tooling/public_offline.py blend
python -X utf8 -B -W error tests/tooling/public_offline.py runtime
python -X utf8 -B -W error tests/tooling/public_offline.py panel
python -X utf8 -B -W error tests/tooling/public_offline.py execution
python -X utf8 -B -W error tests/tooling/validate_examples.py
```

`field-editor` includes pressure, custom tips, procedural brushes, library,
multi-field sessions, Transfer and Balance. Its exhaustive arithmetic and
randomized linked-history checks are intentionally slower. Hotdog separately
checks canonical PNG identity and every decoded pixel against the embedded
runtime resource. `nodes` uses real tensor operations and must use the host lane.

Fences prohibit network, host/browser launch and generation. Only the runners' limited inline
Node/Python probes are allowed. Execution tests use an in-memory HTTP fixture;
they do not prove real socket behavior. Do not replace these commands with broad
unfenced discovery. These checks do not establish support on every platform.

One optional historical decoder test accepts `CONDITIONING_LAYERS_DECODER_HOST`
pointing to the exact anchored ComfyUI 0.37.2 sources; it checks source hashes
and never launches that host. Without it, that one test reports a skip. This is
not an installation prerequisite. Symlink tests may skip when Windows does not
permit creating a symlink.

Leave `CONDITIONING_LAYERS_P3D_QUALIFICATION_BRIDGE` unset: this inactive legacy
hook is not supported by the distribution. Historical repository-relative
evidence strings in source records are not runtime file dependencies.

## Validation

On 2026-10-09 the Windows public maintenance suite ran **1,841 tests: 1,836 passed, 5 skipped,
0 failures/errors**. The skips are four Windows symlink-creation checks and one
optional historical host-source decoder check. The tested interpreters are
**CPython 3.10.11** (core/editor) and **3.12.11** (host dependencies), with
**Node.js 25.6.1** for frontend checks. Linux and macOS testing is not established.

Both example validators pass **all 10 workflows**; the JavaScript validator
also passes **both brush presets**. These checks cover graph structure, fields, full coverage, contributing layers,
settings, exact Hotdog restamping and composition; they do not
judge generated image quality. No GPU generation tests are part of this public
offline suite. No host or browser is launched by these commands.

Compatibility tiers are **ComfyUI 0.34.6 / frontend 1.49.6: qualified baseline**,
and **ComfyUI 0.39.2 / frontend 1.53.10: functional smoke tested** for the node
workflow/editor. The newer pair has narrower coverage. A previous isolated
server-load check registered 23 nodes, including the optional helper, but that
is not a browser or GPU-generation test. See [compatibility](../README.md#compatibility).

## Sidebar compatibility

The legacy sidebar supports a separate `.conditioning.json` document workflow,
including Open, Save, Save As, Base Prompt, identities, owned PNG fields and
document-level composition policy. ComfyUI workflow JSON does not replace or
automatically convert this format. Documents live in ComfyUI user data under
`conditioning-layers/documents`; the Brush Library separately uses
`conditioning-layers/brush-library-v1.json`.

Generation supports **1–3 Active Conditioning Layers with No Overlap**, or
**exactly 3 with Blend**. An Active Conditioning Layer at Strength zero still
counts toward these limits. No Overlap rejects any positive-field overlap.
Blend is a document-wide policy, separate from the nodes' per-layer BLENDED mode.

No Overlap generation uses the legacy **format 1.0** document path. **Format 2.0
with explicit No Overlap can be opened and saved but cannot Generate**; choosing
No Overlap after saving a Blend document does not silently downgrade its format.

The sidebar's supported generation profile is **ComfyUI 0.34.6**, revision
`8fed37813848259fbdd2548ae3cd9f14df7fd68b`, **frontend 1.49.6**, using its
specific Krea 2 Turbo BF16 model inventory. It checks model identities and the
applicable execution dependencies, not only version labels. Node/editor smoke
testing on 0.39.2 does not establish sidebar generation support there. Check
the sidebar's reported compatibility findings before generating.

## Troubleshooting node availability

The normal package exposes 22 nodes; **Normalized Blend Preparation** is an
optional 23rd. It requires exact Torch **2.8.0+cu129**, NumPy **2.4.6**, PyAV
**17.0.1**, no `--fp16-intermediates`, and matching component source hashes.
Execution also requires float32 intermediates. Its absence alone is expected
outside that profile and does not disable Layer → Add → Compose.

If a normal node group is missing, confirm the entire package is installed and
inspect loader import failures. The loader records group-specific
`*_REGISTRATION_ERROR` values for diagnosis; it currently does not print every
caught group failure. For Painted Field, verify **Edit Field…** appears and opens
before re-saving a workflow, then refresh the browser if necessary.
