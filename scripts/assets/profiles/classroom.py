"""Classroom-specific legacy material baking; executed only inside Blender."""
import hashlib
import json
import math
import bpy
from blender_scene import camera_record, source_light
from material_graph import SHADERS, UnsupportedSurfaceNode, surface_shaders


def prepare_uv(mesh):
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="SourceUV")
    source_uv = mesh.uv_layers.active
    mesh.uv_layers.new(name="BakedUV")
    mesh.uv_layers.active_index = len(mesh.uv_layers) - 1
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.015)
    bpy.ops.object.mode_set(mode="OBJECT")
    source_uv.active_render = True


def prepare_bake_materials(obj, image, record):
    mesh = obj.data
    if not mesh.materials:
        material = bpy.data.materials.new("Unassigned surface")
        material.use_nodes = True
        mesh.materials.append(material)
        record["fallback_materials"].append(obj.name + ": source has no material")
    material_info = []
    for slot in obj.material_slots:
        original = slot.material
        mat = original.copy() if original else bpy.data.materials.new("unassigned")
        mat.use_nodes = True
        slot.material = mat
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        try:
            reachable = surface_shaders(mat)
        except UnsupportedSurfaceNode as exc:
            reachable = []
            record.setdefault("shader_approximations", []).append({
                "material": mat.name, "reason": str(exc), "selected": "neutral gray fallback"})
        shader = next((n for kind in SHADERS for n in reachable if n.type == kind), None)
        if len(reachable) > 1 or (shader and shader.type == "BSDF_TRANSLUCENT"):
            record.setdefault("shader_approximations", []).append({
                "material": mat.name, "connected_shaders": [n.type for n in reachable],
                "selected": shader.type, "reason": "Mixed/translucent surface reduced to one PBR material"})
        kind = shader.type if shader else "FALLBACK"
        strength = shader.inputs["Strength"].default_value if kind == "EMISSION" else 0
        roughness = shader.inputs["Roughness"].default_value if shader and "Roughness" in shader.inputs else 0.5
        if kind == "BSDF_DIFFUSE":
            glossy = next((n for n in reachable if n.type == "BSDF_GLOSSY"), None)
            roughness = glossy.inputs["Roughness"].default_value if glossy else 0.65
        material_info.append((mat, kind, strength, max(0.08, roughness)))
        if kind == "FALLBACK":
            record["fallback_materials"].append(original.name if original else "unassigned")
        emission = nodes.new("ShaderNodeEmission")
        socket = shader.inputs.get("Base Color" if kind == "BSDF_PRINCIPLED" else "Color") if shader else None
        if socket:
            if socket.is_linked:
                links.new(socket.links[0].from_socket, emission.inputs["Color"])
            else:
                emission.inputs["Color"].default_value = socket.default_value
        else:
            emission.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if not out:
            out = nodes.new("ShaderNodeOutputMaterial")
        for link in list(out.inputs["Surface"].links):
            links.remove(link)
        links.new(emission.outputs[0], out.inputs["Surface"])
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        nodes.active = tex
    if not material_info:
        raise ValueError(f"Mesh has no material slots: {obj.name}")
    return material_info


def rebuild_materials(obj, image, material_info, record):
    for mat, kind, strength, roughness in material_info:
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        out = nodes.new("ShaderNodeOutputMaterial")
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        links.new(tex.outputs["Color"], shader.inputs["Base Color"])
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = float(kind == "BSDF_GLOSSY")
        if kind == "EMISSION":
            links.new(tex.outputs["Color"], shader.inputs["Emission Color"])
            shader.inputs["Emission Strength"].default_value = strength
            if obj.get("invisible_emitter", False):
                # RTXDI samples emission independently of opacity. Alpha zero keeps
                # the source's camera/shadow-invisible emitter from blocking sun rays.
                shader.inputs["Alpha"].default_value = 0
                mat.surface_render_method = "BLENDED"
        if kind == "BSDF_TRANSPARENT":
            shader.inputs["Alpha"].default_value = 0
            mat.surface_render_method = "BLENDED"
        if kind == "BSDF_GLASS":
            shader.inputs["Alpha"].default_value = 0.12
            mat.surface_render_method = "BLENDED"
            record["glass_approximations"].append(mat.name)
        links.new(shader.outputs[0], out.inputs["Surface"])


