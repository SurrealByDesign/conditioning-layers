# Architecture and accepted boundaries

This guide summarizes the accepted architecture. Changes to durable semantics
require an architectural decision record (ADR).

## Accepted direction

One ComfyUI custom-node distribution contains separate authoring, intent and
execution responsibilities. The core depends only on neutral concepts and
standard-library validation. Host integration and adapters depend inward;
neutral domain code does not import ComfyUI, Torch, NumPy or Pillow. Krea 2 is
the only early backend and prompt-based Conditioning Layers the only layer type.
The saved-document model names that type `PromptLayer`; the public node name is Conditioning Layer.

Native workflow authoring and sidebar Conditioning Documents coexist. Native
ComfyUI workflow JSON is host-owned, not the canonical Conditioning Document
schema. They are not automatically converted into one another. The sidebar
keeps its own capability, host/profile and generation checks for saved documents.
Native algorithms accept a positive dynamic layer count, with no arbitrary
three- or nine-layer maximum and no implied resource guarantee.

Native fields are exact 128 × 128, 8-bit-code-recoverable binary32 masks, with
no silent resizing or snapping. Every enabled field has positive support.
Disabled layers stay authored but are excluded from Compose.
Each Conditioning Layer accepts one prompt encode (one conditioning entry,
batch size 1). Only `pooled_output` and `attention_mask` metadata may accompany
it; upstream masks, areas, timestep ranges, ControlNet, GLIGEN and hooks are
unsupported at that input and are rejected.

FIXED owns every positive cell independently of Strength. FIXED/FIXED overlap
fails; FIXED excludes BLENDED at owned cells. Positive-Strength ownership has
weight one; zero-Strength ownership is not refilled. BLENDED normalizes field
value times Strength on the remaining cells, with exact rational preparation
and one binary32 rounding boundary. Zero support has no hidden base fill.
Stack order is deterministic but has no visual priority semantics.

The editor authors field codes only. It reads no prompts, layer Strength,
modes, stack or sampler and implements no composition. A thin frontend adapter
owns host access. Python validates stored field data independently and never
replays strokes. PNG codecs are strict and bounded. Import Mask is an explicit
previewed area-average authoring operation, not implicit runtime resampling.

A session contains at most four Painted Field nodes from one graph, one active
at a time. Each retains its own settings, selection, baseline and history.
Done validates all changed participants before committing them atomically;
Cancel writes nothing. Membership, selections and local history are transient.
Copy From changes the active field only. Transfer and Balance are the two
pairwise exceptions: they conserve each edited cell's integer pair total and
share coordinated undo/redo. Balance's target is the nearest feasible split
to Active Share, with exact-half ties toward the starting active value.
Partner identity and share are session-only, absent from brush presets.

Frozen schemas, canonical bytes, source identities and validation outcomes
remain immutable. Changes are governed by observable contract effects, not
filenames or whether a change is called a bug fix. Referenced identities,
embedded implementation records and independently versioned embedded contracts
have distinct version-propagation rules. Public alpha status does not erase
existing identity obligations or promise a stable public migration scheme.

## Architectural decisions

| Accepted ADRs | Public architectural meaning |
| --- | --- |
| 0002, 0004 | Krea 2 only; prompt-based Conditioning Layers only. |
| 0003, 0007 | Separate planes, one distribution, inward dependencies. |
| 0005 | Dynamic authoring count; practical limits require evidence. |
| 0011 | Observable-effect evolution and immutable historical identities. |
| 0024 | Saved-document layer-count limits and backward compatibility. |
| 0025 | Document composition policy and normalized influence semantics. |
| 0026 | Explicit binary32 numerical realization and isolated Blend registration. |
| 0027 | Separate developer and host test environments, offline network/process restrictions. |
| 0030 | Native Layer/Add/Compose authoring and FIXED/BLENDED rules; native-node changes do not widen sidebar generation support. |
| 0031 | Node-launched editor, exact stored field codes, host/core split. |
| 0032 | Explicit deterministic mask-import reduction. |
| 0033 | Multi-field sessions and atomic Done. |
| 0034 | Pairwise conserved Transfer and linked history. |
| 0035 | Pairwise Balance, feasible split and shared linked history. |

This table summarizes the decisions by number. The historical ADR archive is
not included in this distribution.

## Open questions and deferred work

Physical pen/browser variation, visual localization and practical resource
limits require evidence beyond offline correctness. More than two-field
redistribution, editor normalization, additional backends and layer types,
per-region MODEL-LoRA isolation and stable public migration promises are deferred.
Image-effect compositing, Photoshop equivalence and speculative extension
frameworks are explicit non-goals.

See [the user guide](../README.md) and [maintenance commands](developer.md).
