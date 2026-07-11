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

def draw_text_multiline(font_id, text, x, y, max_width, size=16, color=(1,1,1,1)):
    blf.size(font_id, size)
    blf.color(font_id, *color)
    
    lines = []
    for paragraph in str(text).split('\n'):
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            width, _ = blf.dimensions(font_id, test_line)
            if width <= max_width:
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
    shader.uniform_float("color", (0.1, 0.1, 0.1, 0.85))
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    
    # Draw Lock Warning if unlocked
    if not prefs.hud_locked:
        shader.uniform_float("color", (0.8, 0.2, 0.2, 0.5))
        # Draw a small border or highlight
        batch.draw(shader)
    
    # Draw Text
    font_id = 0
    text_x = x + 15
    text_y = start_y - 30
    
    if node_info:
        # Title
        blf.size(font_id, int(24 * scale))
        blf.color(font_id, 1, 0.8, 0.2, 1)
        blf.position(font_id, text_x, text_y, 0)
        blf.draw(font_id, node_info.get("name", active_node.name))
        text_y -= int(40 * scale)
        
        # Description
        desc = node_info.get("description", "")
        text_y = draw_text_multiline(font_id, desc, text_x, text_y, box_width - int(30 * scale), size=int(16 * scale))
        text_y -= int(10 * scale)
        
        # Inputs
        valid_inputs = [socket for socket in active_node.inputs if not socket.hide and not socket.is_unavailable]
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
                
                trans_name = trans
                trans_desc = ""
                if isinstance(trans, dict):
                    trans_name = trans.get("name", "")
                    trans_desc = trans.get("description", "")
                
                display_text = f"- {socket.name}: {trans_name}" if trans_name else f"- {socket.name}"
                if trans_desc:
                    display_text += f"\n   {trans_desc}"
                    
                text_y = draw_text_multiline(font_id, display_text, text_x, text_y, box_width - int(30 * scale), size=int(14 * scale))
                
        text_y -= int(10 * scale)
        
        # Outputs
        valid_outputs = [socket for socket in active_node.outputs if not socket.hide and not socket.is_unavailable]
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
                
                trans_name = trans
                trans_desc = ""
                if isinstance(trans, dict):
                    trans_name = trans.get("name", "")
                    trans_desc = trans.get("description", "")
                
                display_text = f"- {socket.name}: {trans_name}" if trans_name else f"- {socket.name}"
                if trans_desc:
                    display_text += f"\n   {trans_desc}"
                    
                text_y = draw_text_multiline(font_id, display_text, text_x, text_y, box_width - int(30 * scale), size=int(14 * scale))
    else:
        # Fallback if node not found
        blf.size(font_id, int(20 * scale))
        blf.color(font_id, 1, 1, 1, 1)
        blf.position(font_id, text_x, text_y, 0)
        blf.draw(font_id, active_node.name)
        text_y -= int(30 * scale)
        text_y = draw_text_multiline(font_id, "ยังไม่มีคำอธิบายสำหรับ Node นี้ในระบบ", text_x, text_y, box_width - int(30 * scale), size=int(16 * scale))

    # Calculate actual height for next frame's box drawing
    global_box_height = start_y - text_y + 20


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
        default=1.0, min=0.5, max=3.0, step=10
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
        
        layout.prop(prefs, "show_hud", text="เปิดแสดงผล (HUD)", toggle=True)
        
        if prefs.hud_locked:
            layout.operator("learn_node.unlock_hud", text="ปลดล็อคเพื่อลาก (Unlock)", icon='UNLOCKED')
        else:
            layout.operator("learn_node.lock_hud", text="ล็อคตำแหน่ง (Lock)", icon='LOCKED')
            
        layout.separator()
        layout.operator("learn_node.reload_data", text="โหลดข้อมูล JSON ใหม่", icon='FILE_REFRESH')


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

def unregister():
    global draw_handler
    if draw_handler is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(draw_handler, 'WINDOW')
        draw_handler = None
        
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
