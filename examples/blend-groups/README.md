# Blend Groups and Contribution

Open [grouped_contribution.json](grouped_contribution.json) in ComfyUI. It is a complete native Krea 2 workflow with embedded fields and no external image assets. Replace the three `SELECT_...` model selections with your local Krea 2 model, matching encoder and VAE. Keep CLIP type `krea2`. Eight Turbo steps, CFG 1 and Euler/simple match the existing examples. No model is needed to inspect Contribution.

Four direct Painted Fields feed four Conditioning Layers:

| Layer | Mode | Blend Group | Field |
| --- | --- | --- | --- |
| Copper | BLENDED | `materials` | Full field |
| Blue glaze | BLENDED | `materials` | Full field |
| Greenhouse | BLENDED | `environment` | Full field |
| Red robot | FIXED | `materials` (ignored for ownership) | Central ellipse |

With all Strengths at 1, Copper and Blue glaze each receive 25% outside the ellipse; Greenhouse receives 50%. Inside it, Red robot receives 100% and all three BLENDED layers receive zero. FIXED ownership crosses group boundaries. These are prepared conditioning weights, not predictions of image colors or appearance.

1. Open Copper's **Edit Field…** and switch **Fields → Contribution**. Select its grouped Compose/layer context if requested. Inspect the 25% outside and 0% inside the ellipse.
2. Open Greenhouse to inspect 50% outside, or Red robot for its global FIXED region. You can also **Add Field** to join all four fields in one editor session.
3. Change Copper's Strength to 0.5. Its group still competes at the Blue glaze maximum of 1: outside the ellipse, Copper becomes about 16.67%, Blue glaze 33.33%, Greenhouse 50%.
4. Change both material Strengths to 0.5: their group becomes weaker and Greenhouse rises to about 66.67%. Strongest-member changes can affect other groups.
5. Disable Red robot to reveal the BLENDED mixture inside its ellipse. Setting its Strength to zero instead keeps FIXED ownership but contributes no weight there.
6. Paint or erase in Fields view, then inspect Contribution. Pending/stale states are intentional; **Done** commits edits and **Cancel** discards them. The preview selection is session-only.

To compare legacy flat blending, use a copy of the workflow, replace **Compose Blend Groups** with **Compose Conditioning Layers**, reconnect its stack/output, and clear **all four blend_group values**. At Strength 1 outside the ellipse the three BLENDED layers become one-third each; FIXED behavior stays the same. Legacy Compose rejects assignments even on FIXED or disabled layers.

The fields connect directly: inserting a processor makes Contribution unavailable until the direct connection is restored. The preview does no generation. This tutorial is structurally and numerically validated teaching material, not a newly GPU-qualified image result. The [main guide](../../README.md#selective-blend-groups) explains limits and the [developer guide](../../docs/developer.md) records validation.
