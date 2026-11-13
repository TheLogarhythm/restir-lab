"""Schema-2 reference input pins, routing and legacy entry-point regressions."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.falcor import scene_inputs
from scripts.falcor import reference_runner as native
from scripts.falcor import reference_batch as native_batch
from scripts.falcor import adapted_reference_runner as adapted
from scripts.falcor import adapted_reference_batch as adapted_batch

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf8")


class ReferenceProfileGuards(unittest.TestCase):
    def fixture(self, root, *, adapted=False):
        bundle = root / "bundle"
        bundle.mkdir()
        for name in ("scene.pyscene", "model.bin", "texture.dds"):
            (bundle / name).write_bytes(name.encode())
        helper = root / "helper.py"
        helper.write_text("original")
        resources = [
            {"path": p.relative_to(root).as_posix(), "sha256": sha(p)}
            for p in sorted(bundle.iterdir())
        ]
        sources = [{"path": "helper.py", "sha256": sha(helper)}]
        if adapted:
            sources.append(
                {
                    "path": "bundle/scene.pyscene",
                    "sha256": sha(bundle / "scene.pyscene"),
                }
            )
        inventory = root / "inventory.json"
        save(
            inventory,
            {
                "schema_version": 1,
                "kind": "falcor_scene_inventory",
                "resources": resources,
                "sources": sources,
            },
        )
        profile = root / "profile.json"
        data = {
            "schema_version": 1,
            "kind": "falcor_scene_profile",
            "profile_id": "fixture",
            "scene_id": "classroom",
            "adapted": adapted,
            "inventory": "inventory.json",
            "scene_source": "bundle/scene.pyscene",
            "asset_roots": ["bundle"],
            "ready_for_reference": True,
        }
        if adapted:
            data["runtime_receipt_sha256"] = "f" * 64
        save(profile, data)
        view = root / "view.json"
        save(
            view,
            {
                "schema_version": 2,
                "scene_id": "classroom",
                "view_id": "view-a",
                "scene_profile": "profile.json",
                "camera": {
                    "position": [0, 0, 0],
                    "direction": [0, 0, 1],
                    "up": [0, 1, 0],
                    "vertical_fov": 60,
                },
            },
        )
        config, inputs = scene_inputs.load_view(view, root)
        return view, profile, inventory, config, inputs

    def test_native_pins_assets_sources_and_scene_closure_without_fixed_exrs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            view, profile, inventory, config, _ = self.fixture(root)
            assets, sources = scene_inputs.verify_profile_inventory(
                config, root, adapted=False
            )
            self.assertEqual(assets, native.asset_inventory(config, root))
            self.assertEqual(sources, {"helper.py": sha(root / "helper.py")})
            camera = json.loads(view.read_text())
            camera["camera"]["position"][0] = 9
            save(view, camera)
            changed, _ = scene_inputs.load_view(view, root)
            scene_inputs.verify_profile_inventory(changed, root, adapted=False)
            self.assertFalse((root / "assets/references").exists())
            (root / "bundle/texture.dds").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "inventory"):
                scene_inputs.verify_profile_inventory(config, root, adapted=False)

    def test_native_source_changes_extra_assets_and_unsafe_paths_are_rejected(self):
        for change in ("source", "extra", "escape"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                _, _, _, config, _ = self.fixture(root)
                if change == "source":
                    (root / "helper.py").write_text("changed")
                elif change == "extra":
                    (root / "bundle/extra.bin").write_bytes(b"extra")
                else:
                    config["resources"][0]["path"] = "../outside.bin"
                with self.assertRaises(ValueError):
                    scene_inputs.verify_profile_inventory(config, root, adapted=False)

    def test_schema2_lock_and_profile_cannot_disagree_about_adapter_or_runtime(self):
        for change in ("adapted", "receipt", "runtime"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                view, profile, inventory, config, inputs = self.fixture(
                    root, adapted=True
                )
                entry = {
                    "scene_id": "classroom",
                    "view_id": "view-a",
                    "adapted": True,
                    "config_path": "view.json",
                    "config_sha256": sha(view),
                    "input_sha256": inputs,
                    "graph_sha256": "e" * 64,
                    "runtime_receipt_sha256": "f" * 64,
                }
                if change == "adapted":
                    entry["adapted"] = False
                elif change == "receipt":
                    entry["runtime_receipt_sha256"] = "a" * 64
                else:
                    data = json.loads(profile.read_text())
                    data["reference_runtime"] = "reference"
                    save(profile, data)
                    entry["input_sha256"]["profile.json"] = sha(profile)
                manifest = root / "lock.json"
                save(
                    manifest,
                    {
                        "schema_version": 2,
                        "kind": "falcor_scene_inputs",
                        "path_base": "workspace",
                        "views": [entry],
                    },
                )
                with self.assertRaisesRegex(ValueError, "[Aa]dapt|[Rr]untime"):
                    scene_inputs.load_locked_views(
                        manifest, root, {("classroom", "view-a")}
                    )

    def test_native_launch_rejects_modified_pin_before_build_or_renderer(self):
        from scripts.falcor import build

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            view, _, _, _, _ = self.fixture(root)
            (root / "bundle/texture.dds").write_bytes(b"changed")
            original = native.asset_inventory
            with patch.object(native, "ROOT", root), patch.object(
                native,
                "asset_inventory",
                side_effect=lambda c, *args: original(c, root),
            ), patch.object(native, "check_renderer_idle"), patch.object(
                build, "verify_build", side_effect=AssertionError("build reached")
            ), patch.object(
                native.run, "execute"
            ) as execute:
                with self.assertRaisesRegex(ValueError, "inventory"):
                    native.launch(view, root / "output", 0, 1, 16, 9, 30, scout=True)
                execute.assert_not_called()
                self.assertFalse((root / "output").exists())

    def test_native_postflight_rejects_texture_mutation_without_publishing_success(
        self,
    ):
        from scripts.falcor import build, reference_runtime
        from contextlib import nullcontext
        import numpy as np

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            view, _, _, _, _ = self.fixture(root)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "receipt.json").write_text("{}")
            receipt = {
                key: key
                for key in (
                    "patch_file",
                    "original_sha256",
                    "patched_sha256",
                    "old",
                    "new",
                )
            }

            def execute(command, output, timeout, *, prepare, verify, metadata):
                output.mkdir()
                (output / "resolved-camera.json").write_text("{}")
                (output / "capture.AccumulatePass.output.1.exr").write_bytes(b"fixture")
                (root / "bundle/texture.dds").write_bytes(b"changed during rendering")
                verify(output)
                self.fail("Changed pinned texture was accepted after rendering")

            with patch.object(native, "ROOT", root), patch.object(
                native, "exclusive_operation", return_value=nullcontext()
            ), patch.object(native, "check_renderer_idle"), patch.object(
                build, "verify_build", return_value={"executable": "Mogwai.exe"}
            ), patch.object(
                reference_runtime, "DEST", runtime
            ), patch.object(
                reference_runtime, "verify", return_value=receipt
            ), patch.object(
                native.subprocess, "check_output", return_value="fixture GPU"
            ), patch.object(
                native, "validate_camera_records"
            ), patch.object(
                native.run, "inspect_hdr", return_value=np.ones((9, 16, 3))
            ), patch.object(
                native.run, "execute", side_effect=execute
            ):
                with self.assertRaisesRegex(ValueError, "inventory"):
                    native.launch(view, root / "out", 0, 1, 16, 9, 30, scout=True)

    def test_native_batch_and_resume_reject_pin_changes_without_launch(self):
        for resume in (False, True):
            with self.subTest(resume=resume), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                view, _, _, config, inputs = self.fixture(root)
                (root / "bundle/texture.dds").write_bytes(b"changed")
                with patch.object(native_batch, "ROOT", root), patch.object(
                    native_batch,
                    "current_provenance",
                    side_effect=AssertionError("provenance reached"),
                ), patch.object(native_batch.reference_runner, "launch") as launch:
                    self.assertFalse(
                        native_batch.config_inputs_unchanged(view, config, inputs)
                    )
                    with self.assertRaisesRegex(ValueError, "inventory"):
                        native_batch._run_batch([view], root / "out", resume=resume)
                    launch.assert_not_called()
                    self.assertFalse((root / "out").exists())

    def test_adapted_resume_rechecks_pins_and_legacy_rows_remain_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            view, _, _, config, inputs = self.fixture(root, adapted=True)
            row = {
                "path": str(view),
                "sha256": sha(view),
                "config": config,
                "config_input_sha256": inputs,
            }
            with patch.object(adapted_batch, "ROOT", root):
                self.assertTrue(adapted_batch._row_unchanged(row))
                (root / "bundle/texture.dds").write_bytes(b"changed")
                self.assertFalse(adapted_batch._row_unchanged(row))
            legacy = root / "legacy.json"
            save(legacy, {"schema_version": 1, "scene_id": "classroom"})
            with patch.object(native_batch, "ROOT", root):
                legacy_config, legacy_inputs = native_batch.load_config_snapshot(legacy)
                self.assertIsNone(legacy_inputs)
                self.assertTrue(
                    native_batch.config_inputs_unchanged(
                        legacy, legacy_config, legacy_inputs
                    )
                )

    def test_runner_routes_reject_opposite_profile_without_rendering(self):
        from scripts.falcor import build

        for want_adapted in (False, True):
            with self.subTest(
                want_adapted=want_adapted
            ), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                view, _, _, _, _ = self.fixture(root, adapted=not want_adapted)
                with patch.object(native, "ROOT", root), patch.object(
                    build, "verify_build", side_effect=AssertionError("build reached")
                ), patch.object(native, "check_renderer_idle"), patch.object(
                    native.run, "execute"
                ) as execute:
                    with self.assertRaisesRegex(ValueError, "[Aa]dapt|[Rr]untime"):
                        (adapted if want_adapted else native).launch(
                            view, root / "out", 0, 1, 16, 9, 30, scout=True
                        )
                    execute.assert_not_called()

    def test_module_and_direct_script_entrypoints_reach_budget_guards(self):
        config = ROOT / "experiments/views/falcor-pt-spatial-comparison/classroom.json"
        for direct in (False, True):
            for module, guard in (
                ("reference_runner", "Scout is limited"),
                ("reference_batch", "Timeout must be positive"),
            ):
                with self.subTest(direct=direct, module=module):
                    command = [sys.executable, "-B"]
                    command += (
                        [str(ROOT / "scripts/falcor" / (module + ".py"))]
                        if direct
                        else ["-m", "scripts.falcor." + module]
                    )
                    command += ["--output", str(ROOT / "unreachable-test-output")]
                    if module == "reference_runner":
                        command += [
                            "--config",
                            str(config),
                            "--seed",
                            "0",
                            "--samples",
                            "257",
                            "--width",
                            "64",
                            "--height",
                            "36",
                            "--scout",
                        ]
                    else:
                        command += ["--configs", str(config), "--timeout", "-1"]
                    result = subprocess.run(
                        command, cwd=ROOT, capture_output=True, text=True
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(guard, result.stderr)
                    self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assertFalse((ROOT / "unreachable-test-output").exists())


if __name__ == "__main__":
    unittest.main()
