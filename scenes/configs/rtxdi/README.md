# RTXDI scene profiles

Profiles: [Cornell](cornell-box.json), [Arcade](arcade.json),
[Bistro](bistro.json), [Zero-Day Measure One](zero-day-measure-one.json),
[San Miguel](san-miguel.json), [Classroom](classroom.json).

San Miguel and Classroom are optional static import previews; they are excluded
from the default baseline scene list. Motion paths are not validated.

Schema 2 separates scene settings from the shared [experiment](../../../experiments/configs/di-reuse.json):
source (repository-relative asset root and entry), camera (position/direction/up/FOV),
motion endpoint, lighting and fixed PNG exposure. Currently lighting uses the
sample's procedural environment, with explicit intensity/rotation and emissive scale.
Preview exposure never changes PFM radiance.

To add a scene:

1. Prepare a Donut-compatible glTF or .scene.json and local resources.
2. Copy a profile, set a new ID, source.kind=file, asset root/entry and camera.
   Choose a short motion path clear of geometry; omit source.asset for file sources.
3. Register provenance and backend_configs.rtxdi in [the manifest](../../manifest.yaml).
   Record runtime_assets.sha256 and file_count from the dependency bundle:
   ~~~python
   import sys
   sys.path.insert(0, "scripts/run")
   from experiment.scenes import load_scene, asset_files, bundle_digest
   scene = load_scene("new-scene")
   files = asset_files(scene["source"]["path"], scene["source"]["root"])
   print({"sha256": bundle_digest(files), "file_count": len(files)})
   ~~~
4. Run rtxdi_reuse.py --scene new-scene --check, then a 640×360 motion check;
   inspect the start/end views and converted materials before comparisons.

The dependency check follows scene wrappers, local glTF resources, Donut's DDS
texture preference and referenced IES profiles. Missing files, LFS pointers and
paths outside the configured asset root fail before rendering. GLB is not supported
by this validator yet. Adding a supported scene requires no Python/C++ changes.
