bl_info = {
    "name": "Learn Node (Thai Explainer)",
    "author": "Antigravity",
    "version": (1, 0),
    "blender": (3, 3, 0),
    "location": "Node Editor > N-Panel > Learn Node",
    "description": "Explains Geometry Nodes in Thai using a HUD overlay.",
    "category": "Node",
}

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
import json
import os
import glob
import textwrap

# Global handler variable
draw_handler = None
node_data_cache = None
global_box_height = 400

SOCKET_TYPE_NAMES = {
    'VALUE': 'Float', 'INT': 'Integer', 'BOOLEAN': 'Boolean',
    'VECTOR': 'Vector', 'STRING': 'String', 'RGBA': 'Color',
    'SHADER': 'Shader', 'OBJECT': 'Object', 'IMAGE': 'Image',
    'GEOMETRY': 'Geometry', 'COLLECTION': 'Collection',
    'TEXTURE': 'Texture', 'MATERIAL': 'Material'
}

PROBE_DATA_TYPE_BY_SOCKET_TYPE = {
    'VALUE': 'FLOAT',
    'INT': 'INT',
    'BOOLEAN': 'BOOLEAN',
    'VECTOR': 'FLOAT_VECTOR',
    'RGBA': 'FLOAT_COLOR',
}
RUNTIME_VALUE_REFRESH_SECONDS = 0.3
runtime_value_cache = {"key": None, "values": {}}
runtime_probe_index = 0

