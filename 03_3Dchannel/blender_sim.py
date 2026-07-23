"""
Blender 物理仿真脚本
==================
在 Blender 进程中运行（通过 blender --background --python 本脚本 -- <参数>）。

工作流程:
  1. 清空默认场景
  2. 导入 GLB 模型
  3. 创建地面（被动刚体）
  4. 为模型设置主动刚体属性
  5. 配置刚体世界
  6. 运行仿真并烘焙
  7. 渲染输出并保存 .blend 文件
"""

import sys
import json
import argparse
import math
import random
from pathlib import Path

# Blender 的 bpy 模块只在 Blender 进程内可用
# 在 IDE 中开发时这些导入会报错，这是正常的
try:
    import bpy
    import mathutils
    INSIDE_BLENDER = True
except ImportError:
    INSIDE_BLENDER = False


# ============================================================
# 常量/默认参数
# ============================================================
DEFAULT_CONFIG = {
    "sim_start_frame": 1,
    "sim_end_frame": 150,
    "sim_substeps": 20,
    "sim_solver_iters": 20,
    "gravity": (0.0, 0.0, -9.81),
    "ground_size": 20.0,
    "ground_height": 0.1,
    "object_mass": 1.0,
    "object_friction": 0.5,
    "object_restitution": 0.1,
    "object_collision_shape": "CONVEX_HULL",
    "object_linear_damping": 0.3,
    "object_angular_damping": 0.4,
    "object_start_z": 5.0,
    "object_random_rotation": True,
    "render_engine": "CYCLES",
    "render_resolution_x": 1920,
    "render_resolution_y": 1080,
    "render_samples": 128,
    "render_output_format": "PNG",
    "render_frame_step": 1,
}


# ============================================================
# 核心函数（仅在 Blender 进程中调用）
# ============================================================

