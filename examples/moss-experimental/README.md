# Experimental: native MOSS-Image with Conditioning Layers FIXED composition

> **Experimental.** This is one qualified example, not a supported product
> profile. It sits outside the Krea 2 compatibility claims in
> [Compatibility](../../README.md#compatibility) and outside the Krea 2 examples.
> Its example-only standing is summarized in the
> [accepted architecture](../../docs/architecture.md#architectural-decisions).

Two MOSS layout prompts share one harbor scene. Each adds its own subject box:
a red car on the left, a sailboat on the right. Two FIXED Prompt Layers give the
left and right halves of the image to the matching encoded layout prompt.

| File | Use |
| --- | --- |
| [moss_experimental_fixed.json](moss_experimental_fixed.json) | UI workflow: open it in ComfyUI |
| [moss_experimental_fixed_api.json](moss_experimental_fixed_api.json) | API prompt the frontend exports from it, as executed |

## Requirements

- ComfyUI **0.42.0**, using only its built-in MOSS nodes: `CreateBoundingBoxes`,
  `MOSSImageLayoutPrompt`, `EmptyFlux2LatentImage`. No third-party MOSS node
  pack is needed or used.
- Conditioning Layers nodes: Rectangle Field, Invert Field, Layer, Add Layer,
  Compose. FIXED only. Blend Groups is not qualified for this MOSS example.
- Models, referenced by filename:

  | Folder | File | Bytes |
  | --- | --- | --- |
  | `diffusion_models` | `moss_image_sft_int8_convrot.safetensors` | 5,413,698,958 |
  | `text_encoders` | `mossImage_sft_txt_int8.safetensors` (CLIP type `moss_image`) | 9,748,121,532 |
  | `vae` | `flux2-vae.safetensors` | 336,213,556 |

- Settings: 1024×1024, seed 20261022 (`fixed`), 25 steps, CFG 2.5,
  `er_sde` / `simple`, denoise 1.0.

## Verified restrictions

1. **Keep 1024×1024.** MOSS stores a 64×64 latent grid at this size. A
   128×128 Influence Field is exact only when it is constant within aligned
   2×2 cells. This example's boundary at column 64 (pixel 512) is aligned.
2. **Painted gradients and unaligned FIXED boundaries are not exact.**
3. **Cover the whole image with positive layers.** With CFG above 1, the
   negative prompt also acts on uncovered regions.
4. **Layout boxes are learned guidance, not ownership.** In the qualified run,
   the car is small near the horizon instead of filling its large lower-left
   box. The FIXED field, not the box, controls which prompt reaches each half.
5. **Boxes are `[ymin, xmin, ymax, xmax]` on a 0–1000 grid.** They are typed in
   the two text nodes. `bboxes` on Create Bounding Boxes accepts only a link,
   not a widget. The node's drawing canvas works only in **Nodes 2.0**. Canvas
   edits override the text until that text changes.
6. **Only FIXED was qualified on the live host.** BLENDED and other field types
   were not exercised with MOSS.
7. **One model per graph.** Mixing MOSS and Krea 2 predictions is not supported.
8. **The qualification used input, output, user and models on one drive.**
   The legacy sidebar can fail on a split-drive layout (`Paths don't have the
   same drive`). The public loader isolates sidebar failure so native nodes can
   still register. This is not evidence that every split-drive setup works;
   inspect registration warnings if installation fails.

## Qualification record

- **Host:** real ComfyUI 0.42.0 server (`355cd6b14c92`, frontend 1.55.18) on
  loopback. The isolated base loaded only Conditioning Layers, from baseline
  `62d9de0c3803`.
- **Environment:** Python 3.12.11, torch 2.8.0+cu129, RTX 5080 16 GB.
- **Registration and validation:** All 15 graph node types registered, and all
  model and sampler selections were listed. The UI workflow reloaded identically
  in a fresh browser profile. Its export type-checks on all 25 links. It matches
  the earlier in-process v003 graph apart from the two text nodes and the
  output prefix.
- **Single GPU generation:** queued once, succeeded, with no warnings or errors
  in the run log. Wall time was 77.2 s, of which sampling took 71.1 s (2.80 s/it)
  and decode 0.5 s.
- **Memory:** Peak device memory was 15.5 GB (nvidia-smi, 4.4 GB baseline).
  The host staged the 9.3 GB text encoder and the 5.2 GB diffusion model for
  dynamic VRAM loading. Free device memory fell to 136 MB.
- **Image:** pixel-identical to the v003 output (RGB SHA-256 `bb6f7246…`,
  maximum difference 0).
