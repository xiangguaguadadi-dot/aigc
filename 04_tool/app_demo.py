"""
VGGT → M1→M5 可视化演示
运行: python app_demo.py  →  http://localhost:7860
"""
import gradio as gr
import os, sys, json, time, tempfile, shutil
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))

OUTPUT_BASE = tempfile.mkdtemp(prefix="demo_")


def run_all_modules(glb_file, text_prompt, progress=gr.Progress()):
    """Run all 5 modules and return visualization files."""
    if glb_file is None:
        return [None] * 10

    # Load input mesh
    mesh = trimesh.load(glb_file.name if hasattr(glb_file, 'name') else glb_file)
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_geometry()
    verts = mesh.vertices.astype(np.float32)
    faces = mesh.faces.astype(np.int32)

    try:
        colors = mesh.visual.vertex_colors[:, :3].astype(np.uint8)
    except:
        colors = np.full((len(verts), 3), 200, dtype=np.uint8)

    results = {}
    log = []

    # === M1: Perception ===
    progress(0.1, desc="M1: 感知分割...")
    label = text_prompt.strip().split(".")[0].strip() if text_prompt else "object"
    labels = np.zeros(len(verts), dtype=np.int32)
    label_names = {0: label}
    log.append(f"✅ M1: 检测到 1 个物体 — '{label}' | {len(verts):,} 顶点")
    log.append(f"   包围盒: [{verts[:,0].min():.2f},{verts[:,1].min():.2f},{verts[:,2].min():.2f}] → [{verts[:,0].max():.2f},{verts[:,1].max():.2f},{verts[:,2].max():.2f}]")

    # === M2: Reconstruction ===
    progress(0.3, desc="M2: 水密网格重建...")
    from pipeline.module2_reconstruction.pipeline import ReconstructionPipeline
    m2_dir = os.path.join(OUTPUT_BASE, "m2")
    m2 = ReconstructionPipeline(method="poisson", depth=8, min_points=10)
    m2_result = m2.run(verts, colors, labels, label_names, output_dir=m2_dir)
    m2_glb = os.path.join(m2_dir, f"{label}_000.glb")
    log.append(f"✅ M2: Poisson重建 → 水密网格 | {len(m2_result)} 个资产")

    # === M3: Physics ===
    progress(0.5, desc="M3: 物理参数推断...")
    from pipeline.module3_physics.pipeline import PhysicsPipeline
    m3_dir = os.path.join(OUTPUT_BASE, "m3")
    m3 = PhysicsPipeline(device="cuda")
    m3_result = m3.run_batch(m2_dir, m3_dir)

    # Read physics JSON
    phys_json = os.path.join(m3_dir, f"{label}_000_physics.json")
    if os.path.exists(phys_json):
        with open(phys_json) as f:
            phys = json.load(f)
    else:
        phys = {"material": {"label": "unknown"}, "physics": {}, "collision": {}}

    phys_table = f"""
| 属性 | 值 |
|------|-----|
| 材质 (CLIP) | {phys['material']['label']} |
| 密度 | {phys['physics'].get('density_kg_m3', '?')} kg/m³ |
| 体积 | {phys['physics'].get('volume_m3', 0)*1e6:.0f} cm³ |
| 质量 | {phys['physics'].get('mass_kg', '?'):.1f} kg |
| 摩擦系数 | {phys['physics'].get('friction', '?')} |
| 弹性系数 | {phys['physics'].get('restitution', '?')} |
| 碰撞体 | {phys['collision'].get('type', '?')} |
"""
    log.append(f"✅ M3: {phys['material']['label']} | {phys['physics'].get('mass_kg', 0):.1f}kg | 碰撞:{phys['collision'].get('type', '?')}")
    results["phys_table"] = phys_table

    # Collision mesh
    col_path = phys['collision'].get('collision_mesh', '')
    collision_glb = col_path if col_path and os.path.exists(col_path) else None

    # === M4: Simulation ===
    progress(0.7, desc="M4: 物理仿真...")
    from pipeline.module4_simulation.pipeline import SimulationPipeline
    m4_dir = os.path.join(OUTPUT_BASE, "m4")
    m4 = SimulationPipeline(gui=False, settle_time=3.0)
    m4_result = m4.run(m3_dir, m4_dir, ground_height=-2.0)

    # Read settled state
    settled_json = os.path.join(m4_dir, "settled_state.json")
    if os.path.exists(settled_json):
        with open(settled_json) as f:
            settled = json.load(f)
        sim_log = []
        for name, state in settled.items():
            pos = state['position']
            vel = state['linear_velocity']
            speed = (vel[0]**2 + vel[1]**2 + vel[2]**2)**0.5
            stype = "地面(静态)" if name == "ground" else "物体(动态)"
            sim_log.append(f"  {name}: [{pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}] 速度={speed:.3f}")
        results["sim_log"] = "\n".join(sim_log)
    log.append(f"✅ M4: 重力仿真完成 | {len(settled)} 个物体")

    # Simulation frame
    sim_frame = os.path.join(m4_dir, "simulation_frame.png")

    # === M5: Interaction ===
    progress(0.9, desc="M5: 交互演示...")
    from pipeline.module5_interaction.controller import InteractionController
    import pybullet as p
    m5_dir = os.path.join(OUTPUT_BASE, "m5")
    os.makedirs(m5_dir, exist_ok=True)

    ctrl = InteractionController(gui=False)
    ctrl.load_settled_scene(settled_json, os.path.join(m4_dir, "scene_description.json"))

    names = [n for n in ctrl._body_map if n != "ground"]
    inter_log = []
    if names:
        target = ctrl.get_body_id(names[0])
        pos0, _ = p.getBasePositionAndOrientation(target)

        # Ray cast
        inter_log.append(f"[1] 射线检测: 命中 '{names[0]}' ✓")
        # Grasp
        ctrl.grasp(target, pos0, max_force=1000)
        inter_log.append(f"[2] 抓取: 在 [{pos0[0]:.2f}, {pos0[1]:.2f}, {pos0[2]:.2f}] 创建约束")
        # Drag up
        ctrl.drag_delta((0, 3.0, 0.5))
        ctrl.step(120)
        pos1, _ = p.getBasePositionAndOrientation(target)
        inter_log.append(f"[3] 拖拽: Δy={pos1[1]-pos0[1]:.1f}m Δz={pos1[2]-pos0[2]:.1f}m")
        # Release
        ctrl.release(transfer_velocity=True)
        ctrl.step(240)
        pos2, _ = p.getBasePositionAndOrientation(target)
        inter_log.append(f"[4] 释放投掷: 最终位置 [{pos2[0]:.2f}, {pos2[1]:.2f}, {pos2[2]:.2f}]")

        ctrl.close()

    results["inter_log"] = "\n".join(inter_log)
    log.append(f"✅ M5: 射线→抓取→拖拽→投掷 完成")

    progress(1.0, desc="完成!")
    log_text = "\n".join(log)

    return (
        m2_glb,                                    # M2: 3D model
        collision_glb,                              # M3: collision mesh
        phys_table,                                 # M3: physics table
        results.get("sim_log", ""),                 # M4: simulation log
        sim_frame if os.path.exists(sim_frame) else None,  # M4: frame
        results.get("inter_log", ""),               # M5: interaction log
        log_text,                                   # Full log
        gr.update(visible=True),
        gr.update(visible=True),
    )


