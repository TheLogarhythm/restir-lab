# Scene Gallery

Browse configured RTXDI scenes and choose presentation images in the [gallery](index.html). Click an image for full resolution. The undenoised version is on the left and the OIDN version on the right. Scene counts, view counts and completion status are generated from the configuration.

## Files and responsibilities

```text
scene-gallery/
├── gallery.json                 Default resolution, render budget, OIDN path and frozen experiment definition
├── scenes/                      Editable configuration: one JSON file per scene
│   ├── cornell-box.json
│   └── ...
├── render.py                    Command entry point, native rendering and PNG postprocessing
├── gallery_tools/
│   ├── catalog.py               Configuration validation, scene discovery, state merging and change detection
│   ├── site.py                  HTML generation, image and reproduction-record verification
│   └── page.html                Static page template and styles
├── tests/test_catalog.py        Extension and rendering-workflow checks without a GPU
├── manifest.json                Generated configuration snapshots, asset sources, completion status and result hashes
├── verification.json            Most recent integrity check
├── index.html                   Generated gallery, ready to open
└── <scene-id>/
    ├── view-a/
    │   ├── raw.png
    │   ├── processed.png
    │   ├── config.json          Native configuration used for this render; reproducible from this directory
    │   ├── render-record.json   Input frame hashes, exposure, processing, timings and reproduction details
    │   ├── renderer.log
    │   ├── timings.csv
    │   └── resolved.json
    └── view-b/
```

Edit `gallery.json` and `scenes/*.json` for routine changes. Do not edit the generated `manifest.json`, `index.html` or historical `render-record.json` files by hand. Scene IDs match repository registry entries, and view IDs are unique within each scene. Both use lowercase letters, digits and hyphens. Directory names do not use dates or depend on a fixed scene count.

The `scene_order` in `gallery.json` controls the order of existing sections. New configurations are discovered automatically and appended; add their IDs to this list when you want to change the order. Each scene has two views by default and can have more.

## Add a scene

Run these commands from the **restir-lab repository root**. Run only one native renderer process at a time.

1. First import the scene into the repository: record asset sources and licenses in `THIRD_PARTY.md`, register it in `scenes/manifest.yaml`, and configure `scenes/configs/rtxdi/<scene-id>.json`. The gallery reuses these assets and validation interfaces without copying models or textures.
2. List the available IDs, then create the gallery configuration. Replace the ID in this PowerShell example with a real registry entry:

   ```powershell
   python -B runs/scene-gallery/render.py --list-scenes
   $sceneId = 'your-registered-scene-id'
   python -B runs/scene-gallery/render.py --add-scene $sceneId
   ```

   The command creates `scenes/<scene-id>.json` and updates the gallery without overwriting existing configurations. `view-a` uses the registered camera. `view-b.camera` starts as `null`, and the page displays "Camera selection pending" without inventing a second image.

3. Edit `title`, `credit`, and each view's `title` and `camera` in the new JSON. The camera format is shown below. These values only illustrate the format; choose values for the actual scene:

   ```json
   {
     "position": [0, 2, -8],
     "direction": [0, 0, 1],
     "up": [0, 1, 0],
     "vertical_fov": 60
   }
   ```

   Calculate `direction` as the target point minus the camera position. `vertical_fov` is the vertical field of view in degrees. The two cameras must have different positions and clearly different subjects or orientations; changing only the FOV is insufficient. Automatic checks reject duplicate positions, directions parallel to up, and similar errors, but composition still needs visual review.

4. Check the new scene and make scout renders without affecting other scenes:

   ```powershell
   python -B runs/scene-gallery/render.py --check --scene $sceneId
   python -B runs/scene-gallery/render.py --scout --scene $sceneId
   ```

   The default scout render is 640×360 over 128 frames and uses the last frame. It writes only an undenoised PNG and records to `_scouts/<scene-id>/<view-id>/`. If the second camera is not ready, start with `--view "${sceneId}/view-a"`. Scout again after changing a view. Native configuration changes, including composition and lighting, invalidate the scout cache. Use `--force` to repeat the render.

5. After reviewing the scouts, render the selected views, update the page and check the results:

   ```powershell
   python -B runs/scene-gallery/render.py --render --scene $sceneId
   python -B runs/scene-gallery/render.py --html --verify
   ```

   Adding a scene requires no Python or HTML changes and no reruns of existing scenes. `--scene` selects a whole scene; `--view scene-id/view-id` selects a view. Both accept multiple arguments. Without selectors, all views with ready cameras are processed, skipping existing complete images that match the configuration.

## Changes, updates and completion status

