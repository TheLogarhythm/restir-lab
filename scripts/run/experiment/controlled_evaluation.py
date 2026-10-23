"""Fixed sparse quality selection; method captures and render settings stay intact.

Reference targets are exact physical states. Sampling seed, PDF weighting,
reuse mode, neighbour count, and logical time never create a new target.
"""
import copy
import hashlib
import json

from .reference import target, target_key

STATIC_FRAMES = (128,)
REPRESENTATIVE_FRAMES = (32, 48, 96)
SUPPORT_FRAMES = (31, 47, 95)
TEMPORAL_PAIRS = ((31, 32), (47, 48), (95, 96))
EXPECTED_REFERENCE_STATES = 15
STATIC_PRIORITY = ("cornell-static", "arcade-static", "bistro-interior-static", "bistro-exterior-static")



def validate_reference_priority_scenes(value):
    """Validate optional launch scheduling without changing reference identity."""
    allowed = ("cornell-box", "arcade", "bistro")
    if (not isinstance(value, (list, tuple))
            or any(not isinstance(scene, str) or scene not in allowed for scene in value)
            or len(set(value)) != len(value)):
        raise ValueError("Reference priority scenes must be unique known scene IDs")
    return tuple(value)


def reference_execution_order(states, priority_scenes=()):
    """Return stable execution order; leave the frozen inventory untouched."""
    priority = validate_reference_priority_scenes(priority_scenes)
    rows = list(states)
    if not priority:
        return rows
    rank = {scene: index for index, scene in enumerate(priority)}
    return sorted(rows, key=lambda row: rank.get(row["target"]["scene_id"], len(rank)))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def selection_spec(scenario):
    """Return a fresh, JSON-safe receipt of the approved quality frames."""
    if scenario == "static":
        spatial, support, pairs = STATIC_FRAMES, (), ()
    elif scenario in ("motion", "lighting"):
        spatial, support, pairs = REPRESENTATIVE_FRAMES, SUPPORT_FRAMES, TEMPORAL_PAIRS
    else:
        raise ValueError(f"Unsupported sparse quality scenario: {scenario}")
    return {"schema_version": 1, "spatial_frames": list(spatial), "support_frames": list(support),
            "temporal_pairs": [list(pair) for pair in pairs],
            "reference_frames": sorted(set(spatial) | set(support))}


def validate_selection(value, scenario):
    """Reject selection drift instead of silently changing the frozen analysis."""
    expected = selection_spec(scenario)
    try:
        same = _json(value) == _json(expected)
    except (TypeError, ValueError):
        same = False
    if not same:
        raise ValueError("Sparse quality selection differs from the approved fixed frames and pairs")
    return expected


def select_reference_captures(captures, scenario=None):
    """Select quality and preceding support frames, validating every input run.

    This selects reference *states*, not the captures used by the precision
    gate. Use :func:`quality_captures` on all retained runs for that gate.
    """
    selected, runs = [], {}
    for capture in captures:
        try:
            config = capture["config"]
            current = config["scenario"]
            frame = capture["frame"]["frame"]
            if scenario is not None and current != scenario:
                continue
            wanted = set(selection_spec(current)["reference_frames"])
            identity = (("directory", str(capture["directory"])) if "directory" in capture
                        else ("config", _json(config)))
        except (KeyError, TypeError) as error:
            raise ValueError("Missing sparse reference capture metadata") from error
        if type(frame) is not int or frame <= 0:
            raise ValueError("Invalid sparse reference capture frame")
        prior = runs.setdefault(identity, {"scenario": current, "wanted": wanted, "frames": set()})
        if prior["scenario"] != current or frame in prior["frames"]:
            raise ValueError("Duplicate frame or inconsistent scenario in sparse reference run")
        prior["frames"].add(frame)
        if frame in wanted:
            selected.append(capture)
    if not runs:
        raise ValueError("No captures match the sparse reference selection")
    for run in runs.values():
        missing = sorted(run["wanted"] - run["frames"])
        if missing:
            raise ValueError(f"Missing sparse quality/support frames in reference run: {missing}")
    return selected


