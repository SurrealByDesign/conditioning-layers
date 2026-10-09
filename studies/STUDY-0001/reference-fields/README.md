# Pattern Field reference assets

This legacy directory is a runtime asset location for Pattern Field. It contains
`pairs.json` and eight source/inverse pairs: checkerboard-coarse,
concentric-rings, diagonal-split, grid-3x3-center-corners, grid-3x3-cross,
horizontal-stripes, scattered-islands and soft-radial-gradient.

Black is zero field value, white maximum and gray intermediate. Gray affects
relative weights where BLENDED Conditioning Layers overlap; it does not
automatically attenuate a lone positive-strength Conditioning Layer.
Inverse pairs exchange each 8-bit code with 255 minus that code. Preserve exact
PNG bytes, manifest checksums and filenames. Patterns describe spatial intent;
they do not guarantee visual separation or perceptually linear output.

Study protocols and participant material are not part of this distribution.
See the [node guide](../../../README.md#node-guide) for normal use.
