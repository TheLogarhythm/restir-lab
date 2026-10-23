"""Pilot release gates and receiver-light influence validation."""
import numpy as np
from .error_metrics import luminance
from .images import read_pfm


def validate_pilot_gate(receipt, build, matrix_hash, reference_build):
    if (receipt.get("passed") is not True or receipt.get("matrix_sha256") != matrix_hash
            or receipt.get("build") != build or receipt.get("validation_version") != 2
            or receipt.get("reference_build") != reference_build
            or receipt.get("lighting_influence", {}).get("passed") is not True):
        raise ValueError("Quantitative reports require a passed reference pilot for this build and matrix")


def validate_technical_gate(receipt, build, matrix_hash):
    if (receipt.get("technical_passed") is not True or receipt.get("validation_version") != 1
            or receipt.get("kind") != "technical_only" or receipt.get("build") != build
            or receipt.get("matrix_sha256") != matrix_hash
            or receipt.get("references_accepted") is not False):
        raise ValueError("Method renders require a passed technical pilot for this build and matrix")


def lighting_influence(base, peak, rois, *, load_image=read_pfm):
    """Require positive receiver illumination above measured reference variation."""
    values = []
    for record in (base, peak):
        values.append({"mean": luminance(load_image(record["image"])),
            "previous": luminance(load_image(record["previous_image"])),
            "a": luminance(load_image(record["streams"][0])),
            "b": luminance(load_image(record["streams"][1]))})
    rows = {}
    for roi in rois:
        x, y, width, height = (roi[k] for k in ("x", "y", "width", "height"))
        mask = (slice(y, y + height), slice(x, x + width))
        before, after = values
        signal = float(np.mean(after["mean"][mask] - before["mean"][mask]))
        noise = sum(float(np.mean(np.abs(v["a"][mask] - v["b"][mask]))) * .5 for v in values)
        drift = sum(float(np.mean(np.abs(v["mean"][mask] - v["previous"][mask]))) for v in values)
        threshold = 3 * max(noise, drift, 1e-12)
        rows[roi["name"]] = {"luminance_increase": signal, "half_stream_uncertainty": noise,
            "checkpoint_change": drift, "threshold": threshold, "passed": signal > threshold}
    return {"passed": any(row["passed"] for row in rows.values()), "receivers": rows}