- To change titles, credits or section order, run `--sync --html`; no render is needed.
- After changing cameras, exposure, lights, render parameters or resolution, run `--sync --html`. Affected views become `stale`, and the page displays "Configuration updated; render pending". The original PNGs stay on disk but are no longer presented as results from the new configuration.
- Once the new configuration is confirmed, replace that view using `--render --force --view scene-id/view-id`. Other views are retained.
- `camera: null` means camera selection is pending. A configured camera with no render is `pending`. By default, `--verify` requires every view to be complete. While planning new scenes, use `--html --verify --allow-pending` to check the completed portion; `stale` still fails verification.
- Misspelled parameters, unknown IDs and duplicate view IDs produce errors. After updates, run `--html --verify` to check PNG dimensions and hashes, shared-source and exposure metadata, native configuration hashes, page links and counts.

Optional fields for each view:

| Field | Purpose |
| --- | --- |
| `exposure_ev` | Display exposure; `null` uses the automatic exposure recorded with the result; both PNGs always match |
| `lighting_overrides` | Override existing lighting fields in the registered scene, such as `emissive_scale`; recorded in the actual configuration |
| `render_overrides` | Override defaults, such as `frames` and `averaged_tail_frames` |
| `indirect_mode` | `RESTIRPT` or `BRDF`; inherits the global setting by default |

The budget requires `frames >= 128` and `1 <= averaged_tail_frames <= frames` for compatibility with the motion/reset settings in the frozen definition. This gallery uses only static views. Change `definition_snapshot` only for a clear reason; it retains the original experiment's base settings so later scenes can use the same standard.

## Rendering and reproduction conventions

- Uses the existing RTXDI v3.1.0 `FullSamplePdf` build. The build fingerprint and selected scene assets are verified before rendering; renderer source code is unchanged.
- Defaults: 1920×1080, seed 1, ReSTIR DI + ReSTIR PT / ULTRA, 5 bounces, 384 frames with the final 32 averaged. PDF Similarity, native denoising and native AA are off.
- Existing exceptions are retained: Emerald Square uses BRDF indirect lighting and 128 / 32 frames; Zero-Day uses 512 / 64 frames and emissive scale 64. Its actual ID is `zero-day-measure-one`.
- `raw.png` is the undenoised finite-frame average with the recorded exposure and ACES fitted / sRGB display transform. ReSTIR history makes these samples correlated, so the frame count is not an independent spp count.
- `processed.png` applies OIDN RT / HDR / HIGH, CUDA, color-only denoising to **the same linear RGB buffer in memory**, followed by the same exposure and display transform. The installed version is OIDN 2.5.
- HDR, PFM and native floating-point images are not retained. Per-frame input hashes, averaged-result hashes and processing records are stored beside each image pair. Temporary floating-point files are removed after success. Failed renders retain diagnostics in `_work/`; inspect them before cleaning up the failed view to avoid overwriting unreviewed results.

Requirements: the same repository and scene assets, verified renderer and shaders, Python 3.11 + NumPy / Pillow, and a CUDA-compatible OIDN 2.x installation. Update `oidn_library` in `gallery.json` if its installation path changes. Use `--oidn-smoke` to test the library separately. The [OIDN C API](https://github.com/RenderKit/oidn/blob/master/include/OpenImageDenoise/oidn.h) is licensed under Apache-2.0; this gallery does not distribute its binaries.

`manifest.json` summarizes the currently requested configuration and output status. `config.json` and `render-record.json` retain the configuration and hashes for each actual output. The original gallery's reproduction summary remains in `initial_publication_reproduction`; restructuring does not rewrite historical images or render records. Hardware, driver or renderer changes may cause pixel differences.

These images show how the configured scenes look. They do not establish that material import is fully validated or that reference convergence criteria have been met. The repository's `THIRD_PARTY.md` is authoritative for asset licenses and attribution.

## Code maintenance and verification

Add scenes through the configuration workflow. Edit `gallery_tools/page.html` / `site.py` for layout changes, `catalog.py` for scene configuration rules, and `render.py` for capture and processing changes. Generated records are not manually maintained source files.

```powershell
python -B -m unittest discover -s runs/scene-gallery/tests -v
python -B runs/scene-gallery/render.py --sync --html --verify
python -B scripts/check_scaffold.py
```

Tests cover new-scene discovery, reuse of existing results, invalidation after configuration changes, invalid configurations, dynamic pages and complete paired PNG export using a mocked renderer/OIDN. They do not launch GPU rendering. `--sync`, `--html`, `--verify` and `--list-scenes` also leave the renderer idle.

This directory is inside `runs/`, which Git ignores by default. When moving or backing up the gallery, retain its configurations, helper code, images and records together with the HTML.

The HTML opens without a server. For a local HTTP preview, run `python -B -m http.server 8767 --bind 127.0.0.1` in this directory.
