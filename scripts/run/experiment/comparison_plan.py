"""Frozen input plans: artifact integrity is distinct from current-code rendering."""
from pathlib import Path
import hashlib
import zipfile
from rtxdi_common import ROOT, sha
from records.provenance import shared_source_hashes
from .fixed_reference import read_json

REQUIRED_CHECKS = {"cpu", "native", "scaffold", "gpu_off_equivalence", "gpu_transport_edges",
                   "gpu_reference_resume", "gpu_reference_convergence", "independent_review"}


def source_hashes():
    paths = [*sorted((ROOT / "scripts/run").rglob("*.py")),
             *sorted((ROOT / "scripts/analysis").glob("*.py")),
             *sorted((ROOT / "scripts/analysis").glob("*.html")),
             ROOT / "scripts/assets/gltf.py", ROOT / "scenes/manifest.yaml",
             *sorted((ROOT / "experiments/configs").rglob("*.json")),
             *sorted((ROOT / "scenes/configs").rglob("*.json"))]
    return {**{p.relative_to(ROOT).as_posix():sha(p) for p in paths}, **shared_source_hashes(ROOT)}


def validate_gate(path, builds, code, *, source_archive=None):
    path = Path(path).resolve()
    gate = read_json(path)
    targets = {a:"direct" if a == "DI" else "full" for a in builds if a != "reference"}
    if (gate.get("status") != "passed" or gate.get("unresolved_blockers") != []
            or gate.get("builds") != builds or gate.get("code_sha256") != code
            or set(gate.get("checks", {})) != REQUIRED_CHECKS or gate.get("target_compatibility") != targets):
        raise ValueError("Formal conformance gate has not passed for these exact inputs")
    for name, check in gate["checks"].items():
        if check.get("status") != "passed" or not check.get("evidence"):
            raise ValueError(f"Missing conformance evidence: {name}")
        for evidence in check["evidence"]:
            candidate = (path.parent / evidence["path"]).resolve()
            digest = sha(candidate) if candidate.is_file() else None
            if source_archive is not None and candidate.is_relative_to(ROOT) and candidate.relative_to(ROOT).parts[0] in ("scripts", "src", "tests", "experiments", "scenes"):
                with zipfile.ZipFile(source_archive) as archive:
                    key = candidate.relative_to(ROOT).as_posix()
                    digest = hashlib.sha256(archive.read(key)).hexdigest() if key in archive.namelist() else None
            if digest != evidence["sha256"]:
                raise ValueError(f"Conformance evidence changed: {name}")
    return gate


def read_artifact_plan(root, *, source_archive=None):
    """Verify an immutable historical receipt; never authorize a renderer launch.

The original source inventory and gate remain intact. Reanalysis records the
current inventory separately and does not claim the original exact-code receipt.
"""
    root = Path(root).resolve()
    plan = read_json(root / "plan.json")
    version = plan.get("schema_version")
    if version not in (1,2,3) or sha(root / "config.json") != plan["config_sha256"]:
        raise ValueError("Plan/configuration changed or schema unsupported")
    spec = read_json(root / "config.json")
    definition = ROOT / spec["definition_file"]
    if sha(definition) != plan["definition_sha256"]:
        raise ValueError("Frozen definition changed")
    if sha(root / "preview-check.json") != plan["preview_check_sha256"]:
        raise ValueError("Frozen camera verification changed")
    for entry in (*plan.get("external_inputs", {}).values(), *plan.get("reference_inputs", {}).values()):
        if sha(Path(entry["path"])) != entry["sha256"]:
            raise ValueError("Frozen external/reference input changed")
    if source_archive is not None:
        with zipfile.ZipFile(source_archive) as archive:
            for key, digest in plan["code_sha256"].items():
                if key not in archive.namelist() or hashlib.sha256(archive.read(key)).hexdigest() != digest:
                    raise ValueError(f"Historical source archive differs from frozen inventory: {key}")
    if version in (2,3):
        validate_gate(plan["external_inputs"]["conformance"]["path"], plan["builds"], plan["code_sha256"],
                      source_archive=source_archive)
    return plan


def validate_plan(root):
    """Current-code execution requires a new schema-3 exact-source plan."""
    plan = read_artifact_plan(root)
    if plan["schema_version"] != 3 or plan["code_sha256"] != source_hashes():
        raise ValueError("Frozen comparison code differs; historical artifact verification does not authorize resume")
    from .comparison_config import load_spec, validate_approved_budget
    validate_approved_budget(load_spec(Path(root) / "config.json"))
    return plan