def bake_mesh(obj, index, output, size, record):
    mesh = obj.data
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    prepare_uv(mesh)
    image = bpy.data.images.new(f"classroom-color-{index:03d}", width=size, height=size, alpha=False)
    image.filepath_raw = str(output / (image.name + ".png"))
    image.file_format = "PNG"
    materials = prepare_bake_materials(obj, image, record)
    bpy.ops.object.bake(type="EMIT", uv_layer="BakedUV", margin=4, use_clear=True)
    image.save()
    rebuild_materials(obj, image, materials, record)
    for layer in list(mesh.uv_layers):
        if layer.name != "BakedUV":
            mesh.uv_layers.remove(layer)
    mesh.uv_layers.active_index = 0
    mesh.uv_layers[0].active_render = True
    print(f"BAKED {index}: {obj.name} ({len(mesh.polygons)} faces)", flush=True)


def convert(source, output, texture_size=512):
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    original = bpy.context.scene
    camera = original.camera
    record = {"blender_version": bpy.app.version_string, "texture_size": texture_size,
              "camera": camera_record(camera, original),
              "portal_approximations":[],"source_lights":[],"fallback_materials":[],"glass_approximations":[],
              "approximations":["Legacy color graphs baked per shared mesh; instance-dependent variation frozen to representative",
                "Scalar roughness; micro-bump, displacement and volumetric effects omitted",
                "Pure glossy shaders approximated as metallic; glass approximated with alpha",
                "Daylight portal sky color baked; backface emission mapped to one-sided geometry; camera/shadow-invisible window emitter uses zero opacity",
                "Authored lights use radiometric units; point intensity is power / (4 pi); area radiance is power / (pi area)"]}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects, meshes, representatives = [], {}, {}
    source_lights = []
    for instance in depsgraph.object_instances:
        evaluated = instance.object
        if evaluated.type == "LIGHT" and instance.show_self and not evaluated.original.hide_render:
            source_lights.append(source_light(evaluated, instance.matrix_world.copy()))
        if evaluated.type != "MESH" or not instance.show_self or evaluated.original.hide_render:
            continue
        key = evaluated.original.as_pointer()
        if key not in meshes:
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
            # Material slots may override the shared mesh on the source object.
            materials = [slot.material for slot in evaluated.material_slots]
            mesh.materials.clear()
            for material in materials:
                mesh.materials.append(material)
            if any(m and m.name == "dayLight_portal" for m in materials):
                mesh.flip_normals()
                record["portal_approximations"].append(evaluated.name)
            meshes[key] = mesh
        if not meshes[key].polygons:
            continue
        obj = bpy.data.objects.new(evaluated.name + "-export", meshes[key])
        obj.matrix_world = instance.matrix_world.copy()
        obj["invisible_emitter"] = not evaluated.original.visible_camera and not evaluated.original.visible_shadow
        objects.append(obj)
        representatives.setdefault(key, obj)
    scene = bpy.data.scenes.new("ClassroomExport")
    bpy.context.window.scene = scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    for obj in objects:
        scene.collection.objects.link(obj)
    record.update(objects=len(objects), unique_meshes=len(representatives))
    print("EXPORT OBJECTS",len(objects),"UNIQUE MESHES",len(representatives),flush=True)
    for i, obj in enumerate(representatives.values()):
        bake_mesh(obj, i, output.parent, texture_size, record)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLTF_SEPARATE", use_selection=True,
        export_cameras=False, export_lights=False, export_animations=False, export_apply=False,
        export_image_format="AUTO", export_texcoords=True, export_normals=True)
    wrapper = {"models": [output.name], "graph": [{"name": "Classroom", "model": 0}, *source_lights]}
    output.with_suffix(".scene.json").write_text(json.dumps(wrapper, indent=2) + "\n", encoding="utf-8")
    record["source_lights"] = source_lights
    record["fallback_materials"] = sorted(set(record["fallback_materials"]))
    record["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".conversion.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
    return record