def clear_scene():
    """清空默认场景中的所有对象"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    print("[blender] 🧹 场景已清空")


def create_ground(config: dict):
    """
    创建地面平面 + 被动刚体。

    Args:
        config: 配置字典，包含 ground_size, ground_height, object_friction, object_restitution
    """
    size = config.get("ground_size", 20.0)
    height = config.get("ground_height", 0.1)

    # 创建平面
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, -height / 2))
    ground = bpy.context.active_object
    ground.name = "Ground"

    # 给平面加厚度（用 Solidify 修改器）
    mod = ground.modifiers.new(name="Solidify", type='SOLIDIFY')
    mod.thickness = height

    # 添加材质（灰色）
    mat = bpy.data.materials.new(name="Ground_Material")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1.0)  # 灰色
        bsdf.inputs["Roughness"].default_value = 0.8
    ground.data.materials.append(mat)

    # 设置被动刚体
    bpy.ops.rigidbody.object_add()
    ground.rigid_body.type = 'PASSIVE'
    ground.rigid_body.friction = config.get("object_friction", 0.5)
    ground.rigid_body.restitution = config.get("object_restitution", 0.1)
    ground.rigid_body.collision_shape = 'MESH'

    print(f"[blender] 🟫 地面已创建: {size}×{size}m")
    return ground


def import_glb_model(glb_path: str) -> list:
    """
    导入 GLB 模型到场景中。

    Args:
        glb_path: GLB 文件路径

    Returns:
        导入的对象列表
    """
    glb = Path(glb_path)
    if not glb.exists():
        raise FileNotFoundError(f"GLB 文件不存在: {glb_path}")

    # 记录导入前的对象集合
    before = set(bpy.data.objects)

    bpy.ops.import_scene.gltf(filepath=str(glb_path))

    # 找出新导入的对象
    after = set(bpy.data.objects)
    imported = list(after - before)

    print(f"[blender] 📥 导入模型: {glb.name} ({len(imported)} 个对象)")
    for obj in imported:
        print(f"  - {obj.name} (类型: {obj.type})")

    return imported


def select_mesh_objects(objects: list) -> list:
    """从对象列表中筛选出 MESH 类型的对象"""
    return [o for o in objects if o.type == 'MESH']


def normalize_model_scale(objects: list, target_height: float = 2.0):
    """
    将模型缩放到合适的大小。

    计算所有网格对象的包围盒，缩放到大约 target_height 高度。

    Args:
        objects: 网格对象列表
        target_height: 目标高度（米）
    """
    mesh_objects = select_mesh_objects(objects)
    if not mesh_objects:
        return

    # 计算所有网格的组合包围盒
    all_verts = []
    for obj in mesh_objects:
        for vert in obj.data.vertices:
            world_co = obj.matrix_world @ vert.co
            all_verts.append(world_co)

    if not all_verts:
        return

    all_verts_z = [v.z for v in all_verts]
    current_height = max(all_verts_z) - min(all_verts_z)

    if current_height < 0.001:
        return

    scale_factor = target_height / current_height

    # 缩放到目标根对象（通常是 Armature 或第一个顶层父对象）
    root_objects = [o for o in objects if o.parent is None and o.type != 'MESH']
    if not root_objects:
        root_objects = [o for o in objects if o.parent is None]

    for obj in root_objects if root_objects else objects:
        if obj.parent is None:  # 只缩放顶层对象
            obj.scale *= scale_factor

    print(f"[blender] 📏 模型缩放: {current_height:.2f}m → {target_height:.2f}m (×{scale_factor:.2f})")


def setup_rigid_body_for_objects(objects: list, config: dict):
    """
    为所有网格对象设置主动刚体属性。

    Args:
        objects: 对象列表
        config: 物理参数配置
    """
    mesh_objects = select_mesh_objects(objects)

    if not mesh_objects:
        print("[blender] ⚠️ 没有网格对象可设置刚体")
        return

    for obj in mesh_objects:
        # 确保对象被选中
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # 添加刚体
        bpy.ops.rigidbody.object_add()

        rb = obj.rigid_body
        rb.type = 'ACTIVE'
        rb.mass = config.get("object_mass", 1.0)
        rb.friction = config.get("object_friction", 0.5)
        rb.restitution = config.get("object_restitution", 0.1)
        rb.linear_damping = config.get("object_linear_damping", 0.3)
        rb.angular_damping = config.get("object_angular_damping", 0.4)

        # 碰撞形状
        collision_shape = config.get("object_collision_shape", "CONVEX_HULL")
        try:
            rb.collision_shape = collision_shape
        except TypeError:
            rb.collision_shape = 'CONVEX_HULL'

    print(f"[blender] ⚙️ 已为 {len(mesh_objects)} 个对象设置主动刚体")


def position_objects(objects: list, config: dict):
    """
    将物体放置到初始位置（空中，准备掉落）。

    Args:
        objects: 对象列表
        config: 包含 object_start_z, object_random_rotation
    """
    mesh_objects = select_mesh_objects(objects)
    if not mesh_objects:
        return

    start_z = config.get("object_start_z", 5.0)
    random_rotation = config.get("object_random_rotation", True)

    for obj in mesh_objects:
        # 水平位置居中，Z 轴放在指定高度
        obj.location.x = 0.0
        obj.location.y = 0.0
        obj.location.z = start_z

        if random_rotation:
            obj.rotation_euler = (
                random.uniform(0, 2 * math.pi),
                random.uniform(0, 2 * math.pi),
                random.uniform(0, 2 * math.pi),
            )

        # 关键帧：初始位置
        obj.keyframe_insert(data_path="location", frame=config.get("sim_start_frame", 1))
        obj.keyframe_insert(data_path="rotation_euler", frame=config.get("sim_start_frame", 1))

    print(f"[blender] 📍 物体初始位置: Z={start_z}m")


def setup_rigidbody_world(config: dict):
    """
    配置刚体世界（重力、子步数等）。

    Args:
        config: 包含 gravity, sim_substeps, sim_solver_iters
    """
    scene = bpy.context.scene

    # 如果还没有刚体世界则创建
    if scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()

    rbw = scene.rigidbody_world

    # 重力
    gravity = config.get("gravity", (0, 0, -9.81))
    rbw.effector_weights.gravity = True
    scene.gravity = gravity

    # 求解器质量
    rbw.substeps_per_frame = config.get("sim_substeps", 20)
    rbw.solver_iterations = config.get("sim_solver_iters", 20)

    # 将场景中所有物体链接到刚体世界集合
    collection = rbw.collection
    if collection:
        for obj in scene.objects:
            if obj.rigid_body and obj.name not in collection.objects:
                collection.objects.link(obj)

    print(f"[blender] 🌍 刚体世界配置: 重力={gravity}, 子步={rbw.substeps_per_frame}")


def setup_scene_and_render(config: dict):
    """配置场景帧范围和渲染参数"""
    scene = bpy.context.scene

    # 帧范围
    scene.frame_start = config.get("sim_start_frame", 1)
    scene.frame_end = config.get("sim_end_frame", 150)
    scene.render.fps = 30

    # 渲染引擎
    engine = config.get("render_engine", "CYCLES")
    scene.render.engine = engine

    # 分辨率
    scene.render.resolution_x = config.get("render_resolution_x", 1920)
    scene.render.resolution_y = config.get("render_resolution_y", 1080)
    scene.render.resolution_percentage = 100

    # 输出格式
    fmt = config.get("render_output_format", "PNG")
    scene.render.image_settings.file_format = fmt

    # 采样（Cycles）
    if engine == "CYCLES":
        scene.cycles.samples = config.get("render_samples", 128)

    # 相机设置
    setup_camera()

    # 灯光设置
    setup_lighting()

    print(f"[blender] 🎬 场景配置: {engine}, {scene.render.resolution_x}×{scene.render.resolution_y}")


def setup_camera():
    """设置合适的相机角度（俯瞰视角）"""
    # 创建相机
    bpy.ops.object.camera_add(location=(10, -10, 8))
    camera = bpy.context.active_object
    camera.name = "Simulation_Camera"

    # 让相机看向原点
    direction = mathutils.Vector((0, 0, 0)) - camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    bpy.context.scene.camera = camera
    print("[blender] 📷 相机已设置")


def setup_lighting():
    """添加默认灯光"""
    # 太阳光
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    sun = bpy.context.active_object
    sun.name = "Simulation_Sun"
    sun.data.energy = 5.0
    sun.data.angle = 0.5

    # 环境光（让暗面不那么黑）
    bpy.ops.object.light_add(type='AREA', location=(0, 5, 3))
    fill = bpy.context.active_object
    fill.name = "Simulation_Fill"
    fill.data.energy = 50.0
    fill.data.size = 10.0

    print("[blender] 💡 灯光已设置")


def run_simulation(config: dict):
    """
    运行物理仿真并烘焙到关键帧。

    Args:
        config: 仿真配置
    """
    scene = bpy.context.scene
    start = config.get("sim_start_frame", 1)
    end = config.get("sim_end_frame", 150)

    # 设置帧范围
    scene.frame_start = start
    scene.frame_end = end
    scene.frame_set(start)

    print(f"[blender] ▶️ 开始物理仿真: 帧 {start} → {end}")

    # 烘焙刚体仿真到关键帧
    bpy.ops.rigidbody.bake_to_keyframes(frame_start=start, frame_end=end)

    # 释放缓存
    bpy.ops.ptcache.free_bake()

    print("[blender] ✅ 仿真烘焙完成")


def render_animation(config: dict, output_dir: str):
    """
    渲染仿真结果。

    Args:
        config: 渲染配置
        output_dir: 输出目录
    """
    scene = bpy.context.scene
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 设置输出路径
    scene.render.filepath = str(out / "frame_")

    start = config.get("sim_start_frame", 1)
    end = config.get("sim_end_frame", 150)
    step = config.get("render_frame_step", 1)

    scene.frame_start = start
    scene.frame_end = end

    total_frames = len(range(start, end + 1, step))
    print(f"[blender] 🎥 开始渲染: {total_frames} 帧 → {out}")

    for frame in range(start, end + 1, step):
        scene.frame_set(frame)
        scene.render.filepath = str(out / f"frame_{frame:04d}")
        bpy.ops.render.render(write_still=True)

    print(f"[blender] ✅ 渲染完成!")


def save_blend_file(output_dir: str, name: str = "simulation.blend"):
    """保存 .blend 文件"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    print(f"[blender] 💾 已保存: {path}")


