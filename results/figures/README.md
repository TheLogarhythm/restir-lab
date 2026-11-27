# Figures

Store selected figures with captions and source run IDs. Record crops, exposure, tone mapping, error scales, and generation configs. Display images are not linear references.

## README media

- **Benchmark scenes.** The contact sheet uses the complete 16,384-spp display references from the saved six-view archive at `runs/pt-6-views-spatial-compare/images/<view>/reference.png`. It retains the archived exposure and display transform and resizes without cropping. [Contact sheet](benchmark-scenes.jpg) · [Scene credits](../../THIRD_PARTY.md#scene-assets-and-fonts)
- **Emerald Square error maps.** Both panels show the method's per-pixel SMAPE minus original reuse, averaged over four seeds and 16 frames per seed. The source arrays are `cgns_change_pp` and `pdf_change_pp` in `runs/pt-6-views-spatial-compare/data/emerald-square/arrays.npz`. The shared diverging color scale clips at ±20 percentage points. [Error maps](smape-improvement.png) · [Benchmark protocol](../../docs/reproductions/pt-6-views-spatial-compare.md)

The fixed-view panels come from the [six-view PT comparison](../../docs/reproductions/pt-6-views-spatial-compare.md). The three method crops use seed 0, frame 48, and the archived display transform. Both regions were selected to show an improvement. The reference previews preserve the full field of view, and the crops are enlarged with nearest-neighbor sampling.

| Panel | Source rectangle `(left, top, right, bottom)` at 1920 × 1080 |
| --- | --- |
| Emerald Square | `(1566, 574, 1694, 702)` |
| Bistro Interior | `(326, 524, 454, 652)` |

The Bistro Exterior and Zero Day clips derive from the synchronized course-v2 composites for the [four-trajectory PT comparison](../../scenes/trajectories/README.md). The README versions relabel the baseline column as “Ordinary spatial reuse” and encode the original 300 frames as 1280 × 720 H.264 at 30 FPS. Cover images are from 1.5 seconds into the clips. Scene credits are listed in [THIRD_PARTY.md](../../THIRD_PARTY.md).
