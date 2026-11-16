"""Independently replay Falcor's fixed point-PT proposal and check saved GPU pair weights."""
import argparse
import json
from pathlib import Path

import numpy as np

from .pdf_pt_validation_results import _read_exr


def offsets(radius):
    # createNeighborOffsetTexture(): float32 disk rejection, followed by RG8Snorm.
    phi = np.float32(1) / np.float32(1.3247179572447)
    u = v = np.float32(.5)
    result = []
    while len(result) < 8192:
        u += phi
        v += phi * phi
        if u >= 1:
            u -= np.float32(1)
        if v >= 1:
            v -= np.float32(1)
        x, y = u - np.float32(.5), v - np.float32(.5)
        if x*x + y*y <= .25:
            result.append((int(x*254), int(y*254)))
    return (np.array(result, dtype=np.float32) / 127 * radius).astype(int)


def neighbors(frame_dim, reuse_seed, table):
    # TinyUniformSampleGenerator(interleaved pixel, sgCount * reuse seed + spatialSgOffset).
    width, height = frame_dim
    y, x = np.indices((height, width), dtype=np.uint32)
    left = sum((((x >> i) & 1) << (2*i)) | (((y >> i) & 1) << (2*i+1)) for i in range(16))
    right = np.full_like(left, (3 * reuse_seed + 2) & 0xffffffff)
    total = 0
    for _ in range(16):
        total = (total + 0x9e3779b9) & 0xffffffff
        left += ((right << 4) + 0xa341316c) ^ (right + total) ^ ((right >> 5) + 0xc8013ea4)
        right += ((left << 4) + 0xad90777d) ^ (left + total) ^ ((left >> 5) + 0x7e95761e)
    rng = left * 1664525 + 1013904223
    dx, dy = np.moveaxis(table[rng >> 19], -1, 0)
    return x.astype(int) + dx, y.astype(int) + dy


def lobes(moment):
    mean = moment[:, :3] / np.where(moment[:, 3:4] > 0, moment[:, 3:4], 1)
    length = np.linalg.norm(mean, axis=1)
    r = np.clip(length, 0, 1)
    t = r * (3-r*r)
    return mean, length, 100*t / (t + 100*(1-r*r))


def expected_h(a, b, evidence, limit):
    x, r, k = lobes(a)
    y, s, l = lobes(b)
    cosine = np.clip(np.sum(x*y, axis=1) / np.maximum(r*s, 1e-12), -1, 1)
    denom = np.maximum(k+l, 1e-12)
    overlap = np.minimum(1, 2*np.sqrt(k*l)/denom)**10 * np.exp(10*k*l/denom*(cosine-1))
    similarity = np.where(k+l <= 1e-12, 1, overlap)
    confidence = np.clip((evidence-1) / (limit-1), 0, 1) if limit > 1 else 0
    return np.where(np.minimum(a[:, 3], b[:, 3]) > 0, 1-confidence+confidence*similarity, 1)


def check(case):
    manifest = json.loads((case / "manifest.json").read_text(encoding="utf8"))
    if (manifest.get("status"), manifest.get("pdf_profile"), manifest.get("temporal_reuse")) != ("completed", "observe", True):
        raise ValueError("Expected a completed temporal-on observe capture")
    index = json.loads((case / "pdf-diagnostics.json").read_text(encoding="utf8"))
    paths = {(r["output"], r["frame"]): case / r["hdr"] for r in index["artifacts"]}
    dims = manifest["resolution"]
    reuse = manifest["requested_graph_options"]["reSTIRPathTracingOptions"]
    table = offsets(reuse["spatialGatherRadius"])
    limit = manifest["pdf_shader_parameters"]["history_limit"]
    summary = {"pairs": 0, "minimum_h": 1., "max_h_error": 0., "max_M_eff_error": 0.}
    for record in manifest["artifacts"]:
        f = record["frame"]
        def read(aov):
            return _read_exr(paths["PathTracer." + aov, f], "RGBA")
        moment = read("nrdDiffuseRadianceHitDist")
        count = read("nrdEmission")[..., 3]
        pair = read("nrdSpecularRadianceHitDist")
        x, y = neighbors(dims, record["reuse_seed"], table)
        active = pair[..., 1] > 0
        if np.any(active & ((x < 0) | (x >= dims[0]) | (y < 0) | (y >= dims[1]))):
            raise ValueError("An active proposal is outside the image")
        if not active.any():
            continue
        nx, ny = x[active], y[active]
        h = expected_h(moment[active], moment[ny, nx], np.minimum(count[active], count[ny, nx]), limit)
        err = np.abs(h - pair[active, 0])
        pos = int(err.argmax())
        if float(err[pos]) > summary["max_h_error"]:
            cy, cx = np.argwhere(active)[pos]
            summary.update(max_h_error=float(err[pos]), h_error_position=[f, int(cx), int(cy)])
        # The neighbor's own diagnostic Mc is its pre-spatial, post-temporal source M.
        delta = pair[active, 1] - pair[active, 0] * pair[ny, nx, 3]
        summary["max_M_eff_error"] = max(summary["max_M_eff_error"], float(np.max(np.abs(delta))))
        summary["pairs"] += int(active.sum())
        summary["minimum_h"] = min(summary["minimum_h"], float(pair[active, 0].min()))
    summary["passed"] = (summary["pairs"] > 0 and summary["max_h_error"] < 1e-5
                         and summary["max_M_eff_error"] == 0)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    result = check(parser.parse_args().case)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
