# Conditioning Layers Examples

Ten editable ComfyUI workflows teach spatial prompt control from a single subject
region to a nine-layer composition. **Start with 01, then 02 and 03.** For painting,
start with 06a and compare 06b. The filenames follow this progression; 06 has two
states of the same exercise.

| Example | Scene | What it demonstrates |
| --- | --- | --- |
| [01 - One Influence Field](01_one_influence_field.json) | Red astronaut in snow | A FIXED ellipse owns the subject region; a BLENDED Solid Field fills the background. |
| [02 - Two Fixed Regions](02_two_fixed_regions.json) | Renaissance aristocrat beside a chrome robot advert | Two disjoint FIXED halves separate radically different subjects and styles. |
| [03 - Blended Gradients](03_blended_gradients.json) | Snowy castle into coral reef | Opposing BLENDED gradients share influence, with a third radial bubble field at the transition. |
| [04 - Field Processing](04_transform_repeat_fade_remap.json) | Rain-soaked neon megablock | Rectangle, Repeat, Transform, Fade, Remap and Blur build a window grid over a Solid backdrop. |
| [05 - Patterns and Templates](05_patterns_and_templates.json) | Retro diner collage | Complementary patterns, QR/UPC preset fields and a painted Hotdog template combine with separate FIXED details. |
| [06a - Painted Field Start](06a_painted_field_start.json) / [06b - Completed](06b_painted_field_completed.json) | Rune-lit knight in a crypt | Add local rune/glow influence with painting, erasing, selections and straight strokes; compare the starter and completed fields. |
| [07 - Advanced Brushes](07_advanced_brushes.json) | Hotdog nebula | Procedural Noise, an embedded Custom Tip, single/scattered Hotdogs, Count, Spread, Rotation, Jitter, Mirror and Invert Template. |
| [08 - Multi-Field Painting](08_multi_field_painting.json) | Tin-toy robot in a vintage toy shop | Four locally editable fields: head glow, body plating, sparks and window light; tabs, overlays and Copy from. |
| [09 - Nine-Layer Showcase](09_nine_layer_showcase.json) | Alien night market under a neon moon | Nine prompts with distinct styles combine FIXED ownership, BLENDED gradients, processors, patterns and four Painted Fields. |

## Open and explore

Drag a workflow JSON onto ComfyUI or use its workflow Open command. Replace the
three `SELECT_...` loader values with your locally installed Krea 2 model, matching
text encoder and VAE; keep Load CLIP type `krea2`. The examples use 1024 x 1024,
eight Turbo steps, CFG 1, Euler/simple and an empty negative prompt. Three loader
warnings are expected until you select models. See [installation](../../README.md#installation).
Images save under `ConditioningLayers/`.

Read each workflow's **WHAT THIS SHOWS**, **TRY THIS** and **IMPORTANT** notes.
Every workflow provides full field coverage, and every layer leads somewhere.
FIXED owns positive field cells; gray values produce relative weights where
BLENDED layers overlap. Fields control conditioning participation, not output
pixels: generated images can still show seams, leakage or changes elsewhere.
These workflows are teaching material, not verified generated-image results.

## Painting and reusable brushes

Confirm **Edit Field...** appears before re-saving a Painted Field workflow.
Open a field with that button or its thumbnail; **Done** keeps edits and **Cancel**
discards them. Example 06 changes rune influence during generation; it is not
inpainting and does not preserve an existing image.

In 08, open one Painted Field and use **Add Field...** to join the other three.
In 09, join L3, L7, L8 and L9. Ordinary painting edits one active field while the
others appear as overlays. Each field keeps its own brush. Selections, Undo
history and session membership are not saved. **Transfer and Balance are available
editor tools but are not demonstrated by saved edits in this pack**; see the
[Transfer](../../README.md#transfer) and [Balance](../../README.md#balance) guides.

Import [Hotdog meteor shower](presets/hotdog_meteor_shower.brush.json) or
[Sparkle glints](presets/sparkle_glints.brush.json) using **Brush Library... >
Import Preset JSON...**, then select it and **Apply**. They match L5 and L3 in 07;
opening a workflow installs nothing. The original sparkle tip is embedded.

The Hotdog line-art template is project-created. The QR Code preset points to
`https://github.com/SurrealByDesign/conditioning-layers`; UPC is the synthetic/demo
code `000000000000`. These shapes define influence, not a guaranteed rendered
symbol or scannable code. Nine layers is a demonstration, not a maximum or a
GPU-memory guarantee.
