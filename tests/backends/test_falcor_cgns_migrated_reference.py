"""The current campaign must consume migrated reference data safely."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.falcor import cgns_pt_six_view_smoke as six
from scripts.falcor import cgns_paper_campaign, cgns_temporal_campaign


class MigratedReferenceTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.history = self.root / "provenance/original/reference"
        self.history.mkdir(parents=True)
        self.key = ("bistro", "view-a")
        self.attempt = self.root / "bistro/view-a/reference/seeds/extension/attempt-01"
        self.attempt.mkdir(parents=True)
        self.seed = self.root / "bistro/view-a/reference/seeds/old/seed-01/attempt-01"
        self.seed.mkdir(parents=True)
        self.reference = self.root / "bistro/view-a/reference/reference-16384.exr"
        self.reference.write_bytes(b"reference image")
        self.seed_manifest = self.seed / "manifest.json"
        self.seed_manifest.write_bytes(b"old seed manifest")
        self.state = self.attempt / "scene-state.json"
        self.state.write_text(json.dumps({"state": "frozen"}), encoding="utf8")
        self.audit = self.attempt / "scene-audit.json"
        self.audit.write_text(json.dumps({"audit": "frozen"}), encoding="utf8")
        self.old = self.history / "old-manifest.json"
        self.old.write_bytes(b"frozen old index")
        self.baseline = self.history / "baseline.json"
        self.baseline.write_text(json.dumps({"views": [{
            "scene_id": self.key[0], "view_id": self.key[1], "adapted": True,
            "old_seeds": [{"index": 0, "manifest": "old absolute path",
                           "manifest_sha256": self.sha(self.seed_manifest)}]
        }]}), encoding="utf8")
        self.extension = self.history / "extension-manifest.json"
        self.extension.write_text(json.dumps({
            "status": "completed", "baseline_sha256": self.sha(self.baseline),
            "old_manifest_sha256": self.sha(self.old),
            "views": [{"scene_id": self.key[0], "view_id": self.key[1],
                       "status": "completed", "reference": "old/path.exr",
                       "reference_sha256": self.sha(self.reference),
                       "blocks": [{"attempt": "old/attempt",
                           "scene_state_sha256": self.sha(self.state),
                           "scene_audit_sha256": self.sha(self.audit)}]}]
        }), encoding="utf8")
        self.catalog = self.root / "manifest.json"
        self.write_catalog(self.reference.relative_to(self.root).as_posix())
        self.patchers = [
            patch.object(six, "REFERENCE", self.root),
            patch.object(six, "EXTENSION", self.root / "old-extension"),
            patch.object(six, "KEYS", {self.key}),
        ]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_catalog(self, path):
        self.catalog.write_text(json.dumps({
            "schema_version": 1, "kind": "falcor_pt_spatial_view_catalog",
            "views": [{"scene_id": self.key[0], "view_id": self.key[1],
                       "reference": {"path": path, "sha256": self.sha(self.reference)}}]
        }), encoding="utf8")

    def test_migrated_frozen_reference_preserves_history_checks_and_observations(self):
        entry = six.historical_frozen_views()[self.key]
        self.assertEqual(six.historical_reference_for_view(self.key), self.reference)
        self.assertEqual(six.old_seed_manifest(entry, 0), self.seed_manifest)
        self.assertEqual(six._reference_observations(self.key),
                         ({"state": "frozen"}, {"audit": "frozen"}))
        self.state.write_text('{"state":"tampered"}', encoding="utf8")
        with self.assertRaisesRegex(ValueError, "scene state hash"):
            six._reference_observations(self.key)
        self.old.write_bytes(b"tampered historical manifest")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            six.historical_frozen_views()

    def test_migrated_reference_path_cannot_escape_root(self):
        self.write_catalog("../outside.exr")
        with self.assertRaises(ValueError):
            six.historical_reference_for_view(self.key)

    def test_historical_baseline_can_be_verified_without_active_config(self):
        before = self.baseline.read_bytes()
        entry = six.historical_frozen_views()[self.key]
        self.assertTrue(entry['adapted'])
        self.assertEqual(self.baseline.read_bytes(), before)
        self.baseline.write_text('{}', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            six.historical_frozen_views()
