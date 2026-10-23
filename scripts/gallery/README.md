# Scene gallery

From the repository root:

```powershell
python -B scripts/gallery/render.py --sync --html
python -B scripts/gallery/render.py --verify
python -B scripts/gallery/render.py --output-dir runs/scene-gallery --render --view cornell-box/view-a
```

The output directory contains gallery.json, scenes/*.json, manifests, records and PNGs. The default is runs/scene-gallery. The legacy runs/scene-gallery/render.py command forwards to this implementation. Templates and implementation are versioned here; tests/test_gallery_catalog.py runs without a GPU or downloaded assets.

Run --check before rendering after a build change. Existing render settings, exposures and source records remain authoritative. source-migration.json in the existing gallery points to the frozen tool version present immediately before migration and matches manifest.reproduction.tool_sources. Earlier per-view render records retain their original script hashes and exact native configurations; the new snapshots cover the pre-migration tool version only.
