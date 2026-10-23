# Script maintenance implementation plan

> Execute locally in this side conversation. No subagents, commits, pushes, or changes to progress-report files. The user approved the audit recommendations and exclusions on 2026-10-24.

**Goal:** Retire obsolete utilities, preserve current rendering/evaluation behavior, and reduce duplicated orchestration and test setup.

**Architecture:** Keep existing command names as thin entry points; put reusable implementations beside related modules. Gallery code belongs in scripts/gallery and its tests in tests. Store the controlled experiment matrix as JSON while retaining identical resolved configurations.

**Tech Stack:** Python 3.11, unittest, PowerShell, CMake/MSVC, existing NumPy/Pillow/matplotlib.

**Spec:** User annotations on the script audit in this conversation. Progress generators and scripts/analysis/pdf_archive.py are excluded.

## Constraints and review focus
- Preserve unrelated working-tree and index changes. The checkout is main; do not commit.
- Snapshot exactly the five retired files into a named Git stash and verify byte equality before removal.
- Validate the resolved tmp root, reject linked descendants, and check for active users before deleting contents.
- Preserve scene settings, method seeds, reference policies, capture frames, and timing definitions.
- Keep legacy gallery render.py invocation working with a thin shim; preserve existing gallery data and source-hash records.
- Keep build restoration and failure recovery intact; publish variants only after verified restoration.
- Keep archive and report files untouched. Record checks in build/script-maintenance-20261024.

## Tasks
- [x] 1. Run the existing CPU suite as a baseline; inspect all existing work and protect unrelated changes.
- [x] 2. Create a verified Git stash for obsolete cleanup modules/tests and the unused FBX camera inspector; remove these five files. Recheck and clear disposable tmp contents.
- [x] 3. Move gallery implementation/templates into scripts/gallery and its tests into tests. Add --output-dir to separate code from saved data; retain the old command shim. Verify discovery, state preservation, and mocked rendering.
- [x] 4. Extract shared test fixtures for worker imports, equal-time data, and C++ compilation/function extraction. Consolidate viewer configuration tests; preserve assertions and native fixtures.
- [x] 5. Move controlled media export and retained-report validation out of the runner; keep a thin command entry point and a focused experiment implementation. Store fixed matrix in experiments/configs/pdf-controlled.json. Check all resolved configurations against the baseline and run controlled/reference/analysis tests.
- [x] 6. Share variant build transactions across external, experiment/reference, and PDF entry points. Verify failed compilation, failed restoration, shader validation, and publication ordering. Rebuild supported local variants if renderer is idle.
- [x] 7. Add portable CPU CI and explicit optional integration checks; update script/test/gallery documentation. Run full tests, structure checks, syntax checks, and a separate final diff review; report skips and build outcomes.

## Verification
Use fresh unittest results per affected component. New behavioral interfaces get failing tests before implementation; pure extraction reuses existing behavioral regressions. Full suite: python -B -m unittest discover -s tests -v. Structure: python -B scripts/check_scaffold.py. Keep full logs in the task work directory and show concise results.

## Verified outcome

417 unittest checks and both Blender fixtures passed locally; four variants rebuilt with original files restored byte-for-byte. The declared campaign matches all 288 saved configuration fingerprints. See `build/script-maintenance-20261024/README.md` for logs and per-file recovery from the verified stash. The GitHub workflows have not been dispatched.

## Follow-up review

Fixed test-group filtering that could hide discovery/import errors. Three regression tests cover failure, listing and skipped dependencies. The fresh full suite passed 420 tests with no skips, and an isolated source copy without local render outputs passed 406 CPU tests. Structure, diff formatting, current build fingerprints and gallery evidence checks passed. See `build/script-maintenance-20261024/review-verification.json` and `commit-plan.md`. No commits were created; hosted CI and new GPU rendering were not run.