# ============================================================
# 主入口
# ============================================================

def run(glb_path: str, output_dir: str, config: dict):
    """
    运行完整的 Blender 仿真流程。

    Args:
        glb_path: 输入的 GLB 文件路径
        output_dir: 输出目录
        config: 配置字典
    """
    if not INSIDE_BLENDER:
        raise RuntimeError("此脚本必须在 Blender 进程内运行！")

    print("=" * 60)
    print("  Blender 物理仿真流程")
    print("=" * 60)
    print(f"  输入模型: {glb_path}")
    print(f"  输出目录: {output_dir}")

    # 1. 清空场景
    clear_scene()

    # 2. 导入模型
    imported_objects = import_glb_model(glb_path)

    # 3. 缩放模型到合适大小
    normalize_model_scale(imported_objects, target_height=2.0)

    # 4. 创建地面
    create_ground(config)

    # 5. 放置物体
    position_objects(imported_objects, config)

    # 6. 设置刚体属性
    setup_rigid_body_for_objects(imported_objects, config)

    # 7. 配置刚体世界
    setup_rigidbody_world(config)

    # 8. 配置场景和渲染
    setup_scene_and_render(config)

    # 9. 运行仿真
    run_simulation(config)

    # 10. 渲染
    render_animation(config, output_dir)

    # 11. 保存 .blend 文件
    save_blend_file(output_dir)

    print("=" * 60)
    print("  🎉 仿真流程完成！")
    print("=" * 60)


