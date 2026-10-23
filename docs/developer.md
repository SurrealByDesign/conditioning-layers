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
- `src/conditioning_layers/integrations`: sidebar routes, readiness and the optional CPU composition preview.
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

`field-editor` includes brush dynamics (smoothing, pressure Minimum Size, jitter, Scatter and Follow Stroke Direction), compact-toolbar/Advanced-panel behavior, pressure, custom tips, procedural brushes, library,
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

On 2026-10-09 the Windows public maintenance suite ran **1,846 tests: 1,841 passed, 5 skipped,
0 failures/errors**. This includes five loader-registration regression tests added after the initial release. The skips are four Windows symlink-creation checks and one
optional historical host-source decoder check. The tested interpreters are
**CPython 3.10.11** (core/editor) and **3.12.11** (host dependencies), with
**Node.js 25.6.1** for frontend checks. Linux and macOS testing is not established.

Both example validators pass **all 10 workflows**; the JavaScript validator
also passes **both brush presets**. These checks cover graph structure, fields, full coverage, contributing layers,
settings, exact Hotdog restamping and composition; they do not
judge generated image quality. No GPU generation tests are part of this public
offline suite. No host or browser is launched by these commands.

The qualified baseline is **ComfyUI 0.34.6 / frontend 1.49.6**. Retained newer evidence is bounded: **0.37.2 / 1.52.7** exact-three-layer Blend live qualification; **0.37.4 / 1.52.7** selected technical/live successes, including native N=9 owner visual acceptance; **0.39.2 / 1.53.10** earlier native-node/editor functional smoke testing. **0.42.0 / 1.55.18** has development UI launch and visual inspection only. None promotes the stricter sidebar generation profile or qualifies every subsequent editor change. See [compatibility](../README.md#compatibility).

## Retained alpha.3 evidence

The published alpha.3 candidate transferred six editor modules from accepted commit `072761b1ce783adf428e697ff26438bb59c5d1fb`: `angle_jitter.js`, `stroke_smoothing.js`, `brush.js`, `brush_library.js`, `editor_ui.js` and `engine.js`. The public loader and its sidebar-failure isolation, loader regression tests, Hotdog asset-test adaptation, dependencies, schemas and shipped assets remain intact. Runtime transfer verification compares exact Git-blob bytes. This is an experimental public alpha, not production certification.

Retained qualification includes native **Save → browser restart → Open**, exact restoration of all **16,384 field codes**, and byte-identical final CPU operation-chain output. The owner supplied this completed result for release preparation; it is carried forward without repeating the journey or assigning it to an unqualified host.

Historical alpha.3 validation on **2026-10-22**:

- Public `field-editor` group: **526/526 PASS**, zero failures/errors/skips, using CPython **3.10.11** and Node.js **25.6.1**, with the existing execution fences. The first run exposed one stale Balance field-strip ordering expectation; it now checks the accepted four-item order, including `profile-note`. The complete group then passed. No production file or behavioral assertion was weakened.
- Preserved public `hotdog-template` group: **15/15 PASS**. Existing loader-registration tests: **8/8 PASS**, including sidebar import and cross-drive failure isolation, under the offline fences.
- All six production files match the accepted Git blobs exactly. The installed host served **25 JavaScript modules** matching the copied files; all **49 relative import references** resolved. Dependencies, schemas, assets, examples, loader protections and public Hotdog adaptations remain unchanged.
- Clean installation: an ordinary physical copy of the complete public package, isolated user/data directories, and the qualified **ComfyUI 0.34.6** revision `8fed37813848259fbdd2548ae3cd9f14df7fd68b` / **frontend 1.49.6**, using CPython **3.12.11**. Launched through ComfyUI's normal `main.py` entry point on loopback port **8188** with `--cpu`, without the private product launcher or junctions.
- All **22 normal nodes** registered; the optional helper also registered. Real-browser native mouse painting, editor Undo/Redo, Done/reopen, Brush Library save/apply, Pattern choices and Example 01 node resolution passed. All **16 Pattern and four Preset assets** additionally loaded as float32 CPU masks from the installed copy. No browser page exceptions occurred.
- **Zero execution requests**, empty host history/queue and no GPU generation. The owned browser/host stopped and port 8188 was released. This installation smoke did not repeat native Save/restart/Open qualification or expand newer-host support.

## Alpha.4 validation

Alpha.4 promotes Contribution preview and Selective Blend Groups into the independent public distribution. The root loader retains public sidebar-failure isolation and logging. No runtime dependencies, numerical authority, sidebar admission or historical identity fixtures change. The existing compact toolbar and numbered examples remain intact.

`.gitattributes` keeps Python and JavaScript source at LF on checkout. Source-identity and prefix tests intentionally compare canonical bytes; do not regenerate their hashes after a line-ending conversion. A fresh Windows checkout exposed this packaging issue during preparation. The source bytes were restored to their existing Git identities, with no behavior change.

Run focused checks from the package root with the existing offline fences:

```text
# Developer lane: CPython 3.10.11, Node.js for frontend checks
python -X utf8 -B -W error tests/tooling/public_offline.py selective-groups
python -X utf8 -B -W error tests/tooling/public_offline.py composition-preview
python -X utf8 -B -W error tests/tooling/public_offline.py field-editor
python -X utf8 -B -W error tests/tooling/public_offline.py hotdog-template
node tests/tooling/validate_examples.mjs

# Host-dependency lane: CPython 3.12.11; CPU tensors, no running host or models
python -X utf8 -B -W error tests/tooling/public_offline.py selective-groups-runtime
python -X utf8 -B -W error tests/tooling/public_offline.py release-registration
python -X utf8 -B -W error tests/tooling/validate_examples.py
python -X utf8 -B -W error tests/tooling/validate_feature_examples.py
```

The portable group oracle uses independent Fraction arithmetic and adjacent-IEEE-value rounding; it imports no research prototype or measurements. The public runner does not include private host-cache checks or historical graph-fixture suites requiring unpublished files. The accepted private cache/persistence evidence is retained as qualification, not a public test dependency. The existing Balance `profile-note` expectation from alpha.3 is preserved, and Transfer/Balance adapter pins track the accepted preview adapter.

The feature-example validator checks the new grouped workflow's graph, four embedded fields, exact 25%/25%/50% shares outside the FIXED region, global ownership, serialization and all-layer preview equivalence. It separately checks the accepted MOSS UI/API pair, including native union sockets and empty custom-widget exports. These are structural/numerical checks, not new MOSS runtime qualification.

Accepted feature evidence is carried forward: Contribution's 22 focused tests and 30 CPU/UI checks; groups Stage 1's 88 tests and seven persistence checks; Stage 2's 41 CPU/UI checks with production-bit equivalence; Stage 3's 14 completed Krea 2 Turbo BF16 generations on 0.34.6 / 1.49.6 with owner visual acceptance. The MOSS example carries one successful 0.42.0 / 1.55.18 FIXED generation with its documented models, resolution and alignment. These counts are historical evidence, not a claim that the same suites were rerun publicly. No GPU generations are needed for this packaging candidate.

Candidate verification on **2026-10-23**:

| Check | Result |
| --- | --- |
| `selective-groups` | 56 passed |
| `composition-preview` | 32 passed |
| `selective-groups-runtime` | 23 passed; real Torch on CPU |
| `release-registration` | 29 passed, including retained public sidebar failure isolation |
| `field-editor` | 526 passed after canonical LF checkout correction |
| `hotdog-template` | 15 passed |
| `runtime` | 87 run: 86 passed, one Windows symlink-creation skip |
| Existing example validators | All ten workflows and both brush presets passed |
| Feature examples | Grouped exact weights/preview and MOSS UI/API checks passed |

The full editor rerun had no failures/errors/skips. Its initial three failures were byte-hash differences caused by checkout CRLF conversion; existing identity values were preserved. The candidate also preserves alpha.3's already-correct Balance field-strip assertion. No production behavior was changed to satisfy tests.

An isolated physical installation of the candidate on the supported **ComfyUI 0.34.6 / frontend 1.49.6**, with **Python 3.12.11**, ran on CPU with execution endpoints blocked. All **23 normal nodes plus the optional helper** registered. Thirteen browser checks passed: toolbar/Contribution availability, exact 25% outside and zero inside global FIXED ownership, membership refresh to 50%, grouped native serialize/reload, empty legacy group defaults and byte-exact legacy field restoration. The screenshot was visually inspected. Queue/history stayed unchanged, execution requests were zero, and the owned host/browser stopped. This check does not replace the carried-forward full Save/browser-restart/Open qualification.

Two initial UI harness attempts used the wrong status selector or percentage text format; their captured UI already displayed the expected result. The final check compared numeric weights and passed without changing application code. Three model-selection warnings were expected in this model-free installation; frontend deprecation notices do not constitute new compatibility qualification. No blanket claim is made for later hosts, other models or platforms.

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

The sidebar execution client requires the validated **loopback port 8000** setup. A host on another port can still use native node workflows, but sidebar generation refuses it. Sidebar route initialization also requires input, output, user and model directories with a common filesystem root; different Windows drives can prevent its routes from registering. That failure is logged and no longer prevents the node pack from loading.

## Troubleshooting node availability

The normal package exposes 23 nodes; **Normalized Blend Preparation** is an
optional 24th. It requires exact Torch **2.8.0+cu129**, NumPy **2.4.6**, PyAV
**17.0.1**, no `--fp16-intermediates`, and matching component source hashes.
Execution also requires float32 intermediates. **Compose Conditioning Layers** and **Compose Blend Groups** independently require float32 intermediates too; do not launch with `--fp16-intermediates`. The optional helper's absence alone is expected
outside that profile and does not disable Layer → Add → Compose.

If a normal node group is missing, confirm the entire package is installed and
inspect loader import failures. The loader records group-specific
`*_REGISTRATION_ERROR` values and logs a warning naming each failed registration.
`SIDEBAR_REGISTRATION_ERROR` reports legacy sidebar failures; the independent
node groups still load. The inactive qualification hook logs only the exception
type, preserving its existing secret-redaction boundary. For Painted Field, verify **Edit Field…** appears and opens
before re-saving a workflow, then refresh the browser if necessary.