def _capture_target(capture):
    """Check the saved target against both its key and actual config/frame."""
    try:
        saved = capture["target"]
        actual = target(capture["config"], capture["frame"], saved["asset_sha256"])
        key = capture["key"]
        if saved != actual or key != target_key(actual):
            raise ValueError("Sparse reference target or key differs from its exact physical state")
        # Reject NaNs as well as non-serializable metadata before saving receipts.
        _json(actual)
        return key, actual
    except (KeyError, TypeError) as error:
        raise ValueError("Missing sparse reference target identity") from error


def _condition(capture):
    config = capture["config"]
    # Configs do not carry condition names. The initial camera distinguishes
    # Bistro interior/exterior without incorporating a sampling choice.
    physical_condition = {"scene": config["scene_id"], "scenario": config["scenario"],
                          "camera": config["scene"]["camera"]}
    inferred = config["scene_id"] + "-" + config["scenario"] + "-" + hashlib.sha256(
        _json(physical_condition).encode()).hexdigest()[:12]
    label = capture.get("condition_id", inferred)
    if not isinstance(label, str) or not label:
        raise ValueError("Invalid sparse reference condition identity")
    return label


def target_inventory(captures, expected_states=EXPECTED_REFERENCE_STATES):
    """Verify shared target identities and the frozen 15-state union.

    Receipts list each logical quality selection once even when many seeds,
    ablations, equal-time settings, or PDF methods use that selection.
    """
    if type(expected_states) is not int or expected_states <= 0:
        raise ValueError("Expected sparse reference state count must be a positive integer")
    states, aligned = {}, {}
    for capture in captures:
        key, value = _capture_target(capture)
        config, frame = capture["config"], capture["frame"]["frame"]
        spec = selection_spec(config["scenario"])
        if frame not in spec["reference_frames"]:
            raise ValueError("Inventory includes an unselected quality/support frame")
        condition = _condition(capture)
        logical = (condition, config["scenario"], frame)
        if logical in aligned and aligned[logical] != key:
            raise ValueError("Sparse reference target differs across seeds or method settings")
        aligned[logical] = key
        state = states.setdefault(key, {"key": key, "target": copy.deepcopy(value), "selections": []})
        if state["target"] != value:
            raise ValueError("Different sparse reference targets share a key")
        selection = {"condition": condition, "scene": config["scene_id"],
                     "scenario": config["scenario"], "frame": frame,
                     "role": "representative" if frame in spec["spatial_frames"] else "support"}
        if selection not in state["selections"]:
            state["selections"].append(selection)
    if len(states) != expected_states:
        raise ValueError(f"Frozen sparse reference inventory requires {expected_states} exact states; found {len(states)}")

    def priority(state):
        static = [selection for selection in state["selections"] if selection["scenario"] == "static"]
        if not static:
            return (1, 0, state["key"])
        rank = min((STATIC_PRIORITY.index(row["condition"]) if row["condition"] in STATIC_PRIORITY
                    else len(STATIC_PRIORITY)) for row in static)
        return (0, rank, state["key"])

    for state in states.values():
        state["selections"].sort(key=lambda row: tuple(row[field] for field in
                                  ("condition", "scenario", "frame", "role")))

    return {"schema_version": 1, "expected_state_count": expected_states, "state_count": len(states),
            "states": sorted(states.values(), key=priority)}


def quality_captures(captures, selected_keys):
    """Keep every method capture at selected states for the original strict gate."""
    selected = set(selected_keys)
    if not selected or any(not isinstance(key, str) or not key for key in selected):
        raise ValueError("Sparse reference quality keys must be nonempty strings")
    result, present = [], set()
    for capture in captures:
        if capture.get("key") in selected:
            key, _ = _capture_target(capture)
            result.append(capture)
            present.add(key)
    if present != selected:
        raise ValueError("A selected sparse reference state has no matching quality captures")
    return result
