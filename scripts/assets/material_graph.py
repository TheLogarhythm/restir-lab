"""Inspect only shaders reachable from the active material surface output.

No bpy import: node-link traversal can be tested without launching Blender.
"""
SHADERS = ("EMISSION", "BSDF_DIFFUSE", "BSDF_PRINCIPLED", "BSDF_GLASS", "BSDF_GLOSSY",
           "BSDF_TRANSLUCENT", "BSDF_TRANSPARENT")


class UnsupportedSurfaceNode(ValueError):
    """A surface graph requires an explicit profile approximation or rejection."""


def surface_shaders(material):
    if not material or not material.node_tree:
        return []
    outputs = [n for n in material.node_tree.nodes
               if n.type == "OUTPUT_MATERIAL" and n.is_active_output]
    if len(outputs) != 1:
        raise ValueError(f"Material {material.name}: expected one active output")
    result, visiting = [], set()

    def visit(node):
        identity = id(node)
        if identity in visiting:
            raise ValueError(f"Material {material.name}: cyclic shader graph")
        if node.type in SHADERS:
            if node not in result:
                result.append(node)
            return
        if node.type not in ("MIX_SHADER", "ADD_SHADER", "REROUTE"):
            raise UnsupportedSurfaceNode(f"Material {material.name}: unsupported surface node {node.type}")
        visiting.add(identity)
        for input_socket in node.inputs.values():
            if input_socket.type == "SHADER" or node.type == "REROUTE":
                for link in input_socket.links:
                    visit(link.from_node)
        visiting.remove(identity)

    for link in outputs[0].inputs["Surface"].links:
        visit(link.from_node)
    return result
