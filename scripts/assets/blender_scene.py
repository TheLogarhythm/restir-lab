"""Blender-side camera and authored-light conversion to glTF/Donut axes."""
import math
from mathutils import Vector


def camera_record(camera, scene):
    if camera is None:
        raise ValueError("Source scene has no active camera")
    matrix = camera.matrix_world
    rotation = matrix.to_quaternion()
    # view_frame accounts for sensor fit, render aspect and non-square pixels.
    frame = camera.data.view_frame(scene=scene)
    height = max(point.y for point in frame) - min(point.y for point in frame)
    vertical_fov = 2 * math.atan(height / (2 * abs(frame[0].z)))
    def yup(value):
        return [float(value.x), float(value.z), float(-value.y)]
    return {"position": yup(matrix.translation),
            "direction": yup((rotation @ Vector((0, 0, -1))).normalized()),
            "up": yup((rotation @ Vector((0, 1, 0))).normalized()),
            "vertical_fov": math.degrees(vertical_fov)}


def source_light(obj, matrix):
    """Map authored Blender lamps to Donut's native radiometric light fields."""
    from mathutils import Matrix
    data = obj.data
    if data.type not in ("SUN", "POINT", "AREA"):
        raise ValueError(f"Unsupported authored light: {obj.name}: {data.type}")
    if data.type == "AREA" and data.shape not in ("SQUARE", "RECTANGLE"):
        raise ValueError(f"Unsupported area shape: {obj.name}: {data.shape}")
    transform = Matrix.Rotation(-math.pi / 2, 4, "X") @ matrix
    rotation = transform.to_quaternion()
    result = {"name": obj.name, "translation": list(transform.translation),
              "rotation": [rotation.x, rotation.y, rotation.z, rotation.w], "color": list(data.color)}
    energy = data.energy * 2 ** data.exposure
    if not data.normalize:
        energy *= data.area(matrix_world=matrix)
    if data.type == "SUN":
        result.update(type="DirectionalLight", irradiance=energy, angularSize=math.degrees(data.angle))
    elif data.type == "POINT":
        result.update(type="PointLight", intensity=energy / (4 * math.pi), radius=data.shadow_soft_size)
    else:
        scale = matrix.to_scale()
        width = data.size * abs(scale.x)
        height = (data.size_y if data.shape == "RECTANGLE" else data.size) * abs(scale.y)
        result.update(type="RectLight", width=width, height=height, flux=energy / math.pi)
    return result

