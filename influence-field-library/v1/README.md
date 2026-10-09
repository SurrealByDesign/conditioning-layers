# Influence Field library v1

Five immutable families: left/right, top/bottom, vertical thirds, horizontal
thirds and center/ring/outer. Manifests bind exact PNG bytes and field relationships.
White means maximum field value, black zero. Complement images support
validation; the sidebar offers only the supported preset members.

`generators/generate_library.py` reproduces the deterministic library for
maintenance. It is not an install step. `previews/` contains inspection sheets.
The [inspection workflows](workflows/README.md) are asset-maintenance fixtures;
use the [user examples](../../examples/conditioning-layers/README.md) to learn
native composition. Passing library checks makes no visual-quality promise.
