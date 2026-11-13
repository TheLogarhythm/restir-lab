"""Reusable camera/scene records and reference integrand binding."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.falcor import reference_catalog


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReusableSceneInputsTest(unittest.TestCase):
    def fixture(self, root):
        from scripts.falcor import scene_inputs

        inventory = root / "inventory.json"
        inventory.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "falcor_scene_inventory",
                    "resources": [{"path": "model.bin", "sha256": "a" * 64}],
                    "sources": [{"path": "scene.pyscene", "sha256": "b" * 64}],
                }
            )
        )
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "falcor_scene_profile",
                    "scene_id": "bistro",
                    "profile_id": "bistro-interior",
                    "adapted": True,
                    "inventory": "inventory.json",
                    "scene_source": "scene.pyscene",
                    "ready_for_reference": True,
                    "runtime_receipt_sha256": "c" * 64,
                }
            )
        )
        view = root / "view.json"
        view.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "scene_id": "bistro",
                    "view_id": "view-a",
                    "scene_profile": "profile.json",
                    "camera": {
                        "position": [0, 0, 0],
                        "direction": [0, 0, 1],
                        "up": [0, 1, 0],
                        "vertical_fov": 60,
                    },
                }
            )
        )
        return scene_inputs, view, profile, inventory

    def test_profile_is_reused_with_independent_cameras_and_transitive_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module, view, profile, inventory = self.fixture(root)
            first, inputs = module.load_view(view, root)
            self.assertEqual(
                set(inputs), {"view.json", "profile.json", "inventory.json"}
            )
            self.assertEqual(
                first["resources"], [{"path": "model.bin", "sha256": "a" * 64}]
            )
            other = root / "other.json"
            data = json.loads(view.read_text())
            data["view_id"] = "view-b"
            data["camera"]["position"][0] = 3
            other.write_text(json.dumps(data))
            second, _ = module.load_view(other, root)
            self.assertEqual(first["resources"], second["resources"])
            self.assertNotEqual(first["camera"], second["camera"])
            first["resources"][0]["path"] = "changed"
            self.assertEqual(
                module.load_view(view, root)[0]["resources"][0]["path"], "model.bin"
            )

    def test_rejects_path_escape_and_conflicting_inventory_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module, view, profile, inventory = self.fixture(root)
            data = json.loads(profile.read_text())
            data["inventory"] = "../outside.json"
            profile.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                module.load_view(view, root)
            with self.assertRaises(ValueError):
                module.inventory_map(
                    [
                        {"path": "x", "sha256": "a" * 64},
                        {"path": "x", "sha256": "b" * 64},
                    ]
                )

    def test_reference_binding_rejects_camera_scene_runtime_and_transport_changes(self):
        config = {
            "scene_source": "scene.pyscene",
            "camera": {
                "position": [0, 0, 0],
                "direction": [0, 0, 1],
                "up": [0, 1, 0],
                "vertical_fov": 60,
            },
        }
        entry = {
            "adapted": True,
            "asset_sha256": {"a.bin": "a" * 64},
            "source_sha256": {"scene.pyscene": "b" * 64},
            "runtime_receipt_sha256": "c" * 64,
        }
        experiment = {
            "render": {"width": 1920, "height": 1080},
            "graph": {
                "maxSurfaceBounces": 10,
                "maxDiffuseBounces": 10,
                "maxSpecularBounces": 10,
                "maxTransmissionBounces": 10,
                "useRussianRoulette": True,
                "useRTXDI": False,
            },
        }
        binding = reference_catalog.binding_for_view(config, entry, experiment)
        record = {"binding": binding}
        reference_catalog.validate_binding(record, config, entry, experiment)
        variants = []
        camera = copy.deepcopy(config)
        camera["camera"]["position"][0] = 1
        variants.append((camera, entry, experiment))
        scene = {**config, "scene_source": "other.pyscene"}
        variants.append((scene, entry, experiment))
        runtime = {**entry, "runtime_receipt_sha256": "d" * 64}
        variants.append((config, runtime, experiment))
        transport = copy.deepcopy(experiment)
        transport["graph"]["maxSurfaceBounces"] = 9
        variants.append((config, entry, transport))
        assets = {**entry, "asset_sha256": {"a.bin": "e" * 64}}
        variants.append((config, assets, experiment))
        for args in variants:
            with self.assertRaises(ValueError):
                reference_catalog.validate_binding(record, *args)
        with self.assertRaises(ValueError):
            reference_catalog.validate_binding({}, config, entry, experiment)
        reuse = copy.deepcopy(experiment)
        reuse["graph"]["reSTIRPathTracingOptions"] = {"spatialGatherRadius": 99}
        reference_catalog.validate_binding(record, config, entry, reuse)

    def test_legacy_config_alias_resolves_same_active_scene_and_camera(self):
        from scripts.falcor import cgns_pt_six_view_smoke as six

        for entry in six.frozen_views().values():
            active = six.load_config(entry["config_path"])
            legacy = (
                six.ROOT
                / "experiments/configs/falcor-pt-spatial-comparison"
                / (Path(entry["config_path"]).stem + "-reference.json")
            )
            self.assertEqual(six.load_config(legacy), active)

    def test_standard_batch_accepts_five_composed_native_views(self):
        from scripts.falcor import reference_batch as batch
        from scripts.falcor import cgns_pt_six_view_smoke as six

        entries = six.frozen_views()
        paths = [
            Path(row["config_path"]) for row in entries.values() if not row["adapted"]
        ]
        self.assertEqual(len(batch.validate_configs(paths)), 5)
        for path in paths:
            config, inputs = batch.load_config_snapshot(path)
            self.assertTrue(config["ready_for_reference"])
            self.assertEqual(len(inputs), 3)
            from unittest.mock import patch

            with patch("scripts.falcor.scene_inputs.verify_profile_inventory"):
                self.assertTrue(batch.config_inputs_unchanged(path, config, inputs))
            config["camera"]["position"][0] += 1
            self.assertFalse(batch.config_inputs_unchanged(path, config, inputs))

    def test_adapted_batch_expands_shared_profile_and_detects_changed_camera(self):
        from scripts.falcor import adapted_reference_batch as batch
        from scripts.falcor import cgns_pt_six_view_smoke as six

        path = Path(six.frozen_views()[("bistro", "view-a")]["config_path"])
        rows = batch._configs([path])
        self.assertTrue(rows[0]["config"]["ready_for_reference"])
        self.assertIn("config_input_sha256", rows[0])
        from unittest.mock import patch

        with patch("scripts.falcor.scene_inputs.verify_profile_inventory"):
            self.assertTrue(batch._row_unchanged(rows[0]))
        rows[0]["config"]["camera"]["position"][0] += 1
        self.assertFalse(batch._row_unchanged(rows[0]))

    def test_asset_preflight_accepts_native_empty_source_inventory(self):
        import contextlib
        import io
        from unittest.mock import patch
        from scripts.falcor import scene_inputs, cgns_pt_six_view_smoke as six
        from scripts.falcor import adapted_reference_runner as adapted, reference_runner

        entry = {
            "adapted": False,
            "asset_sha256": {},
            "source_sha256": {},
            "config_path": "native.json",
        }
        with (
            patch("sys.argv", ["scene_inputs", "--check-assets"]),
            patch.object(
                six, "frozen_views", return_value={("classroom", "view-a"): entry}
            ),
            patch.object(six, "load_config", return_value={"sources": []}),
            patch.object(six, "validate_reference_for_view"),
            patch.object(reference_runner, "asset_inventory", return_value={}),
            patch.object(
                adapted,
                "inventory_resources",
                side_effect=AssertionError("empty inventory"),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            scene_inputs.main()

    def test_checked_in_profiles_remove_duplicate_bistro_records_and_qualify_shared_scene(
        self,
    ):
        from scripts.falcor import cgns_pt_six_view_smoke as six

        entries = six.frozen_views()
        config = six.load_config(entries[("bistro", "view-a")]["config_path"])
        self.assertIn(
            "/views/", entries[("bistro", "view-a")]["config_path"].replace("\\", "/")
        )
        self.assertTrue(config["ready_for_reference"])
        self.assertEqual(
            len(config["resources"]), len({x["path"] for x in config["resources"]})
        )
        self.assertEqual(
            len(config["sources"]), len({x["path"] for x in config["sources"]})
        )
        for key, entry in entries.items():
            six.validate_reference_for_view(
                key, config=six.load_config(entry["config_path"]), entry=entry
            )


if __name__ == "__main__":
    unittest.main()
