"""Arc-length camera sampling for the approved 40 + 300 frame preview schedule."""
import bisect
import json
import math
from pathlib import Path, PurePosixPath


def _vector(value):
    if (not isinstance(value, list) or len(value) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
        raise ValueError("Expected a finite three-component vector")
    return [float(x) for x in value]


def _pose(position, target, camera):
    direction = [b - a for a, b in zip(position, target)]
    up = camera["up"]
    cross = [direction[1] * up[2] - direction[2] * up[1],
             direction[2] * up[0] - direction[0] * up[2],
             direction[0] * up[1] - direction[1] * up[0]]
    if math.hypot(*cross) < 1e-8:
        raise ValueError("Camera direction must be nonzero and not parallel to up")
    return {**camera, "position": list(position), "target": list(target)}


def _rounded_u_path(config):
    """Two tangent straights joined by an analytic horizontal semicircle."""
    route = config["rounded_u"]
    if not isinstance(route, dict):
        raise ValueError("Invalid rounded U route")
    start, entry, target = (_vector(route[name]) for name in ("start", "turn_entry", "target"))
    radius = route.get("radius")
    if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
        raise ValueError("Rounded U radius must be finite and positive")
    if route.get("side") not in ("left", "right") or start[1] != entry[1]:
        raise ValueError("Rounded U requires a left/right turn at constant height")
    lead = math.dist(start, entry)
    total = config["speed_m_per_second"] * config["move_seconds"] / config["meters_per_scene_unit"]
    turn_end = lead + math.pi * radius
    if not math.isfinite(total) or not 1e-8 < lead < turn_end < total - 1e-8:
        raise ValueError("Rounded U must fit two nonzero straights and a semicircle in the path budget")
    forward = [(b - a) / lead for a, b in zip(start, entry)]
    sign = 1 if route["side"] == "left" else -1
    lateral = [sign * forward[2], 0.0, -sign * forward[0]]

    def sample(distance):
        if distance <= lead:
            position = [a + distance * d for a, d in zip(start, forward)]
        elif distance <= turn_end:
            angle = (distance - lead) / radius
            position = [a + radius * ((1 - math.cos(angle)) * side + math.sin(angle) * d)
                        for a, side, d in zip(entry, lateral, forward)]
        else:
            position = [a + 2 * radius * side - (distance - turn_end) * d
                        for a, side, d in zip(entry, lateral, forward)]
        return _pose(position, target, config["camera"])

    distances = [0.0, lead, turn_end, total]
    for distance in distances:
        sample(distance)
    return distances, sample


def validate(config):
    fixed = {"schema_version": 1, "fps": 30, "warmup_frames": 40,
             "hold_start_seconds": 1, "move_seconds": 8, "hold_end_seconds": 1}
    if any(type(config.get(k)) is not int or config[k] != v for k, v in fixed.items()):
        raise ValueError("Preview requires 40 warmup frames and a 1 + 8 + 1 second, 30 FPS schedule")
    if not isinstance(config.get("id"), str) or not config["id"]:
        raise ValueError("Trajectory id is required")
    source = PurePosixPath(config.get("scene_config", ""))
    if (source.is_absolute() or ".." in source.parts or "\\" in str(source)
            or ":" in str(source) or not source.parts or source.parts[0] != "experiments"):
        raise ValueError("scene_config must be workspace-relative under experiments")
    for key in ("meters_per_scene_unit", "speed_m_per_second"):
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid " + key)
    if not isinstance(config.get("unit_basis"), str) or not config["unit_basis"]:
        raise ValueError("State the physical unit convention or its uncertainty")
    camera = config["camera"]
    _vector(camera["up"])
    for name, low, high in (("vertical_fov", 1, 170), ("near_plane", 0, 1)):
        value = camera.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not low < value < high:
            raise ValueError("Invalid camera " + name)
    if ("waypoints" in config) == ("rounded_u" in config):
        raise ValueError("Specify either waypoints or a rounded_u route")
    if "rounded_u" in config:
        distance, _ = _rounded_u_path(config)
    else:
        points = config["waypoints"]
        if not isinstance(points, list) or not 2 <= len(points) <= 4096:
            raise ValueError("Need 2 to 4096 camera waypoints")
        distance = [0.0]
        for index, point in enumerate(points):
            _pose(_vector(point["position"]), _vector(point["target"]), camera)
            if index:
                length = math.dist(point["position"], points[index - 1]["position"])
                if length <= 1e-8:
                    raise ValueError("Consecutive positions must differ")
                distance.append(distance[-1] + length)
    requested = config["speed_m_per_second"] * config["move_seconds"]
    if not math.isclose(distance[-1] * config["meters_per_scene_unit"], requested,
                        rel_tol=1e-6, abs_tol=1e-6):
        raise ValueError("Path length must equal speed times eight seconds")
    return distance


def sample_frames(config, *, seed_offset=0):
    distances = validate(config)
    if type(seed_offset) is not int or not 0 <= seed_offset <= 2**32 - 340:
        raise ValueError("Trajectory seeds exceed uint32")
    if "rounded_u" in config:
        _, sample_pose = _rounded_u_path(config)
    else:
        points = config["waypoints"]
        def sample_pose(distance):
            right = min(len(points) - 1, bisect.bisect_right(distances, distance))
            left = right - 1
            alpha = (distance - distances[left]) / (distances[right] - distances[left])
            def interpolate(name):
                return [(1 - alpha) * a + alpha * b
                        for a, b in zip(points[left][name], points[right][name])]
            return _pose(interpolate("position"), interpolate("target"), config["camera"])
    result = []
    for index in range(340):
        video_frame = None if index < 40 else index - 40
        time = 0.0 if video_frame is None else video_frame / 30
        fraction = min(1.0, max(0.0, (time - 1.0) / 8.0))
        distance = distances[-1] * fraction
        pose = sample_pose(distance)
        result.append({"frame": index + 1, "path_seed": seed_offset + index,
                       "video_frame": video_frame, "video_time_seconds": time,
                       "distance_scene_units": distance, "camera": pose})
    return result


def load(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate(config)
    return config
