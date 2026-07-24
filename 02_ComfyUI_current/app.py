#!/usr/bin/env python3
"""
Gradio Web Demo — One click from photo to physics asset.

Usage: python app.py  (opens http://localhost:7860)
"""

import gradio as gr
import os, sys, time, json, tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))

# Lazy imports — only load when needed
_pipeline_loaded = False


def load_pipeline():
    """Lazy-load pipeline modules (heavy imports)."""
    global _pipeline_loaded
    if _pipeline_loaded:
        return
    print("Loading pipeline modules...")
    t0 = time.time()

    # Import TRELLIS.2 generate
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pre-model"))
    global generate_3d
    from pre_model_generate import generate_3d  # will be set up by user

    # Import pipeline modules
    global SegmentationPipeline, ReconstructionPipeline
    global PhysicsPipeline, SimulationPipeline, InteractionController

    from pipeline.module1_perception.pipeline import SegmentationPipeline
    from pipeline.module2_reconstruction.pipeline import ReconstructionPipeline
    from pipeline.module3_physics.pipeline import PhysicsPipeline
    from pipeline.module4_simulation.pipeline import SimulationPipeline
    from pipeline.module5_interaction.controller import InteractionController

    _pipeline_loaded = True
    print(f"  Pipeline loaded in {time.time()-t0:.1f}s")


# ============================================================
# Step 1: Image → 3D (TRELLIS.2)
# ============================================================

def step1_generate_3d(image):
    """Run TRELLIS.2 on uploaded image."""
    if image is None:
        return None, "Please upload an image first."

    # Save uploaded image
    img_path = tempfile.mktemp(suffix=".jpg")
    image.save(img_path)

    # Run TRELLIS.2 generate.py
    output_glb = tempfile.mktemp(suffix=".glb")
    cmd = f"cd {os.path.dirname(__file__)}/pre-model && python generate.py {img_path} -o {output_glb} --steps 12"
    ret = os.system(cmd)

    if ret != 0 or not os.path.exists(output_glb):
        return None, "Generation failed. Check console for errors."

    size_mb = os.path.getsize(output_glb) / 1024**2
    info = f"3D model generated ({size_mb:.1f} MB)"

    return output_glb, info


# ============================================================
# Step 2: Modules 1-5 Pipeline
# ============================================================

def step2_full_pipeline(glb_path, text_prompt, progress=gr.Progress()):
    """Run modules 1-5 on the generated GLB."""
    if glb_path is None:
        return None, "No 3D model to process."

    load_pipeline()
    output_dir = tempfile.mkdtemp(prefix="pipeline_")
    log = []

    try:
        # ---- M1: Perception ----
        progress(0.1, desc="Module 1: Segmenting objects...")
        import open3d as o3d, numpy as np, trimesh

        mesh = trimesh.load(glb_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)

        # For single-object GLB, M1 is simplified: label from prompt
        label = text_prompt.strip().split(".")[0].strip() if text_prompt else "object"
        log.append(f"M1: Labeled as '{label}'")

        # ---- M2: Reconstruction ----
        progress(0.3, desc="Module 2: Building meshes...")
        m2_dir = os.path.join(output_dir, "m2_assets")
        pipeline_m2 = ReconstructionPipeline(method="poisson", depth=8)
        os.makedirs(m2_dir, exist_ok=True)

        # Export normalized mesh
        from pipeline.module2_reconstruction.exporter import export_asset
        asset_path = export_asset(0, mesh.vertices, mesh.faces, label, m2_dir)
        log.append(f"M2: Exported {asset_path}")

        # ---- M3: Physics ----
        progress(0.5, desc="Module 3: Computing physics...")
        m3_dir = os.path.join(output_dir, "m3_physics")
        pipeline_m3 = PhysicsPipeline(device="cuda")
        m3_result = pipeline_m3.run_from_glb(asset_path, m3_dir)
        log.append(f"M3: {m3_result['material']['label']}, "
                   f"mass={m3_result['physics']['mass_kg']:.1f}kg, "
                   f"collision={m3_result['collision']['type']}")

        # ---- M4: Simulation ----
        progress(0.7, desc="Module 4: Running simulation...")
        m4_dir = os.path.join(output_dir, "m4_simulation")
        pipeline_m4 = SimulationPipeline(gui=False, settle_time=2.0)
        m4_result = pipeline_m4.run(m3_dir, m4_dir)
        log.append(f"M4: Simulated {len(m4_result['scene_graph'].objects)} objects")

        # ---- M5: Interaction ----
        progress(0.9, desc="Module 5: Interaction demo...")
        m5_dir = os.path.join(output_dir, "m5_interaction")
        ctrl = InteractionController(gui=False)
        ctrl.load_settled_scene(
            os.path.join(m4_dir, "settled_state.json"),
            os.path.join(m4_dir, "scene_description.json"),
        )

        # Quick demo
        names = [n for n in ctrl._body_map if n != "ground"]
        if names:
            target = ctrl.get_body_id(names[0])
            import pybullet as p
            pos, _ = p.getBasePositionAndOrientation(target)
            ctrl.grasp(target, pos, max_force=1000)
            ctrl.drag_delta((0, 2.0, 0))
            ctrl.step(120)
            ctrl.release()
            ctrl.step(240)
        states = ctrl.get_all_states()
        ctrl.close()
        log.append(f"M5: Interaction complete — {len(states)} objects in final state")

        # Save log
        with open(os.path.join(output_dir, "pipeline_log.json"), "w") as f:
            json.dump({"log": log, "states": {k: v for k, v in list(states.items())[:10]}}, f, indent=2)

        progress(1.0, desc="Complete!")

        return output_dir, "\n".join(log)

    except Exception as e:
        import traceback
        return None, f"Error: {e}\n{traceback.format_exc()[-500:]}"


# ============================================================
# Gradio UI
# ============================================================

def build_ui():
    with gr.Blocks(title="TRELLIS.2 → 3D Physics Pipeline") as demo:
        gr.Markdown("""
        # 🔳 TRELLIS.2 → 3D Physics Pipeline

        **单张照片 → 3D 模型 → 物理仿真 → 交互资产**

        1. 上传照片 → 生成 3D 模型 (TRELLIS.2)
        2. 五模块管线 → 物理仿真资产
        """)

        with gr.Row():
            with gr.Column(scale=1):
                input_image = gr.Image(type="pil", label="📷 上传照片")
                text_prompt = gr.Textbox(
                    value="chair . table . cup . laptop . plant",
                    label="语义标签 (用 . 分隔)"
                )
                btn_generate = gr.Button("🚀 生成 3D 模型", variant="primary")
                btn_pipeline = gr.Button("🔧 运行全流程管线 (M1→M5)", variant="secondary")

            with gr.Column(scale=2):
                model_3d = gr.Model3D(label="3D 预览")
                output_info = gr.Textbox(label="状态", lines=4)
                pipeline_result = gr.File(label="管线输出目录")

        # Events
        btn_generate.click(
            fn=step1_generate_3d,
            inputs=[input_image],
            outputs=[model_3d, output_info],
        )

        btn_pipeline.click(
            fn=step2_full_pipeline,
            inputs=[model_3d, text_prompt],
            outputs=[pipeline_result, output_info],
        )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
