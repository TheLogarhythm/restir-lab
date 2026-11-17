"""Read selected captures from a compact PT archive without live renderer access.

This adapter checks metadata and selected inputs. It does not replace the complete
six-view inventory/reference/exclusion verifier in scripts/analysis/pt_stage_archive.py.
"""
from dataclasses import replace
from pathlib import Path

from records.provenance import sha256
from records.validation import artifact_path, integer, read_json, require_digest

METHODS = {"temporal-off": ("baseline", False), "temporal-on": ("baseline", True),
           "cgns": ("cgns", True), "pdf": ("pdf-similarity", True)}


class StageArchive:
    """A collection of captures, never a synthetic single RunRecord."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self._manifest, self.manifest_sha256 = read_json(artifact_path(self.directory, "manifest.json"))
        m = self._manifest
        if m.get("kind") == "falcor_pt_statistics_archive":
            raise ValueError("Statistics-only archive: full quality HDR was retired. Read statistics/ or use tools/replot.py; raw quality_runs() is unavailable.")
        if (m.get("schema_version") != 1 or m.get("kind") != "falcor_pt_stage_archive"
                or m.get("status") != "completed_compacted" or m.get("path_base") != "archive_root"):
            raise ValueError("Unsupported PT stage archive")
        self._files = {}
        for record in m["files"]:
            name = record["path"]
            # Validate portable containment even for inputs not selected for decoding.
            artifact_path(self.directory, name)
            if name in self._files:
                raise ValueError("Duplicate archive file: " + name)
            require_digest(record["sha256"])
            integer(record["bytes"], "file bytes", 0, 2**63 - 1)
            self._files[name] = record
        seeds = m["quality_seed_offsets"]
        if not isinstance(seeds, list) or not seeds or len(set(seeds)) != len(seeds):
            raise ValueError("Invalid archive seed coverage")
        for seed in seeds:
            integer(seed, "archive seed")
        if not isinstance(m["views"], dict) or not m["views"]:
            raise ValueError("Missing archive views")

    def _unchanged(self):
        if sha256(artifact_path(self.directory, "manifest.json")) != self.manifest_sha256:
            raise ValueError("Archive manifest changed since it was read")

    def _checked(self, name):
        path = artifact_path(self.directory, name)
        if name not in self._files:
            raise ValueError("Unindexed archive input: " + name)
        record = self._files[name]
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError("Archive input hash changed: " + name)
        return path

    def _json(self, name):
        path = self._checked(name)
        return read_json(path, self._files[name]["sha256"])[0]

    def _selected(self, view, method):
        self._unchanged()
        views = self._manifest["views"]
        if view is not None and view not in views:
            raise ValueError("Unknown archive view: " + str(view))
        found = False
        for view_id, entry in views.items():
            if view is not None and view_id != view:
                continue
            for label, data in entry["methods"].items():
                if label not in METHODS:
                    raise ValueError("Unknown archive method: " + label)
                if method is not None and label != method:
                    continue
                found = True
                yield view_id, label, entry, data
        if not found:
            raise ValueError("Unknown archive method: " + str(method))

    def quality_records(self, *, view=None, method=None, seeds=None):
        """Enumerate current paths and original IDs without decoding quality images."""
        selected = None if seeds is None else list(seeds)
        if selected is not None and (not selected or len(set(selected)) != len(selected)
                                    or any(type(s) is not int or s not in self._manifest["quality_seed_offsets"] for s in selected)):
            raise ValueError("Unknown or duplicate selected seed")
        result = []
        for name, label, entry, data in self._selected(view, method):
            seen = [q["seed_offset"] for q in data["quality"]]
            if seen != self._manifest["quality_seed_offsets"]:
                raise ValueError("Archive quality seed coverage differs")
            view_record = self._json(entry["view_config"])
            self._json(entry["reference"])
            for q in data["quality"]:
                if selected is not None and q["seed_offset"] not in selected:
                    continue
                directory = self._checked(q["directory"] + "/manifest.json").parent
                result.append(dict(q, view=name, method=label, directory=directory,
                                   view_record=view_record, view_config=entry["view_config"],
                                   reference=entry["reference"]))
        self._unchanged()
        return result

    def quality_runs(self, *, view=None, method=None, seeds=None):
        """Validate and decode selected quality captures into shared RunRecords."""
        from records import read_run
        result = []
        for entry in self.quality_records(view=view, method=method, seeds=seeds):
            run = read_run(entry["directory"], backend="falcor")
            meta, v = run.config, entry["view_record"]
            expected_method, temporal = METHODS[entry["method"]]
            if (run.seed != entry["seed_offset"] or meta["requested_method"] != expected_method
                    or meta["temporal_reuse"] is not temporal
                    or [f.index for f in run.frames] != self._manifest["quality_frames"]
                    or [run.width, run.height] != self._manifest["resolution"]
                    or (meta["scene_id"], meta["view_id"]) != (v["scene_id"], v["view_id"])
                    or meta["scene_config_sha256"] != v["config_sha256"]):
                raise ValueError("Archive selection and original capture identity differ")
            related = {"manifest.json": self.manifest_sha256}
            for name in [entry["view_config"], entry["reference"]]:
                related[name] = self._files[name]["sha256"]
            prefix = run.directory.relative_to(self.directory).as_posix() + "/"
            for name, digest in run.provenance["record_files"].items():
                self._checked(prefix + name)
                if self._files[prefix + name]["sha256"] != digest:
                    raise ValueError("Archive and capture record hashes differ")
            for frame in run.frames:
                name = frame.image.relative_to(self.directory).as_posix()
                if name not in self._files or self._files[name]["sha256"] != frame.sha256:
                    raise ValueError("Archive and original image hashes differ")
            provenance = dict(run.provenance, archive={
                "directory": str(self.directory), "record_files": related,
                "view": entry["view"], "method": entry["method"],
                "source_run_id": entry["source_run_id"]})
            result.append(replace(run, provenance=provenance))
        self._unchanged()
        return result

    def timing_records(self, *, view=None, method=None, included_only=False):
        """Validate timing-manifest selection; raw samples require the full verifier.

        This metadata API preserves the exclusion policy and does not decode or
        certify raw profiler samples or their derived statistics.
        """
        result = []
        for name, label, entry, data in self._selected(view, method):
            record = data["timing"]
            included, reason = record["included"], record["exclusion_reason"]
            if type(included) is not bool or (not included and (not isinstance(reason, str) or not reason.strip())):
                raise ValueError("Missing timing inclusion/exclusion reason")
            path = self._checked(record["directory"] + "/manifest.json")
            meta = self._json(record["directory"] + "/manifest.json")
            view_record = self._json(entry["view_config"])
            expected_method, temporal = METHODS[label]
            if (meta.get("status") != "completed" or meta.get("seed_offset", 0) != record["seed_offset"]
                    or meta.get("requested_method") != expected_method
                    or meta.get("temporal_reuse") is not temporal
                    or (meta.get("scene_id"), meta.get("view_id")) !=
                       (view_record["scene_id"], view_record["view_id"])):
                raise ValueError("Archive timing capture differs")
            if not included_only or included:
                result.append(dict(record, view=name, method=label, directory=path.parent, raw_timings_validated=False))
        self._unchanged()
        return result


def read_archive(directory):
    """Read archive metadata. Quality HDR is read only by quality_runs()."""
    try:
        return StageArchive(directory)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed PT archive: {exc}") from exc
