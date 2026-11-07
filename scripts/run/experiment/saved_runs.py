"""Validated capture and shared-geometry adapters for saved-run analyses."""
from pathlib import Path
import numpy as np
from rtxdi_common import sha
from .reference import suite_captures
from .geometry_io import read_geometry
from .pixel_regions import traditional_acceptance, rank_regions


def load_run(directory, measured):
    directory = Path(directory).resolve()
    captures = suite_captures(directory)
    if any(item["directory"].resolve() != directory for item in captures):
        raise ValueError("Each input path must name one run, not an entire suite")
    config, manifest = captures[0]["config"], captures[0]["manifest"]
    if type(config.get("seed")) is not int or not 0 <= config["seed"] <= 4095:
        raise ValueError("Invalid independent run seed")
    schedule = config["frames"]
    if any(type(f.get("sampling_frame")) is not int or not 0 <= f["sampling_frame"] < 2**32 for f in schedule):
        raise ValueError("RNG sampling_frame values must be uint32 integers")
    if (not schedule or schedule[0].get("reset") is not True
            or any(type(f["frame"]) is not int or type(f["reset"]) is not bool for f in schedule)
            or any(b["frame"] != a["frame"] + 1 for a,b in zip(schedule,schedule[1:]))):
        raise ValueError("Run control schedule needs a reset start and contiguous unique frame IDs")
    by_frame = {}
    for item in captures:
        index = item["frame"]["frame"]
        if index in by_frame:
            raise ValueError("Duplicate capture frame")
        by_frame[index] = item
    # suite_captures validates existing digests; require them here, not optional.
    saved = manifest.get("captures", [])
    if len({item["frame"] for item in saved}) != len(saved):
        raise ValueError("Duplicate captured-frame records")
    records = {item["frame"]: item for item in saved}
    if not measured or len(set(measured)) != len(measured) or any(type(f) is not int for f in measured):
        raise ValueError("Measured capture IDs must be nonempty unique integers")
    for index in measured:
        if index not in by_frame or not records.get(index, {}).get("image_sha256"):
            raise ValueError(f"Missing measured frame/hash {index}: {directory}")
    return {"config": config,
            "manifest": manifest, "directory": directory, "captures": by_frame, "records": records}


def geometry_target(target):
    # Light-only changes affect the radiance target, not geometric difficulty.
    fields = ("scene_id", "asset_sha256", "renderer_commit", "resolution",
              "camera", "vertical_fov", "surface_settings")
    return {field: target[field] for field in fields}


class SharedRegions:
    """One geometry source per physical frame; masks are cached on disk across methods."""
    def __init__(self, source, targets, output, radius, percent):
        self.source, self.targets, self.output = source, targets, output
        self.radius, self.percent = radius, percent
        self.records = {}
        self.static_frame = source.get("static_frame")
        if self.static_frame is not None and type(self.static_frame) is not int:
            raise ValueError("static_frame must be an integer")
        self.static_masks = None

    def __call__(self, frame):
        source_frame = self.static_frame if self.static_frame is not None else frame
        source = self.source["data"]
        if source_frame not in source["captures"]:
            raise ValueError(f"Missing geometry source frame {source_frame}")
        capture = source["captures"][source_frame]
        if geometry_target(capture["target"]) != self.targets[frame]:
            raise ValueError("Geometry source target/camera does not match measured frame")
        key = str(source_frame)
        if key in self.records:
            if self.static_masks is not None:
                return self.static_masks
            with np.load(self.output / self.records[key]["mask"], allow_pickle=False) as archive:
                return {name: archive[name] for name in ("hard", "easy", "valid")}
        record = source["records"].get(source_frame, {})
        if not record.get("geometry") or not record.get("geometry_sha256"):
            raise ValueError("Geometry capture/hash is missing; export it from a controlled run")
        path = source["directory"] / record["geometry"]
        if sha(path) != record["geometry_sha256"]:
            raise ValueError("Geometry capture was modified")
        geometry = read_geometry(path)
        expected = source["config"]
        if geometry["valid"].shape != (expected["height"], expected["width"]):
            raise ValueError("Geometry dimensions differ from source config")
        with np.load(path, allow_pickle=False) as archive:
            if float(archive["vertical_fov_degrees"]) != expected["scene"]["camera"]["vertical_fov"]:
                raise ValueError("Geometry FOV differs from source camera")
        rates = traditional_acceptance(**geometry, classification_radius=self.radius)
        masks = rank_regions(rates["acceptance"], rates["valid"], hard_percent=self.percent)
        folder = self.output / "regions"
        folder.mkdir(exist_ok=True)
        mask_path = folder / f"frame-{source_frame:04d}.npz"
        np.savez_compressed(mask_path, **masks, acceptance=rates["acceptance"],
                            accepted=rates["accepted"], candidates=rates["candidates"])
        self.records[key] = {
            "source": str(path), "source_sha256": record["geometry_sha256"],
            "target_key": capture["key"], "mask": mask_path.relative_to(self.output).as_posix(),
            "mask_sha256": sha(mask_path), "valid_pixels": int(masks["valid"].sum()),
            "hard_pixels": int(masks["hard"].sum()), "easy_pixels": int(masks["easy"].sum()),
            "candidate_pairs": int(rates["candidates"].sum()), "accepted_pairs": int(rates["accepted"].sum())}
        if self.static_frame is not None:
            self.static_masks = masks
        return masks

