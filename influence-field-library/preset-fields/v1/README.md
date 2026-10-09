# QR and UPC preset fields

Preset Field loads the QR dark/light pair or synthetic/demo UPC-A `000000000000` dark/light pair.
These are binary spatial structures, not a promise of scannable generated output.
The manifest checks exact PNG identities. QR matrix and decoder-verification
records retain the small reproducibility chain; `generator/generate_presets.py`
is a maintenance helper, not an installation step.

Use [example 05](../../../examples/conditioning-layers/05_patterns_and_templates.json).
The QR payload is exactly `https://github.com/SurrealByDesign/conditioning-layers`.
The synthetic UPC-A has check digit zero and no real-product association.
Both labels remain **QR Code** and **UPC**. These generated demo assets are
covered by the project [Apache-2.0 license](../../../LICENSE); no third-party
stock license is needed.

QR uses version 4, ECC M, mask 2, with the retained 33x33 matrix, three-cell
module pitch and quiet zones. The exact light PNG was independently decoded
without resizing. The project URL exceeds the former version-4/Q capacity.
UPC bars are encoded from the digits, including guards and quiet zones.
`python -B influence-field-library/preset-fields/v1/generator/generate_presets.py --check`
verifies byte-identical regeneration from the package root.
