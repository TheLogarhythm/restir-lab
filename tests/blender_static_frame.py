"""Exercise the real FBX worker: frame baking, visibility and default animation export."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/assets"))
import blender_export


def world_matrices(document):
    result = {}

    def visit(index, parent):
        node = document["nodes"][index]
        if "matrix" in node:
            values = node["matrix"]
            local = Matrix([values[i:i + 4] for i in range(0, 16, 4)]).transposed()
        else:
            x, y, z, w = node.get("rotation", [0, 0, 0, 1])
            local = Matrix.LocRotScale(Vector(node.get("translation", [0, 0, 0])),
                                       Quaternion((w, x, y, z)), Vector(node.get("scale", [1, 1, 1])))
        world = parent @ local
        result[node.get("name", str(index))] = world
        for child in node.get("children", []):
            visit(child, world)

    for index in document["scenes"][document.get("scene", 0)]["nodes"]:
        visit(index, Matrix.Identity(4))
    return result


class StaticFbxTests(unittest.TestCase):
    def test_actual_worker_bakes_requested_pose_and_filters_hidden_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "animated.fbx"
            bpy.ops.wm.read_factory_settings(use_empty=True)
            scene = bpy.context.scene
            scene.frame_start, scene.frame_end = 1, 9
            bpy.ops.mesh.primitive_cube_add()
            animated = bpy.context.object
            animated.name = "animated-mesh"
            for frame, x in ((1, 2), (9, 8)):
                animated.location = (x, 1, 3)
                animated.keyframe_insert(data_path="location", frame=frame)
            bpy.ops.mesh.primitive_cube_add()
            hidden = bpy.context.object
            hidden.name = "hidden-construction"
            hidden.hide_viewport = True
            bpy.ops.object.camera_add(location=(4, -5, 6))
            camera = bpy.context.object
            camera.name = "source-camera"
            scene.camera = camera
            for frame, x in ((1, 4), (9, 7)):
                camera.location.x = x
                camera.keyframe_insert(data_path="location", frame=frame)
            scene.frame_set(1)
            bpy.ops.export_scene.fbx(filepath=str(source), use_selection=False,
                                     bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False)

            def export(name, *options):
                output = root / f"{name}.gltf"
                with patch.object(sys, "argv", ["blender", "--", "fbx", str(source), str(output), *options]):
                    blender_export.main()
                return output, json.loads(output.read_text())

            # The FBX importer adds one frame; authored frame 9 is imported frame 10.
            output, document = export("filtered", "--static-frame", "10", "--visible-only")
            metadata = json.loads(output.with_suffix(".import.json").read_text())
            self.assertEqual(metadata["source_frame"], 10)
            self.assertEqual(metadata["visibility_filter"], "visible_and_renderable")
            self.assertEqual(metadata["excluded_meshes"], 1)
            self.assertFalse(document.get("animations"))
            mesh_names = {node["name"] for node in document["nodes"] if "mesh" in node}
            self.assertEqual(mesh_names, {"animated-mesh"})
            worlds = world_matrices(document)
            # Blender Z-up -> glTF Y-up: (x, y, z) -> (x, z, -y).
            for actual, expected in zip(worlds["animated-mesh"].translation, (8, 3, -1)):
                self.assertAlmostEqual(actual, expected, places=4)
            for actual, expected in zip(worlds["source-camera"].translation, metadata["camera"]["position"]):
                self.assertAlmostEqual(actual, expected, places=4)
            for actual, expected in zip(metadata["camera"]["position"], (7, 6, 5)):
                self.assertAlmostEqual(actual, expected, places=4)
            fov = math.degrees(document["cameras"][0]["perspective"]["yfov"])
            self.assertAlmostEqual(metadata["camera"]["vertical_fov"], fov, places=4)

            _, unfiltered = export("unfiltered", "--static-frame", "10")
            self.assertIn("hidden-construction", {node.get("name") for node in unfiltered["nodes"] if "mesh" in node})
            _, animated = export("default")
            self.assertTrue(animated.get("animations"), "Default FBX conversion lost animation")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StaticFbxTests))
    if not result.wasSuccessful():
        raise RuntimeError("Static FBX regression failed")
