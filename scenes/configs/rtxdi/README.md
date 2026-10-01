# RTXDI scene profiles

Profiles: [Cornell](cornell-box.json), [Arcade](arcade.json),
[Bistro](bistro.json), [Zero-Day Measure One](zero-day-measure-one.json).

Schema 2 records the asset root/entry, camera and FOV, motion endpoint, lighting
and fixed preview exposure. The [Cornell runner](../../../scripts/run/rtxdi.py)
accepts the new profile format and legacy argument-based configurations.

Register profiles and source/license information in [the manifest](../../manifest.yaml).
Runtime bundle hashes cover scene wrappers, models, local glTF resources,
Donut's preferred DDS textures and referenced IES profiles. Missing files,
unresolved LFS pointers and paths outside the asset root are rejected.