def get_node_data():
    global node_data_cache
    if node_data_cache is None:
        node_data_cache = {}
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        if os.path.exists(data_dir):
            for filepath in glob.glob(os.path.join(data_dir, "*.json")):
                with open(filepath, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                        node_data_cache.update(data)
                    except Exception as e:
                        print(f"Error loading {filepath}: {e}")
    return node_data_cache

THAI_COMBINING = set('\u0e31\u0e33\u0e34\u0e35\u0e36\u0e37\u0e38\u0e39\u0e3a\u0e47\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u0e4d\u0e4e')

def format_number(value):
    """Keep numeric socket values short enough to read in the HUD."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)

def format_socket_default_value(value):
    """Return a compact, readable representation of a socket default value."""
    if value is None:
        return "None"
    if isinstance(value, (bool, int, float)):
        return format_number(value)
    if isinstance(value, str):
        return f'"{value}"' if value else '""'

    # Object, collection, material, and image sockets expose Blender ID data.
    if hasattr(value, "name"):
        return value.name

    # Vector, color, rotation, and matrix-style values are iterable RNA arrays.
    try:
        components = tuple(value)
    except (TypeError, ValueError):
        return str(value)

    if components:
        return "(" + ", ".join(format_number(component) for component in components) + ")"
    return str(value)

def runtime_socket_key(socket):
    return (socket.node.name, socket.identifier, socket.is_output)

def find_socket_by_identifier(sockets, identifier):
    return next((socket for socket in sockets if socket.identifier == identifier), None)

def get_runtime_value_targets(valid_inputs, valid_outputs):
    """Map HUD sockets to the output sockets that provide their live values."""
    targets = []
    for socket in valid_inputs:
        if socket.is_linked:
            source_socket = socket.links[0].from_socket
            if source_socket.inferred_structure_type == 'SINGLE':
                targets.append((runtime_socket_key(socket), source_socket))
    for socket in valid_outputs:
        if socket.inferred_structure_type == 'SINGLE':
            targets.append((runtime_socket_key(socket), socket))
    return targets

def read_attribute_value(attribute):
    if not attribute.data:
        return None
    item = attribute.data[0]
    for property_name in ('value', 'vector', 'color'):
        try:
            return getattr(item, property_name)
        except AttributeError:
            pass
    return None

def evaluate_runtime_values(tree, targets):
    """Evaluate socket outputs on a temporary point, matching the Viewer-node model."""
    global runtime_probe_index

    supported_targets = [
        (display_key, source_socket)
        for display_key, source_socket in targets
        if source_socket.type in PROBE_DATA_TYPE_BY_SOCKET_TYPE
    ]
    if not supported_targets:
        return {}

    probe_tree = None
    probe_mesh = None
    probe_object = None
    values = {}
    runtime_probe_index += 1
    probe_prefix = f"__learn_node_probe_{runtime_probe_index}_"

    try:
        probe_tree = tree.copy()
        group_input = next(node for node in probe_tree.nodes if node.bl_idname == 'NodeGroupInput')
        group_output = next(
            node for node in probe_tree.nodes
            if node.bl_idname == 'NodeGroupOutput' and node.is_active_output
        )
        geometry_input = next(socket for socket in group_input.outputs if socket.type == 'GEOMETRY')
        geometry_output = next(socket for socket in group_output.inputs if socket.type == 'GEOMETRY')

        current_geometry = geometry_input
        captured_targets = []
        for index, (display_key, source_socket) in enumerate(supported_targets):
            probe_node = probe_tree.nodes.get(source_socket.node.name)
            if not probe_node:
                continue
            probe_socket = find_socket_by_identifier(probe_node.outputs, source_socket.identifier)
            if not probe_socket:
                continue

            attribute_name = f"{probe_prefix}{index}"
            store = probe_tree.nodes.new('GeometryNodeStoreNamedAttribute')
            store.data_type = PROBE_DATA_TYPE_BY_SOCKET_TYPE[source_socket.type]
            store.domain = 'POINT'
            store.inputs['Name'].default_value = attribute_name
            probe_tree.links.new(current_geometry, store.inputs['Geometry'])
            probe_tree.links.new(probe_socket, store.inputs['Value'])
            current_geometry = store.outputs['Geometry']
            captured_targets.append((display_key, source_socket, attribute_name))

        if not captured_targets:
            return {}
        probe_tree.links.new(current_geometry, geometry_output)

        probe_mesh = bpy.data.meshes.new(f"{probe_prefix}mesh")
        probe_mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        probe_mesh.update()
        probe_object = bpy.data.objects.new(f"{probe_prefix}object", probe_mesh)
        bpy.context.scene.collection.objects.link(probe_object)
        modifier = probe_object.modifiers.new(f"{probe_prefix}modifier", 'NODES')
        modifier.node_group = probe_tree

        bpy.context.view_layer.update()
        evaluated_object = probe_object.evaluated_get(bpy.context.evaluated_depsgraph_get())
        attributes = evaluated_object.data.attributes
        for display_key, source_socket, attribute_name in captured_targets:
            attribute = attributes.get(attribute_name)
            value = read_attribute_value(attribute) if attribute else None
            if value is None:
                continue
            values[display_key] = format_socket_default_value(value)
    except (AttributeError, KeyError, RuntimeError, StopIteration, TypeError, ValueError) as error:
        print(f"Learn Node: could not evaluate runtime values: {error}")
    finally:
        if probe_object:
            bpy.data.objects.remove(probe_object, do_unlink=True)
        if probe_mesh:
            bpy.data.meshes.remove(probe_mesh)
        if probe_tree:
            bpy.data.node_groups.remove(probe_tree)

    return values

def runtime_values_cache_key(tree, active_node, targets):
    return (
        tree.as_pointer(),
        active_node.as_pointer(),
        tuple((display_key, source_socket.node.name, source_socket.identifier) for display_key, source_socket in targets),
    )

def get_live_socket_values(tree, active_node, valid_inputs, valid_outputs):
    """Read the latest timer-produced values without mutating Blender during drawing."""
    targets = get_runtime_value_targets(valid_inputs, valid_outputs)
    cache_key = runtime_values_cache_key(tree, active_node, targets)
    return runtime_value_cache["values"] if runtime_value_cache["key"] == cache_key else {}

def find_active_geometry_node_context():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'NODE_EDITOR':
                continue
            space = area.spaces.active
            if space.tree_type != 'GeometryNodeTree' or not space.edit_tree:
                continue
            active_node = space.edit_tree.nodes.active
            if active_node:
                return space.edit_tree, active_node
    return None, None

def refresh_runtime_values():
    """Evaluate active-node sockets away from the draw handler, like a lightweight Viewer."""
    global runtime_value_cache

    try:
        prefs = bpy.context.preferences.addons[__package__ if __package__ else __name__].preferences
    except KeyError:
        return RUNTIME_VALUE_REFRESH_SECONDS
    if not prefs.show_hud:
        return RUNTIME_VALUE_REFRESH_SECONDS

    tree, active_node = find_active_geometry_node_context()
    if not tree or not active_node:
        return RUNTIME_VALUE_REFRESH_SECONDS

    valid_inputs = [socket for socket in active_node.inputs if not socket.hide and not socket.is_unavailable]
    valid_outputs = [socket for socket in active_node.outputs if not socket.hide and not socket.is_unavailable]
    targets = get_runtime_value_targets(valid_inputs, valid_outputs)
    cache_key = runtime_values_cache_key(tree, active_node, targets)
    values = evaluate_runtime_values(tree, targets)
    runtime_value_cache = {"key": cache_key, "values": values}

    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()
    return RUNTIME_VALUE_REFRESH_SECONDS

def get_socket_runtime_value(socket, live_values):
    """Return only the value Blender can show for a socket, never link metadata."""
    live_value = live_values.get(runtime_socket_key(socket))
    if live_value is not None:
        return f"Value: {live_value}"

    if not socket.is_output and not socket.hide_value and socket.type in PROBE_DATA_TYPE_BY_SOCKET_TYPE:
        try:
            default_value = socket.default_value
            if default_value is not None:
                return f"Value: {format_socket_default_value(default_value)}"
        except (AttributeError, TypeError, ValueError):
            pass
    return ""

def get_socket_type_name(socket):
    socket_type = SOCKET_TYPE_NAMES.get(getattr(socket, 'type', ''), getattr(socket, 'type', '').title())
    if getattr(socket, 'display_shape', '') == 'DIAMOND':
        socket_type += " Field"
    return socket_type

def draw_text_multiline(font_id, text, x, y, max_width, size=16, color=(1,1,1,1)):
    blf.size(font_id, size)
    blf.color(font_id, *color)
    
    lines = []
    for paragraph in str(text).split('\n'):
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            width, _ = blf.dimensions(font_id, test_line)
            # Never break line if character is a combining mark
            if width <= max_width or char in THAI_COMBINING:
                current_line = test_line
            else:
                if char == ' ':
                    lines.append(current_line)
                    current_line = ""
                else:
                    # find a space to break nicely for English words
                    last_space = current_line.rfind(' ')
                    if last_space != -1 and (len(current_line) - last_space) < 20: 
                        lines.append(current_line[:last_space])
                        current_line = current_line[last_space+1:] + char
                    else:
                        # Character break (suitable for Thai text without spaces)
                        lines.append(current_line)
                        current_line = char
        if current_line:
            lines.append(current_line)
    
    current_y = y
    for line in lines:
        blf.position(font_id, x, current_y, 0)
        blf.draw(font_id, line)
        current_y -= size * 1.5
        
    return current_y

def draw_callback_px():
    context = bpy.context
    try:
        prefs = context.preferences.addons[__package__ if __package__ else __name__].preferences
    except KeyError:
        return
        
    if not prefs.show_hud:
        return
        
    space = context.space_data
    if space.type != 'NODE_EDITOR' or space.tree_type != 'GeometryNodeTree':
        return
        
    tree = space.edit_tree
    if not tree:
        return
        
    active_node = tree.nodes.active
    if not active_node:
        return
        
    node_data = get_node_data()
    node_info_raw = node_data.get(active_node.bl_idname)
    
    node_info = None
    if node_info_raw:
        # Create a copy so we don't overwrite the cached base data
        node_info = dict(node_info_raw)
        
        # Check all possible dropdown properties on the node
        sub_types_dict = node_info.get("sub_types", {})
        for prop_key, prop_sub_types in sub_types_dict.items():
            if hasattr(active_node, prop_key):
                prop_val = getattr(active_node, prop_key)
                if prop_val in prop_sub_types:
                    sub_data = prop_sub_types[prop_val]
                    # Override the base properties
                    if "name" in sub_data and sub_data["name"]: 
                        node_info["name"] = sub_data["name"]
                    if "description" in sub_data and sub_data["description"]: 
                        if node_info.get("description"):
                            node_info["description"] += "\n" + sub_data["description"]
                        else:
                            node_info["description"] = sub_data["description"]
                    if "inputs" in sub_data and sub_data["inputs"]: 
                        if "inputs" not in node_info: node_info["inputs"] = {}
                        node_info["inputs"].update(sub_data["inputs"])
                    if "outputs" in sub_data and sub_data["outputs"]: 
                        if "outputs" not in node_info: node_info["outputs"] = {}
                        node_info["outputs"].update(sub_data["outputs"])
        
    region = context.region
    width = region.width
    height = region.height
    
    scale = prefs.hud_scale
    box_width = int(350 * scale)
    padding = int(20 * scale)
    
    global global_box_height
    
    if prefs.hud_x == -1 or prefs.hud_y == -1:
        x = width - box_width - padding
        start_y = height - padding
    else:
        x = prefs.hud_x
        start_y = prefs.hud_y
        
    y = start_y - global_box_height
    
    vertices = (
        (x, y), (x + box_width, y),
        (x, start_y), (x + box_width, start_y)
    )
    indices = ((0, 1, 2), (2, 1, 3))
    
    if bpy.app.version >= (4, 0, 0):
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    else:
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        
    batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)
    
    # Draw Background
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", (0.1, 0.1, 0.1, prefs.hud_bg_opacity))
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    
    # Draw Lock Warning if unlocked
    if not prefs.hud_locked:
        shader.uniform_float("color", (0.8, 0.2, 0.2, 0.5))
        batch.draw(shader)
        
        blf.size(font_id, int(14 * scale))
        blf.color(font_id, 1, 1, 1, 1)
        blf.position(font_id, x + int(15 * scale), y + int(10 * scale), 0)
        blf.draw(font_id, "Right Click or ESC to Lock")
    
    # Draw Text
    font_id = 0
    text_x = x + 15
    text_y = start_y - 30
    
    if node_info:
        # Title (English, multiline)
        blf.color(font_id, 1, 0.8, 0.2, 1)
        title = active_node.label if active_node.label else active_node.bl_label
        text_y = draw_text_multiline(font_id, title, text_x, text_y, box_width - int(30 * scale), size=int(24 * scale))
        text_y -= int(15 * scale)
        
        # Description
        desc = node_info.get("description", "")
        text_y = draw_text_multiline(font_id, desc, text_x, text_y, box_width - int(30 * scale), size=int(16 * scale))
        text_y -= int(10 * scale)
        
        # Inputs
        valid_inputs = [socket for socket in active_node.inputs if not socket.hide and not socket.is_unavailable]
        valid_outputs = [socket for socket in active_node.outputs if not socket.hide and not socket.is_unavailable]
        live_socket_values = get_live_socket_values(tree, active_node, valid_inputs, valid_outputs)
        if valid_inputs:
            blf.size(font_id, int(18 * scale))
            blf.color(font_id, 0.4, 0.8, 1.0, 1)
            blf.position(font_id, text_x, text_y, 0)
            blf.draw(font_id, "Inputs:")
            text_y -= int(25 * scale)
            
            json_inputs = node_info.get("inputs", {})
            for socket in valid_inputs:
                trans = json_inputs.get(socket.name)
                if not trans and hasattr(socket, 'identifier'):
                    trans = json_inputs.get(socket.identifier, "")
                
                trans_desc = ""
                if isinstance(trans, dict):
                    trans_desc = trans.get("description", "")
                elif isinstance(trans, str) and trans:
                    pass
                
                # Get socket color
                s_color = socket.draw_color(context, active_node)
                # Boost brightness slightly if it's too dark
                s_color = (min(1.0, s_color[0] * 1.2), min(1.0, s_color[1] * 1.2), min(1.0, s_color[2] * 1.2), 1.0)
                blf.color(font_id, *s_color)
                
                s_type = get_socket_type_name(socket)
                type_suffix = f" ({s_type})" if s_type else ""

                runtime_value = get_socket_runtime_value(socket, live_socket_values)
                display_text = f"- {socket.name}{type_suffix}"
                if runtime_value:
                    display_text += f"  {runtime_value}"
                text_y = draw_text_multiline(font_id, display_text, text_x, text_y, box_width - int(30 * scale), size=int(14 * scale), color=s_color)
                if trans_desc:
                    text_y = draw_text_multiline(font_id, f"  {trans_desc}", text_x, text_y, box_width - int(30 * scale), size=int(14 * scale), color=s_color)
                text_y -= int(5 * scale)
                
        text_y -= int(10 * scale)
        
        # Outputs
        if valid_outputs:
            blf.size(font_id, int(18 * scale))
            blf.color(font_id, 0.4, 0.8, 1.0, 1)
            blf.position(font_id, text_x, text_y, 0)
            blf.draw(font_id, "Outputs:")
            text_y -= int(25 * scale)
            
            json_outputs = node_info.get("outputs", {})
            for socket in valid_outputs:
                trans = json_outputs.get(socket.name)
                if not trans and hasattr(socket, 'identifier'):
                    trans = json_outputs.get(socket.identifier, "")
                
                trans_desc = ""
                if isinstance(trans, dict):
                    trans_desc = trans.get("description", "")
                
                # Get socket color
                s_color = socket.draw_color(context, active_node)
                s_color = (min(1.0, s_color[0] * 1.2), min(1.0, s_color[1] * 1.2), min(1.0, s_color[2] * 1.2), 1.0)
                blf.color(font_id, *s_color)
                
                s_type = get_socket_type_name(socket)
                type_suffix = f" ({s_type})" if s_type else ""

                runtime_value = get_socket_runtime_value(socket, live_socket_values)
                display_text = f"- {socket.name}{type_suffix}"
                if runtime_value:
                    display_text += f"  {runtime_value}"
                text_y = draw_text_multiline(font_id, display_text, text_x, text_y, box_width - int(30 * scale), size=int(14 * scale), color=s_color)
                if trans_desc:
                    text_y = draw_text_multiline(font_id, f"  {trans_desc}", text_x, text_y, box_width - int(30 * scale), size=int(14 * scale), color=s_color)
                text_y -= int(5 * scale)
    else:
        # Fallback if node not found
        blf.color(font_id, 1, 1, 1, 1)
        title = active_node.label if active_node.label else active_node.bl_label
        text_y = draw_text_multiline(font_id, title, text_x, text_y, box_width - int(30 * scale), size=int(20 * scale))
        text_y -= int(15 * scale)
        text_y = draw_text_multiline(font_id, "ยังไม่มีคำอธิบายสำหรับ Node นี้ในระบบ", text_x, text_y, box_width - int(30 * scale), size=int(16 * scale))

    # Calculate actual height for next frame's box drawing
    global_box_height = start_y - text_y + 20


def update_hud_scale(self, context):
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    area.tag_redraw()
    except Exception as e:
        print("Error in update_hud_scale:", e)

class LearnNodePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    show_hud: bpy.props.BoolProperty(
        name="Show HUD",
        description="Toggle the Learn Node HUD overlay",
        default=True
    )
    hud_x: bpy.props.IntProperty(name="HUD X", default=-1)
    hud_y: bpy.props.IntProperty(name="HUD Y", default=-1)
    hud_locked: bpy.props.BoolProperty(name="HUD Locked", default=True)
    hud_scale: bpy.props.FloatProperty(
        name="HUD Scale", 
        description="Scale the size of the HUD", 
        default=1.0, min=0.5, max=3.0, step=10,
        update=update_hud_scale
    )
    hud_bg_opacity: bpy.props.FloatProperty(
        name="HUD Opacity",
        description="Opacity of the background frame",
        default=0.85, min=0.0, max=1.0, step=5,
        update=update_hud_scale
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "show_hud")
        layout.prop(self, "hud_scale", slider=True)
        layout.prop(self, "hud_locked")


class NODE_PT_learn_node(bpy.types.Panel):
    bl_label = "Learn Node"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Learn Node"
    
    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'GeometryNodeTree'

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences
        
        layout.prop(prefs, "show_hud", text="Toggle HUD", toggle=True)
        layout.prop(prefs, "hud_scale", text="HUD Scale", slider=True)
        layout.prop(prefs, "hud_bg_opacity", text="Background Opacity", slider=True)
        
        if prefs.hud_locked:
            layout.operator("learn_node.unlock_hud", text="Unlock to Move", icon='UNLOCKED')
        else:
            layout.operator("learn_node.lock_hud", text="Lock Position", icon='LOCKED')
            
        layout.separator()
        layout.operator("learn_node.reload_data", text="Reload JSON Data", icon='FILE_REFRESH')


class NODE_OT_learn_node_reload(bpy.types.Operator):
    """Reload the JSON data file"""
    bl_idname = "learn_node.reload_data"
    bl_label = "Reload JSON Data"

    def execute(self, context):
        global node_data_cache
        node_data_cache = None
        get_node_data()
        self.report({'INFO'}, "Learn Node: JSON Data reloaded successfully")
        
        # Tag redraw to update HUD
        for area in context.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()
                
        return {'FINISHED'}

class NODE_OT_learn_node_drag_hud(bpy.types.Operator):
    """Drag the HUD across the Node Editor"""
    bl_idname = "learn_node.drag_hud"
    bl_label = "Drag HUD"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        prefs = context.preferences.addons[__name__].preferences
        if prefs.hud_locked:
            return {'FINISHED'}
            
        self.dragging = False
        self.offset_x = 0
        self.offset_y = 0
        
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        prefs = context.preferences.addons[__name__].preferences
        
        if prefs.hud_locked or not prefs.show_hud:
            return {'FINISHED'}
            
        global global_box_height
        box_w = int(350 * prefs.hud_scale)
        box_h = global_box_height
        
        mouse_x = event.mouse_region_x
        mouse_y = event.mouse_region_y
        
        x = prefs.hud_x if prefs.hud_x != -1 else context.region.width - box_w - 20
        start_y = prefs.hud_y if prefs.hud_y != -1 else context.region.height - 20
        y = start_y - box_h
        
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if x <= mouse_x <= x + box_w and y <= mouse_y <= start_y:
                    self.dragging = True
                    self.offset_x = mouse_x - x
                    self.offset_y = mouse_y - start_y
                    
                    if prefs.hud_x == -1: prefs.hud_x = x
                    if prefs.hud_y == -1: prefs.hud_y = start_y
                    
                    return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                self.dragging = False
                
        elif event.type == 'MOUSEMOVE' and self.dragging:
            prefs.hud_x = mouse_x - self.offset_x
            prefs.hud_y = mouse_y - self.offset_y
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
            
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            prefs.hud_locked = True
            context.area.tag_redraw()
            return {'FINISHED'}
            
        if not self.dragging:
            return {'PASS_THROUGH'}
            
        return {'RUNNING_MODAL'}

class NODE_OT_learn_node_unlock_hud(bpy.types.Operator):
    bl_idname = "learn_node.unlock_hud"
    bl_label = "Unlock HUD"
    
    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        prefs.hud_locked = False
        
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            with context.temp_override(window=window, area=area, region=region):
                                bpy.ops.learn_node.drag_hud('INVOKE_DEFAULT')
                            break
        return {'FINISHED'}

class NODE_OT_learn_node_lock_hud(bpy.types.Operator):
    bl_idname = "learn_node.lock_hud"
    bl_label = "Lock HUD"
    
    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        prefs.hud_locked = True
        return {'FINISHED'}


classes = (
    LearnNodePreferences,
    NODE_PT_learn_node,
    NODE_OT_learn_node_reload,
    NODE_OT_learn_node_drag_hud,
    NODE_OT_learn_node_unlock_hud,
    NODE_OT_learn_node_lock_hud
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    global draw_handler
    if draw_handler is None:
        draw_handler = bpy.types.SpaceNodeEditor.draw_handler_add(
            draw_callback_px, (), 'WINDOW', 'POST_PIXEL'
        )

    if not bpy.app.timers.is_registered(refresh_runtime_values):
        bpy.app.timers.register(refresh_runtime_values, first_interval=0.1, persistent=True)

def unregister():
    global draw_handler
    if bpy.app.timers.is_registered(refresh_runtime_values):
        bpy.app.timers.unregister(refresh_runtime_values)
    if draw_handler is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(draw_handler, 'WINDOW')
        draw_handler = None
        
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
