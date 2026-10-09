# Conditioning Layers

Conditioning Layers gives ComfyUI spatial control over multiple conditioning prompts using editable grayscale **Influence Fields**. Design separate regions, blend concepts through gradients, or paint where each prompt participates. This experimental alpha supports **Krea 2 in ComfyUI** and prompt conditioning only.

![BLENDED gradient fields beside a snowy castle transitioning into a coral reef](docs/images/conditioning-layers-blended-transition.png)

*BLENDED influence fields transition from a violet impasto snow castle into a photographic coral reef.* [Example 03](examples/conditioning-layers/03_blended_gradients.json).

**Recommended for new projects: the node-based Conditioning Layers workflow.** Start with [Example 01](examples/conditioning-layers/01_one_influence_field.json), then build toward more complex compositions.

[Install](#installation) · [Build a workflow](#build-your-first-workflow) · [Node guide](#node-guide) · [Painted Field](#painted-field) · [Examples 01–09](#examples) · [Contributing](docs/developer.md)

## What can you do with it?

- Assign different prompts and visual styles to separate FIXED regions: an oil-painted Renaissance aristocrat on the left, chrome robot advertising art on the right. Start with [Example 02](examples/conditioning-layers/02_two_fixed_regions.json).
- Transition from a snowy castle to a coral reef with overlapping BLENDED gradients. Try [Example 03](examples/conditioning-layers/03_blended_gradients.json).
- Paint where a glowing-armor prompt influences a character, using a reference image to place the field. Learn the editor with [Example 06a](examples/conditioning-layers/06a_painted_field_start.json) and its [completed version](examples/conditioning-layers/06b_painted_field_completed.json). **This controls conditioning during generation; it does not preserve an existing input image the way an inpainting workflow does.** The reference underlay is only a placement guide.
- Build geometric and patterned regions, then transform, repeat, blur, fade, remap or invert their fields. Explore [Example 04](examples/conditioning-layers/04_transform_repeat_fade_remap.json) and [Example 05](examples/conditioning-layers/05_patterns_and_templates.json).
- Import PNG brush tips, paint procedural Scatter or Noise, and explore deterministic Hotdog templates with [Example 07](examples/conditioning-layers/07_advanced_brushes.json). The motif shapes influence; it does not force the model to depict a hotdog.
- Edit several Painted Fields together and copy field content with [Example 08](examples/conditioning-layers/08_multi_field_painting.json). **Transfer** and **Balance** are also available editor tools; the saved example does not demonstrate those operations.
- Combine a photoreal alien market, an oil-painted traveler, watercolor twilight, charcoal smoke and neon graphics with [Example 09](examples/conditioning-layers/09_nine_layer_showcase.json). These are prompt ideas, not additional layer types.

These are creative possibilities, not promises of pixel-perfect localization or linear visual mixing. Prompts can still interact, and seams or semantic leakage can occur. The figures shown here are selected results from Examples 02 and 03; the other examples are editable workflows, not a gallery of verified generated results.

## Installation

1. Use an existing ComfyUI installation and its own Python environment. **Python 3.10 or newer is required by the source**; Windows tests use Python **3.10.11** for the core/editor and **3.12.11** for host-dependent code. Use a Python version supported by your ComfyUI installation. Linux and macOS testing is not established. See the compatibility tiers below.
2. Copy the **complete package folder** to `ComfyUI/custom_nodes/conditioning-layers/`. Its `__init__.py`, `src/`, `web/`, `assets/`, `influence-field-library/` and required `studies/` subtree must remain together. Avoid an extra nested folder between `conditioning-layers/` and `__init__.py` when extracting an archive.
3. There is no separate pip package or frontend build step. The host supplies runtime dependencies such as Torch and aiohttp. **Do not install the contributor test requirements into your working ComfyUI environment as an installation step.** Normal use does not require the [legacy optional node](#legacy--optional-node) or its exact dependency profile.
4. Restart ComfyUI and reload the browser; use a full refresh if old frontend assets remain. Search for **Conditioning Layer** and **Painted Field**. Confirm the Painted Field **Edit Field…** button appears and opens the editor **before re-saving a painted example**. That button verifies its custom widget loaded; saving without the adapter can lose stored field data. Keep the original workflow until this check passes.
5. Open [Example 01](examples/conditioning-layers/01_one_influence_field.json) by dragging the downloaded workflow JSON onto ComfyUI's graph canvas or using its workflow **Open** command. Select compatible locally installed assets in all three loader nodes. In **Load CLIP**, keep the example's **type = `krea2`**.

Models are separate downloads and are not bundled. Select assets from the model publisher's authorized distribution under its terms; no model download URL is supplied in this package. The documented Turbo setup uses:

| Asset | ComfyUI model directory |
| --- | --- |
| `krea2_turbo_bf16.safetensors` | `models/diffusion_models/` |
| `qwen3vl_4b_fp8_scaled.safetensors` | `models/text_encoders/` |
| `qwen_image_vae.safetensors` | `models/vae/` |

The examples use separate model/text-encoder/VAE loaders, not a combined checkpoint loader. `SELECT_...` values are **placeholders for your local files**, not missing bundled downloads; three loader warnings are expected until you select assets. The Turbo examples use eight steps, CFG 1, Euler/simple and an empty negative prompt.

### Update and uninstall

To **update**, back up workflows, exported fields and ComfyUI user data, stop ComfyUI, replace this custom-node folder with the complete new release, then restart and refresh the browser. Check **Edit Field…** before re-saving painted workflows. Update the extension separately from ComfyUI; no host update is part of this procedure.

To **uninstall**, stop ComfyUI, remove `custom_nodes/conditioning-layers/`, then restart and refresh. Workflows that use its nodes will show missing nodes. Keep workflow backups and any exported PNGs. The Brush Library and sidebar documents live in ComfyUI user data separately from this package; removing the package does not remove them.

## Build your first workflow

An **Influence Field** is a **128 × 128, 8-bit ComfyUI MASK** used to control spatial participation of a **Conditioning Layer**. Its 0–255 values travel as a float32 MASK with exactly recoverable 8-bit values.

- **Black:** no influence (0).
- **Gray:** partial field value (1–254).
- **White:** maximum field value (255).

Gray values matter as **relative weights where two or more BLENDED Conditioning Layers overlap**. A BLENDED Conditioning Layer with positive Strength that is alone at a location receives full normalized weight wherever its field is above black and no FIXED Conditioning Layer owns the cell. An enabled FIXED Conditioning Layer owns every positive cell in its region, including gray cells. **A lone gray gradient does not automatically fade a prompt into nothing.**

A field controls participation; it does not paint output colors. A brush changes the field, and the prompt supplies the concept. The saved-document model calls this prompt-only type a **Prompt Layer**; this guide uses **Conditioning Layer**, matching the node name.

Start with Example 01 and its normal Krea 2 loader/sampler connections.

1. Add **CLIP Text Encode** for your regional prompt and connect the Krea 2 CLIP output to it.
2. Add a field source, such as **Rectangle Field**, and a **Conditioning Layer**. Connect the field's `MASK` output to `mask` and the prompt's `CONDITIONING` output to `conditioning`.
3. Set **Strength** from **0–1** (default **1**), choose **FIXED** or **BLENDED** (new nodes default to **BLENDED**), and leave `enabled` on. Example 01 uses a FIXED astronaut region and a BLENDED Solid background.
4. Add **one Add Conditioning Layer node per Conditioning Layer**. Connect `layer` to `layer`. Leave the first Add node's optional `layers` input empty; connect each subsequent Add node's `layers` input to the preceding Add node's stack output.
5. Connect the final stack to **Compose Conditioning Layers**, and its `CONDITIONING` output to the sampler's positive input. Keep the usual model, latent, negative, VAE and output connections shown in Example 01.
6. For a second Conditioning Layer, repeat steps 1–4 with its own prompt and field. Use disjoint FIXED rectangles for Example 02, overlapping BLENDED gradients for Example 03, or **Painted Field → Edit Field… → Done** for painted regions.

```text
Prompt A + Field A -> Conditioning Layer A -> Add A --layers--> Add B -> Compose -> sampler positive
Prompt B + Field B -> Conditioning Layer B --------------------layer--^
```

The `mask` input accepts **MASK data** with exact 128 × 128, 8-bit values. You can load an unresized **128 × 128, 8-bit grayscale PNG** with **Load Image (as Mask)**, selecting **red** (or green/blue for the same grayscale values), rather than the alpha channel. Arbitrary resized or processed masks may fail validation. Use the supplied field processors or the editor's explicit **Import Mask…** operation to produce valid fields. An enabled Conditioning Layer must have some positive field values; disable an empty one instead.

The field grid spans the full output frame. On a non-square output, ComfyUI maps the square mask across the latent width and height without preserving the field's square aspect: a circle can map to an ellipse. Keep the field at 128 × 128 before Compose; ComfyUI performs any downstream mask scaling. The shipped examples use 1024 × 1024; non-square generated results are not established by these examples.

**Example 01 coverage:** a FIXED Ellipse Field (center 44, 72; radii 16 and 36 cells) gives the red astronaut its region. A full-frame Solid Field at value 255 feeds a BLENDED snowfield background. Both have Strength 1; the background fills every cell outside the FIXED ellipse. This is the [background prompt](#background-prompt) recipe in a complete workflow.

## How it fits together

```text
Prompt -> CLIP Text Encode -----+
                               v
Influence Field ----------> Conditioning Layer
  optional field processing    |
                               v
                      Add Conditioning Layer -> ... -> Compose Conditioning Layers
                                                               |
                                                               v
                                                       KSampler positive
```

Encode a prompt, create a field, and connect both to **Conditioning Layer**. Chain one **Add Conditioning Layer** node per Conditioning Layer, then use **Compose Conditioning Layers** to produce conditioning for the sampler. Model loading, latent creation, negative conditioning, sampling, VAE decoding and image saving remain ordinary ComfyUI operations.

### Legacy / document workflow

The sidebar remains available for **`.conditioning.json` documents**. It provides **Open, Save, Save As, Base Prompt, persistent document/layer identities, document-owned PNG fields and composition policy**. This is a distinct saved-document format, not a replacement for normal ComfyUI workflow JSON; the two formats do not automatically convert into each other.

Sidebar generation has narrower limits: **1–3 Active Conditioning Layers with No Overlap**, or **exactly 3 with the document-level Blend policy**. Blend is separate from the nodes' per-layer BLENDED mode. Sidebar generation targets the specific **ComfyUI 0.34.6 / frontend 1.49.6 Krea 2 Turbo BF16 profile**, with additional model/dependency checks. Node/editor testing on newer hosts does not establish sidebar support there. See [sidebar compatibility details](docs/developer.md#sidebar-compatibility).

## FIXED and BLENDED Conditioning Layers

**FIXED means spatial ownership.** Every positive cell in an enabled FIXED field belongs to that Conditioning Layer. Two enabled FIXED regions cannot overlap, even if one has Strength zero. Soft gray edges still claim ownership; they do not feather a FIXED boundary.

![Complementary FIXED fields beside a Renaissance portrait and chrome robot composition](docs/images/conditioning-layers-fixed-regions.png)

*FIXED regions assign exclusive conditioning ownership: a candlelit Renaissance portrait on the left and chrome neon advertising art on the right.* [Example 02](examples/conditioning-layers/02_two_fixed_regions.json).

**BLENDED means normalized sharing.** Fields may overlap; their participating influences normalize against one another. Use opposing gradients to transition between two prompts. Strength changes relative weight where contributors overlap. One positive contributor receives the whole local share.

You may mix the two modes: FIXED ownership is resolved first, and BLENDED Conditioning Layers share the remaining locations. A zero-Strength FIXED owner still reserves its region but contributes nothing there. Stack order does not provide a tie-break or visual priority. Disable a Conditioning Layer to remove its participation.

Participating BLENDED Conditioning Layers use `u = field × Strength`, then `weight = u / sum(u)` wherever the sum is positive. Where nothing participates, there is **no hidden base prompt fill**; this does not promise blank pixels or preservation of an input image.

### Background prompt

For subject regions on FIXED Conditioning Layers, add a full-frame **Solid Field** (value 255) as a **BLENDED background Conditioning Layer** with positive Strength. It fills cells no FIXED Conditioning Layer owns.

If the background Solid overlaps BLENDED Conditioning Layers, its **Strength participates in normalization**. Lower its Strength if you want the other BLENDED Conditioning Layers to dominate. Stack position does not make it a background; the field and mode do.

Example prompts may repeat scene/context text so each regional prompt carries that context. There is **no hidden node-system Base Prompt automatically filling uncovered regions**. Add the background explicitly when you want full-frame support.

### How it works for technical users

**Compose Conditioning Layers outputs ordinary ComfyUI masked conditioning entries**, one per enabled Conditioning Layer. Each gets its own normalized weight mask, with FIXED ownership resolved first. The original prompt tensors are preserved; Compose sets `mask_strength` to 1 and `set_area_to_bounds` to false. It builds on ComfyUI conditioning and does not replace the sampler.

Each Conditioning Layer accepts one prompt encode (one conditioning entry, batch size 1). Upstream masks, areas, timestep ranges, GLIGEN and hooks are rejected. **ControlNet-modified conditioning is unsupported at the Conditioning Layer input.** No end-to-end ControlNet compatibility is claimed for other graph arrangements.

## Node guide

The names below are the runtime display names. Search for them in ComfyUI; QR and UPC are choices within **Preset Field**, not separate nodes.

### Assemble Conditioning Layers

| Node | Purpose and common use | Try it |
| --- | --- | --- |
| **Conditioning Layer** | Pairs conditioning with a field, Strength, FIXED/BLENDED mode and enabled state. | Give two Conditioning Layers distinct regional prompts. |
| **Add Conditioning Layer** | Starts an ordered stack or appends one Conditioning Layer to it. | Add a sky or foreground Conditioning Layer. |
| **Compose Conditioning Layers** | Validates enabled Conditioning Layers and resolves their spatial weights into sampler conditioning. | Use BLENDED gradients with overlapping companions to explore sharing. |

### Create fields

| Node | Purpose and common use | Try it |
| --- | --- | --- |
| **Solid Field** | Makes a constant field, useful for full-frame BLENDED support. | Add a broad atmosphere prompt sharing space with regional BLENDED fields. |
| **Rectangle Field** | Defines a rectangular region for panels, horizons or graphic layouts. | Split the frame into nonoverlapping left/right FIXED regions. |
| **Ellipse Field** | Defines an elliptical region for subjects and circular details. | Place an oval over a portrait subject. |
| **Linear Gradient Field** | Changes influence along a direction for transitions. | Pair opposing gradients with two BLENDED prompts. |
| **Radial Gradient Field** | Varies field values around a center for relative BLENDED weighting. | Share a central concept with an overlapping BLENDED background. |
| **Pattern Field** | Loads one of the shipped patterns and inverse variants. | Explore checkerboard, rings, stripes or scattered islands. |
| **Scatter Field** | Generates seeded scattered shapes across the field. | Make repeated islands of a contrasting prompt. |
| **Noise Field** | Generates deterministic noise-based influence. | Build irregular smoke or weather regions with BLENDED layers. |
| **Cyclic Partition Field** | Produces members of a repeating spatial partition. | Give alternating regions different prompts using matching settings and different members. |
| **Voronoi Partition Field** | Produces seeded nearest-site partition regions. | Make an irregular mosaic of concepts. |
| **Polar Partition Field** | Produces partition regions arranged around a center. | Build a radial composition from matching partition members. |
| **Preset Field** | Loads checksum-verified binary QR or UPC fields with dark/light variants. | Use QR structure or barcode stripes to organize a graphic prompt. Generated images are not guaranteed scannable codes. |
| **Painted Field** | Stores a field painted or imported in the node-launched editor. | Trace selected armor plates over a reference underlay. |

### Process fields

These nodes process the field before it reaches a Conditioning Layer. They do not apply image effects to generated pixels.

| Node | Purpose and common use | Try it |
| --- | --- | --- |
| **Field Transform** | Moves, scales and rotates a field. | Rotate an ellipse into a diagonal subject region. |
| **Field Repeat** | Repeats an existing field across X and Y for windows, tiles, signs or stripes. | Connect Rectangle Field or Pattern Field and increase Repeat X/Y. |
| **Field Remap** | Remaps field values to change relative BLENDED weights or positive support. | Tighten a gray transition before BLENDED composition. |
| **Field Blur** | Smooths field values spatially; it can extend positive support. | Smooth relative sharing between overlapping BLENDED Conditioning Layers. |
| **Field Fade** | Reduces field values spatially. | Reduce repeated motifs' relative weight toward an edge where another BLENDED Conditioning Layer overlaps. |
| **Invert Field** | Exchanges low and high influence. | Derive an opposing gradient from the first field. |

### Legacy / optional node

**Normalized Blend Preparation** is a lower-level helper for exactly three conditioning entries. It registers only when **Torch 2.8.0+cu129, NumPy 2.4.6 and PyAV 17.0.1** match exactly, `--fp16-intermediates` is absent, and its source-integrity check passes. Execution also requires float32 intermediates.

Its absence is normal on most installations and it is **not required for normal Conditioning Layers usage**. **22 nodes versus 23 is not, by itself, a broken installation**: the extra node is this optional helper. Use **Conditioning Layer → Add Conditioning Layer → Compose Conditioning Layers** for normal workflows.

## Painted Field

Click **Edit Field…** on a Painted Field node or double-click its thumbnail. The editor changes the field's grayscale values. It does not read your prompts, choose layer modes or generate an image.

Start with **Paint**, **Erase**, **Size**, **Influence**, **Hardness** and **Amount**:

- **Paint** moves covered cells toward the chosen Influence value. **Erase** moves them toward black. **Restore**, in Advanced Brush Behavior, paints toward the field as it was when it joined the session.
- **Size** controls the footprint in field cells. **Influence** is the target value, shown as a percentage or an exact 0–255 value. **Amount** limits how far a stroke moves toward its target. **Hardness** controls the full-coverage portion of the footprint and its soft edge.
- Use **Undo/Redo** to revise local edits. **Done** commits fields and settings back to the nodes; **Cancel** discards this session's changes. Save the ComfyUI workflow afterward to keep the committed fields.

Open **Advanced** when you need more control. Rectangle and ellipse selections constrain edits; combine, invert or clear selections to isolate a region. Clear/Fill/Invert act within the selection when one is active. Field Tools also provide exact flips and quarter-turn rotations; clear the selection before those whole-field transforms. Use the Field Transform node for adjustable offsets, scaling and other angles.

A **reference image** is a display-only guide. Grid and **Heat View** help inspect cell boundaries and low influence; **Alt-click** samples a field value with the eyedropper. These views do not become conditioning or modify the saved field.

**Import PNG** reads an exact 128 × 128 grayscale field. **Advanced > Field Tools > Import Mask…** accepts supported PNG masks at other sizes, shows an explicit preview, and reduces/enlarges them to the field grid with deterministic area averaging. Choose Graded or Binary output and review before Apply. Import Mask creates one undo step and respects the active selection. **Export PNG** saves the field for reuse.

### Shortcuts

These shortcuts apply while the editor is active and you are not typing in a numeric control or using a subdialog.

| Shortcut / gesture | Action |
| --- | --- |
| **B / E** | Paint / Erase |
| **Ctrl/Cmd+Z** | Undo |
| **Ctrl/Cmd+Shift+Z** or **Ctrl/Cmd+Y** | Redo |
| **[ / ]** | Decrease / increase brush Size by 1 |
| **Shift+[ / Shift+]** | Decrease / increase Hardness by 1 |
| **1–9, 0** | Influence 10–90%, then 100% |
| **F** | Fit the field in the view |
| **Hold Space + drag** | Pan; when the Compare button is focused, Space instead reveals the reference |
| **Esc** | Cancel, with discard confirmation if changed; during a stroke/selection gesture, abort that gesture first |
| **Alt-click** | Eyedropper: sample the field value (turn off the selection tool first) |
| **Drag PNG onto the canvas** | Import an exact 128 × 128 grayscale field; use Import Mask… for other supported PNG sizes |

### Brushes

#### Basic brush shapes

Disk, Square and Diamond define the footprint. **Advanced > Brush Shape & Transform** lets you scale and rotate it; falloff shapes its edge.

#### Brush behavior

Spacing controls stamps along the stroke. **Build-up** enables distance-based accumulation, with **Flow** controlling its rate, capped by Amount. **Raise Only** and **Lower Only** constrain ordinary edits to one direction. Uniform, Linear Gradient, Radial Gradient and Square Gradient value profiles control the values painted within the footprint.

#### Custom Tip

Import a local PNG. Choose **Alpha**, **Luminance** or **Alpha × Luminance** to determine coverage, and use crop/trim, scale, mirror and rotation controls to place it. The tip shapes where influence is painted; its colors do not become output colors. The accepted tip data can travel with saved settings and brush presets, without depending on the original local filename.

#### Procedural brushes

Scatter and Noise produce reusable deterministic tips. Scatter offers built-in Circle, Rectangle, Diamond, Trapezoid and Irregular shapes, plus Hotdog. Adjust the seed and the applicable density, size and jitter controls to explore variants.

#### Hotdog Template

This built-in deterministic motif/scatter example demonstrates template-backed brushes. Set **Count from 1-1024**, then adjust Size, Spread, Rotation, Rotation Jitter, Mirror and Invert. **Count = 1** behaves like a single motif brush; larger counts create a deterministic scatter. The same seed and settings reproduce the same template layout. Spread changes placement rather than count; brush Size scales the overall footprint. A motif remains an influence structure, not an inserted picture.

#### Brush Library

Save reusable brush configurations and **Apply**, **Update**, **Rename**, **Duplicate** or **Delete** them. Use favorites, categories and search to find a preset. The library is available across workflows/editor sessions in the same ComfyUI user setup; export/import preset JSON to share configurations. Opening an example does not install its presets automatically.

The library is stored in **ComfyUI user data** as `conditioning-layers/brush-library-v1.json`. It is user-level data, separate from workflow state; export it when moving reusable brushes to another installation.

Presets store brush configuration, not field content, selections, history or field relationships. **Transfer/Balance partner identity and Active Share are not stored.** Applying a preset does not select a partner or change the active cross-field tool.

#### Pressure

When enabled, pen pressure can affect **Size**, **Amount** and **Flow**; Flow pressure applies with Build-up. Choose the mappings you want. A physical pen is optional: mouse, touch and Shift-click lines use the set values. Some pressure tests used synthetic pen events, so physical-device behavior should be checked on your own tablet/browser combination.

### Multi-field editing

Open one Painted Field, then use **Add Field** to bring in other Painted Field nodes from the same workflow. A session holds **up to four fields**. Exactly one is active and editable; the others appear as overlays. Select a field to make it active.

Each field keeps its own brush settings, selection, Restore baseline and local history as you switch. **Copy From** replaces active-field cells with another participant's current values, respecting the active selection and leaving the source unchanged. **Done** commits the participating changes together; **Cancel** discards them together. Reopening starts a new session: add companion fields again as needed.

### Transfer

Transfer moves influence **from another participating field into the active field**. The active field is the destination. In **Advanced > Brush Behavior**, choose **Transfer from** the source field, then paint.

At each changed cell, what the destination gains, the source loses. Their **local pair total is conserved**:

```text
Source 200 + Destination 40 = 240
                  move 30
Source 170 + Destination 70 = 240
```

Brush coverage determines where transfer occurs; Amount controls movement toward the available limit. Transfer works with Custom Tip, Procedural and Hotdog brushes, selections and pressure. It cannot drain below zero or fill above 255. The active field's selection gates both changes. Influence targets, gradient value profiles and Raise/Lower do not apply to this tool.

Paired Undo/Redo keeps both fields synchronized. If a partner has a later edit, the editor tells you which field to undo first rather than undoing only half the transfer.

Transfer is useful for moving a boundary or exchanging influence without adding to the pair's local total. Its **source/destination pairing is session-only**: after reopening, add the companion field and choose the source again.

### Balance

Balance paints two fields **toward a chosen ratio**. Choose **Balance with** one partner, then set **Active Share (%) from 0-100**. A stroke can move influence in either direction automatically, with the same conserved local pair total.

```text
Active A = 20, Partner B = 180; total = 200
Active Share = 75% -> target 75:25 -> A = 150, B = 50
```

That is the target split: brush coverage and Amount determine how far a stroke moves toward it. Whole-number values and the 0-255 limit may restrict the exact split when the total is large. **100% corresponds to Transfer from the partner; 0% moves in the reverse direction.** Balance uses one active field and one partner, with paired Undo/Redo. It does not normalize all fields or inspect FIXED/BLENDED composition.

Balance is useful when you want a consistent relative split, such as more atmosphere and less subject influence, without changing the pair's local total. **The partner and Active Share are session-only**. Reopening starts with no partner and Active Share **50%**; select the tool and partner again.

For **two enabled BLENDED Conditioning Layers with equal Strength**, conserving their local field total keeps their combined unnormalized weight unchanged. At cells not owned by FIXED, a third unchanged overlapping BLENDED Conditioning Layer therefore keeps its normalized share, provided all other inputs stay unchanged. This follows from `field × Strength` normalization on the field grid; it is not a promise that generated pixels stay unchanged. Different Strengths, later field processing or FIXED ownership can invalidate that reasoning. The editor itself does not inspect modes or Strength.

## Examples

The [Conditioning Layers Examples](examples/conditioning-layers/README.md) are the official example set. **Start with 01, then 02 and 03; use 06a/06b to learn painting.** Open their JSON files manually in ComfyUI; nested examples are not promised to appear automatically in a template gallery.

| Sequence | Scene and feature |
| --- | --- |
| [01 - One Influence Field](examples/conditioning-layers/01_one_influence_field.json) | Red astronaut in snow: FIXED ellipse plus BLENDED Solid background. |
| [02 - Two Fixed Regions](examples/conditioning-layers/02_two_fixed_regions.json) | Renaissance portrait versus chrome robot advert: disjoint left/right ownership. |
| [03 - Blended Gradients](examples/conditioning-layers/03_blended_gradients.json) | Snowy castle into coral reef: opposing gradients and a radial bubble seam. |
| [04 - Field Processing](examples/conditioning-layers/04_transform_repeat_fade_remap.json) | Neon megablock: Rectangle through Repeat, Transform, Fade, Remap and Blur. |
| [05 - Patterns and Templates](examples/conditioning-layers/05_patterns_and_templates.json) | Retro diner collage: complementary patterns, QR/UPC presets and Hotdog line art. |
| [06a - Painted Field Start](examples/conditioning-layers/06a_painted_field_start.json) / [06b - Completed](examples/conditioning-layers/06b_painted_field_completed.json) | Rune-lit knight: starter and completed local glow fields. |
| [07 - Advanced Brushes](examples/conditioning-layers/07_advanced_brushes.json) | Hotdog nebula: Custom Tip, procedural Noise and single/scattered/inverted Hotdogs. |
| [08 - Multi-Field Painting](examples/conditioning-layers/08_multi_field_painting.json) | Tin-toy robot: four coordinated fields, tabs, overlays and Copy from. |
| [09 - Nine-Layer Showcase](examples/conditioning-layers/09_nine_layer_showcase.json) | Alien night market: distinct regional styles using the major tools together. |

Import [Hotdog meteor shower](examples/conditioning-layers/presets/hotdog_meteor_shower.brush.json) and [Sparkle glints](examples/conditioning-layers/presets/sparkle_glints.brush.json) through Brush Library for the brushes used in 07. All examples provide full field coverage. The pack contains instructions and embedded fields/tips, not verified generated outputs. Nine layers is a demonstration, not a maximum or a resource guarantee.

## Compatibility

| Tier | ComfyUI | Frontend | Evidence |
| --- | --- | --- | --- |
| Qualified baseline | 0.34.6 | 1.49.6 | Established baseline testing. |
| Successfully functional-smoke-tested | 0.39.2 | 1.53.10 | Core painting, brushes, multi-field editing, Transfer, Balance, Undo/Redo, save/reopen and example loading. |

The newer pair has narrower test coverage than the baseline. Other combinations are not established. These node/editor results do not widen sidebar generation support. See the [public validation summary](docs/developer.md#validation) for automated checks and their limits.

## Current limits

- Krea 2 and prompt-based Conditioning Layers only; there is no claim of other-backend compatibility, separate Style/Control/LoRA layers or per-region MODEL-LoRA isolation.
- Native fields remain 128 × 128. Spatial influence is experimental; perceptual linearity and perfect isolation are not guaranteed.
- Multi-field sessions hold four Painted Fields maximum. Transfer and Balance are pairwise; N-field normalization/redistribution is not implemented in the editor.
- Connect one plain prompt encode per Conditioning Layer. ControlNet-modified conditioning and other upstream spatial/scheduling metadata are unsupported at that input; see [How it works](#how-it-works-for-technical-users).
- Models must be selected locally. Layer count can increase sampling cost; example 09 establishes no GPU-memory budget.
- Sidebar generation has separate document and host limits: 1–3 Active Conditioning Layers with No Overlap, or exactly 3 with document-level Blend. Larger native node compositions do not widen these limits.
- This alpha makes no stable public workflow-schema or migration promise. Keep backups of valuable workflows, especially before loading them without the extension installed.

## Development

Python lives in `src/conditioning_layers/`; the root `__init__.py` is the ComfyUI loader. Frontend modules live in `web/js/`, with editor logic in `web/js/field_editor/` and the host adapter in `web/js/painted_field_node.js`. Runtime field assets retain their existing library and `studies/STUDY-0001/reference-fields/` locations.

From the package root, use a configured developer Python environment and Node.js for the editor lane:

```text
python -X utf8 -B -W error tests/tooling/public_offline.py domain
python -X utf8 -B -W error tests/tooling/public_offline.py field-editor
python -X utf8 -B -W error tests/tooling/public_offline.py hotdog-template
node tests/tooling/validate_examples.mjs
```

Node/runtime and Python example validation use the separate host-dependency lane. See [developer instructions and all test groups](docs/developer.md), [architecture](docs/architecture.md) and [validation results](docs/developer.md#validation).

## License and contact

Copyright 2026 SurrealByDesign. Licensed under the [Apache License 2.0](LICENSE).

The shipped Hotdog artwork/template is project-created for Conditioning Layers.
The **QR Code** demo preset points to `https://github.com/SurrealByDesign/conditioning-layers`.
The **UPC** preset encodes `000000000000`, a synthetic/demo UPC-A with no real-product association.
These demo assets need no third-party stock license.

**SurrealByDesign** - surrealbydesign@protonmail.com
