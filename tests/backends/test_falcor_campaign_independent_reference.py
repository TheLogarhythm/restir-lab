import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.falcor import spatial_campaign as campaign, spatial_experiment_config


class CampaignIndependentReferenceTest(unittest.TestCase):
    def test_catalog_metadata_does_not_require_reference_exr(self):
        for module in (campaign,):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = root / "scene.json"
                config.write_text("{}")
                ref = root / "reference.json"
                ref.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "name": "test",
                            "path_base": "repository_root",
                            "resolution": [1920, 1080],
                            "samples_per_pixel": 16384,
                            "views": [
                                {
                                    "scene_id": "classroom",
                                    "view_id": "view-a",
                                    "path": "assets/ref.exr",
                                    "sha256": "a" * 64,
                                }
                            ],
                        }
                    )
                )
                experiment = spatial_experiment_config.load_config()
                experiment["reference_catalog"] = "reference.json"
                entry = {
                    "config_path": str(config),
                    "config_sha256": module.run.sha(config),
                    "adapted": False,
                }
                with (
                    patch.object(module.reference_sets, "validate_binding"),
                    patch.object(module, "ROOT", root),
                    patch.object(
                        module.six, "frozen_views", return_value={("classroom", "view-a"): entry}
                    ),
                    patch.object(module.six, "load_config", return_value={}),
                    patch.object(
                        module.run, "inspect_hdr", side_effect=AssertionError("should not read EXR")
                    ),
                ):
                    catalog = module._reference_catalog(experiment)
                self.assertEqual(catalog[("classroom", "view-a")]["reference"]["sha256"], "a" * 64)
                self.assertEqual(
                    Path(catalog[("classroom", "view-a")]["reference"]["path"]),
                    root / "assets/ref.exr",
                )

    def test_analysis_rejects_missing_or_modified_reference(self):
        import hashlib

        for module in (campaign,):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = root / "scene.json"
                config.write_text("{}")
                image = root / "assets/ref.exr"
                ref = root / "reference.json"
                ref.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "name": "test",
                            "path_base": "repository_root",
                            "resolution": [1920, 1080],
                            "samples_per_pixel": 16384,
                            "views": [
                                {
                                    "scene_id": "classroom",
                                    "view_id": "view-a",
                                    "path": "assets/ref.exr",
                                    "sha256": hashlib.sha256(b"correct").hexdigest(),
                                }
                            ],
                        }
                    )
                )
                experiment = spatial_experiment_config.load_config()
                experiment["reference_catalog"] = "reference.json"
                entry = {
                    "config_path": str(config),
                    "config_sha256": module.run.sha(config),
                    "adapted": False,
                }
                with (
                    patch.object(module.reference_sets, "validate_binding"),
                    patch.object(module, "ROOT", root),
                    patch.object(
                        module.six, "frozen_views", return_value={("classroom", "view-a"): entry}
                    ),
                    patch.object(module.six, "load_config", return_value={}),
                    patch.object(module.run, "inspect_hdr"),
                ):
                    with self.assertRaises(FileNotFoundError):
                        module._reference_catalog(experiment, require_images=True)
                    image.parent.mkdir()
                    image.write_bytes(b"wrong")
                    with self.assertRaises(ValueError):
                        module._reference_catalog(experiment, require_images=True)
                    image.write_bytes(b"correct")
                    self.assertEqual(
                        len(module._reference_catalog(experiment, require_images=True)), 1
                    )

    def test_experiment_requires_relative_catalog(self):
        experiment = spatial_experiment_config.load_config()
        experiment["reference_catalog"] = "experiments/references/another-set.json"
        self.assertEqual(
            spatial_experiment_config.validate_config(experiment)["reference_catalog"],
            experiment["reference_catalog"],
        )
        experiment["reference_catalog"] = "../outside.json"
        with self.assertRaises(ValueError):
            spatial_experiment_config.validate_config(experiment)

    def six_view_fixture(self, root):
        from contextlib import ExitStack
        import hashlib
        import numpy as np
        import OpenEXR

        experiment = spatial_experiment_config.load_config()
        experiment["reference_catalog"] = "reference.json"
        keys = sorted(campaign.six.KEYS)
        entries, configs, images, records = {}, {}, {}, []
        for index, key in enumerate(keys):
            config_path = root / f"scene-{index}.json"
            config = {
                "scene_id": key[0],
                "view_id": key[1],
                "scene_source": f"scenes/source-{index}.pyscene",
                "camera": {
                    "position": [index, 0, 0],
                    "direction": [0, 0, 1],
                    "up": [0, 1, 0],
                    "vertical_fov": 45,
                },
            }
            config_path.write_text(json.dumps(config))
            entry = {
                "config_path": str(config_path),
                "config_sha256": campaign.run.sha(config_path),
                "adapted": key == ("bistro", "view-a"),
                "asset_sha256": {f"source-{index}": "b" * 64},
                "source_sha256": {},
                "runtime_receipt_sha256": str(index + 1) * 64,
            }
            entries[key], configs[config_path] = entry, config
            image = root / f"reference-{index}.exr"
            images[key] = image
            records.append(
                {
                    "scene_id": key[0],
                    "view_id": key[1],
                    "path": image.name,
                    "sha256": "a" * 64,
                    "binding": campaign.reference_sets.binding_for_view(config, entry, experiment),
                }
            )
        # Real full-resolution FLOAT32 EXRs; the four unselected images remain absent.
        pixels = np.ones((1080, 1920, 3), dtype=np.float32)
        OpenEXR.File({}, {"RGB": pixels}).write(str(images[keys[0]]))
        images[keys[1]].write_bytes(images[keys[0]].read_bytes())
        for record in records[:2]:
            record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
        reference = root / "reference.json"
        reference.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "name": "six-view-test",
                    "path_base": "repository_root",
                    "resolution": [1920, 1080],
                    "samples_per_pixel": 16384,
                    "views": records,
                }
            )
        )
        lock = root / "lock.json"
        lock.write_text("frozen six-view metadata")
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(campaign, "ROOT", root))
        stack.enter_context(patch.object(campaign.six, "frozen_views", return_value=entries))
        stack.enter_context(
            patch.object(
                campaign.six,
                "load_config",
                side_effect=lambda path: json.loads(Path(path).read_text()),
            )
        )
        stack.enter_context(patch.object(campaign.six, "scene_manifest_path", return_value=lock))
        stack.enter_context(
            patch.object(campaign.six, "reference_catalog_path", return_value=reference)
        )
        stack.enter_context(
            patch.object(campaign, "_code_identity", return_value={"code": "constant"})
        )
        return experiment, keys, entries, images, records, reference

    def test_selected_image_validation_reads_only_selected_exr_and_locks_all_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            experiment, keys, entries, images, records, reference = self.six_view_fixture(root)
            identities = []
            for selected in keys[:2]:
                with patch.object(
                    campaign.run, "inspect_hdr", wraps=campaign.run.inspect_hdr
                ) as inspect:
                    catalog = campaign._reference_catalog(
                        experiment, require_images=True, image_views={selected}
                    )
                    self.assertEqual(len(catalog), 6)
                    inspect.assert_called_once_with(images[selected], 1920, 1080)
                selected_catalog = campaign._select_catalog(catalog, True, "/".join(selected))
                adapted = entries[selected]["adapted"]
                identity = campaign._identity(
                    selected_catalog,
                    {("baseline", adapted): {"id": selected[1]}},
                    "commit",
                    experiment=experiment,
                    experiment_path=root / "experiment.json",
                    experiment_sha256="c" * 64,
                    runtime_paths={
                        ("baseline", adapted): root / ("adapted" if adapted else "baseline")
                    },
                    temporal_contrast=True,
                )
                self.assertEqual(len(identity["views"]), 1)
                self.assertEqual(identity["views"][0]["view_id"], selected[1])
                self.assertEqual(
                    identity["views"][0]["reference"]["sha256"],
                    catalog[selected]["reference"]["sha256"],
                )
                self.assertEqual(
                    set(identity["runtimes"]),
                    {"baseline-gltf" if adapted else "baseline-reference"},
                )
                identities.append(campaign._identity_hash(identity))
            self.assertNotEqual(*identities)
            # Default image validation still requires every reference, including missing unselected EXRs.
            with self.assertRaises(FileNotFoundError):
                campaign._reference_catalog(experiment, require_images=True)
            # A damaged unselected image is also irrelevant to a single-view contrast.
            images[keys[2]].write_bytes(b"not an EXR")
            campaign._reference_catalog(experiment, require_images=True, image_views={keys[0]})
            with self.assertRaisesRegex(ValueError, "Reference image hash mismatch"):
                campaign._reference_catalog(experiment, require_images=True)
            # Once every image is present, default validation decodes all six real EXRs.
            payload = json.loads(reference.read_text())
            for key in keys[2:]:
                images[key].write_bytes(images[keys[0]].read_bytes())
            for record in payload["views"]:
                record["sha256"] = campaign.run.sha(root / record["path"])
            reference.write_text(json.dumps(payload))
            with patch.object(
                campaign.run, "inspect_hdr", wraps=campaign.run.inspect_hdr
            ) as inspect:
                self.assertEqual(
                    len(campaign._reference_catalog(experiment, require_images=True)), 6
                )
                self.assertEqual(inspect.call_count, 6)
                self.assertEqual(
                    {call.args[0] for call in inspect.call_args_list}, set(images.values())
                )
            # An unselected metadata input is still frozen and must not silently change.
            Path(entries[keys[-1]]["config_path"]).write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "Scene config hash differs"):
                campaign._reference_catalog(experiment, require_images=True, image_views={keys[0]})

    def test_selected_image_hash_and_dimensions_are_really_validated(self):
        import numpy as np
        import OpenEXR

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            experiment, keys, entries, images, records, reference = self.six_view_fixture(root)
            selected = keys[0]
            images[selected].write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Reference image hash mismatch"):
                campaign._reference_catalog(experiment, require_images=True, image_views={selected})
            OpenEXR.File({}, {"RGB": np.ones((2, 3, 3), dtype=np.float32)}).write(
                str(images[selected])
            )
            payload = json.loads(reference.read_text())
            payload["views"][0]["sha256"] = campaign.run.sha(images[selected])
            reference.write_text(json.dumps(payload))
            with patch.object(
                campaign.run, "inspect_hdr", wraps=campaign.run.inspect_hdr
            ) as inspect:
                with self.assertRaises(ValueError):
                    campaign._reference_catalog(
                        experiment, require_images=True, image_views={selected}
                    )
                inspect.assert_called_once_with(images[selected], 1920, 1080)