# ============================================================
# CLI 入口（被 subprocess 调用）
# ============================================================

def _parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Blender 物理仿真脚本")
    parser.add_argument("glb_path", help="GLB 模型文件路径")
    parser.add_argument("output_dir", help="输出目录")
    parser.add_argument("--config", default=None, help="JSON 配置文件路径（可选）")
    return parser.parse_args()


def _load_config(config_path: str = None) -> dict:
    """加载配置：JSON 文件 → 合并到默认配置"""
    config = DEFAULT_CONFIG.copy()
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config.update(user_config)
    return config


# 当作为 Blender 脚本运行时:
#   blender --background --python blender_sim.py -- model.glb ./output --config config.json
if INSIDE_BLENDER:
    # Blender 会吃掉 -- 之前的参数，后面的传给脚本
    # sys.argv 在 Blender 中: ['blender_sim.py', '--', 'model.glb', './output', '--config', 'config.json']
    argv = sys.argv
    # 找到 -- 之后的部分
    if "--" in argv:
        script_args = argv[argv.index("--") + 1:]
    else:
        script_args = []

    if len(script_args) >= 2:
        glb_in = script_args[0]
        out_dir = script_args[1]

        config_path = None
        if "--config" in script_args:
            idx = script_args.index("--config")
            if idx + 1 < len(script_args):
                config_path = script_args[idx + 1]

        cfg = _load_config(config_path)
        run(glb_in, out_dir, cfg)
    else:
        print("[blender] ⚠️ 参数不足，用法: blender --background --python blender_sim.py -- <glb_path> <output_dir>")

elif __name__ == "__main__":
    print("=" * 60)
    print("  此脚本需要在 Blender 进程中运行：")
    print("=" * 60)
    print()
    print("  方式1 - 命令行:")
    print('    blender --background --python blender_sim.py -- model.glb ./output')
    print()
    print("  方式2 - 通过 pipeline.py 自动调用")
    print("    python pipeline.py")
    print()