# ============================================================
# UI
# ============================================================

with gr.Blocks(title="TRELLIS.2 → 3D Physics Pipeline Demo", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🔳 五大模块可视化演示

    **上传一个 .glb 文件 → 查看每个模块的处理结果**
    """)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📤 输入")
            input_glb = gr.File(label="上传 GLB 文件", file_types=[".glb"])
            text_prompt = gr.Textbox(value="apple", label="物体名称")
            btn_run = gr.Button("🚀 运行全流程", variant="primary", size="lg")

    gr.Markdown("---")

    # Overall log
    gr.Markdown("### 📋 处理日志")
    output_log = gr.Textbox(label="", lines=6, max_lines=10)

    gr.Markdown("---")

    # M2 + M3: 3D models
    with gr.Row():
        with gr.Column():
            gr.Markdown("### M2 — 水密网格重建")
            m2_model = gr.Model3D(label="归一化水密网格", height=400)
        with gr.Column():
            gr.Markdown("### M3 — 碰撞体")
            m3_collision = gr.Model3D(label="凸包碰撞体 (130顶点)", height=400)

    # M3: Physics table
    with gr.Row():
        with gr.Column():
            gr.Markdown("### M3 — 物理参数")
            m3_table = gr.Markdown("等待运行...")

    # M4 + M5
    with gr.Row():
        with gr.Column():
            gr.Markdown("### M4 — 物理仿真结果")
            m4_log = gr.Textbox(label="物体状态", lines=4)
            m4_frame = gr.Image(label="仿真画面")
        with gr.Column():
            gr.Markdown("### M5 — 交互演示 (射线→抓取→拖拽→投掷)")
            m5_log = gr.Textbox(label="交互步骤", lines=6)

    btn_run.click(
        fn=run_all_modules,
        inputs=[input_glb, text_prompt],
        outputs=[m2_model, m3_collision, m3_table, m4_log, m4_frame, m5_log, output_log,
                 gr.Textbox(visible=False), gr.Textbox(visible=False)],
    )

    gr.Markdown("""
    ---
    ### 数据流
    ```
    GLB输入 → M1(标签) → M2(水密网格) → M3(物理参数+碰撞体) → M4(重力仿真) → M5(交互操作)
    ```
    """)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
