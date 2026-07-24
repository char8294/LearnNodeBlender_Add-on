"""Headless performance probe for Learn Node's live geometry socket inspection.

Run with Blender: blender --background --factory-startup --python tests/perf_live_geometry_probe.py
"""

import importlib.util
import sys
import time
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("learn_node_blender", ROOT / "__init__.py")
addon = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = addon
SPEC.loader.exec_module(addon)


def make_tree():
    tree = bpy.data.node_groups.new("Live Geometry Probe", "GeometryNodeTree")
    tree.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    group_input = tree.nodes.new("NodeGroupInput")
    group_output = tree.nodes.new("NodeGroupOutput")
    grid = tree.nodes.new("GeometryNodeMeshIcoSphere")
    grid.name = "Dense Icosphere"
    grid.inputs["Subdivisions"].default_value = 9
    tree.links.new(grid.outputs["Mesh"], group_output.inputs["Geometry"])
    owner_mesh = bpy.data.meshes.new("Probe Owner Mesh")
    owner = bpy.data.objects.new("Probe Owner", owner_mesh)
    bpy.context.scene.collection.objects.link(owner)
    modifier = owner.modifiers.new("Geometry Nodes", "NODES")
    modifier.node_group = tree
    bpy.context.view_layer.objects.active = owner
    owner.select_set(True)
    return tree, grid, owner


def main():
    tree, node, owner = make_tree()
    targets = addon.get_runtime_value_targets([], [node.outputs["Mesh"]])
    try:
        start = time.perf_counter()
        values = addon.evaluate_runtime_values(tree, targets)
        elapsed = time.perf_counter() - start
        assert targets == [], "Geometry output must not schedule a live evaluation"
        assert values == {}, "Geometry output must not produce a live value"
        print(f"LIVE_GEOMETRY_SELECTION_SECONDS={elapsed:.3f}")
        assert elapsed < 0.25, f"selection-path geometry work took {elapsed:.3f}s"
    finally:
        bpy.data.objects.remove(owner, do_unlink=True)
        bpy.data.node_groups.remove(tree)


main()
