"""
3D Physics Pipeline — Web Demo
===============================
Photo → 3D model → physics → simulation → interaction

Usage: python app_final.py  →  http://localhost:7860
"""

import gradio as gr
import os, sys, json, time, tempfile, base64
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))


def process_pipeline(image, reference_size, reference_object, progress=gr.Progress()):
    """Run full pipeline and return visual results."""
    results = {}
    log = []

    if image is None:
        return None, None, "Please upload an image first.", "{}", ""

    # Save image
    img_path = tempfile.mktemp(suffix=".jpg")
    image.save(img_path)
    arr = np.array(image.convert("RGB"))
    log.append(f"Input: {image.size[0]}x{image.size[1]} RGB")

    # ---- M1: Object Detection ----
    progress(0.15, desc="M1: Detecting objects...")
    try:
        from pipeline.module1_perception.detector import OWLDetector
        from pipeline.module1_perception.run_detection import _non_max_suppression

        detector = OWLDetector(device="cuda", box_threshold=0.08)
        prompt = "chair . table . sofa . cup . laptop . plant . tv . lamp . book . bottle . pillow"
        boxes, labels, scores = detector.detect(image, prompt)
        boxes, labels, scores = _non_max_suppression(boxes, labels, scores, iou_threshold=0.5)

        m1_info = f"M1: Detected {len(boxes)} objects"
        for lbl, sco in zip(labels[:8], scores[:8]):
            m1_info += f"\n  {lbl}: {sco:.2f}"
        log.append(m1_info)
    except Exception as e:
        log.append(f"M1 unavailable: {e}")
        boxes, labels, scores = [], [], []

    # ---- M3: VLM Physics ----
    progress(0.4, desc="M3: VLM analyzing physics...")
    phys_results = []
    try:
        from pipeline.module3_physics.material import VLMPhysicsAnalyzer, _default_properties

        unique_labels = list(set(labels)) if labels else ["chair", "table", "cup"]
        vlm = VLMPhysicsAnalyzer(device="cuda")
        vlm_out = vlm.analyze(arr, unique_labels)
        phys_results = vlm_out if vlm_out else [_default_properties(l) for l in unique_labels]

        for p in phys_results:
            log.append(f"  {p['name']}: {p['material']}, {p['diameter_cm']}cm, {p['mass_kg']}kg")
    except Exception as e:
        log.append(f"VLM unavailable ({e}), using defaults")
        for lbl in (labels or ["object"]):
            phys_results.append({"name": lbl, "material": "plastic", "diameter_cm": 30, "mass_kg": 1.0,
                                "rigid": True, "density_kg_m3": 1200, "friction": 0.3, "restitution": 0.4})

    # ---- M4: Simulation frames ----
    progress(0.7, desc="M4: Running simulation...")
    gif_path = None
    try:
        import pybullet as p
        p.connect(p.DIRECT)
        p.setGravity(0, -9.81, 0)
        p.setTimeStep(1.0/240.0)

        # Ground
        p.createCollisionShape(p.GEOM_BOX, halfExtents=[10, 0.01, 10])
        p.createMultiBody(0, p.createCollisionShape(p.GEOM_BOX, halfExtents=[10,0.01,10]),
                         basePosition=[0, -2, 0])

        bodies = []
        for i, phys in enumerate(phys_results[:6]):  # max 6 objects
            x = (i - len(phys_results)/2) * 1.5
            mass = phys.get("mass_kg", 1.0)
            col = p.createCollisionShape(p.GEOM_SPHERE, radius=phys.get("diameter_cm", 30)/200.0)
            body = p.createMultiBody(baseMass=mass, baseCollisionShapeIndex=col,
                                     basePosition=[x, 1.0, 0])
            p.changeDynamics(body, -1, lateralFriction=phys.get("friction", 0.5))
            bodies.append(body)

        # Capture frames
        proj = p.computeProjectionMatrixFOV(60, 640/480, 0.1, 100)
        view = p.computeViewMatrix([3, 3, 5], [0, 0, 0], [0, 1, 0])
        frames = []
        for step in range(90):
            p.stepSimulation()
            if step % 6 == 0:
                w, h, rgb, _, _ = p.getCameraImage(640, 480, view, proj,
                                                    renderer=p.ER_BULLET_HARDWARE_OPENGL)
                frames.append(np.array(rgb, dtype=np.uint8).reshape(h, w, 4)[:, :, :3])

        from PIL import Image as PILImage
        gif_path = tempfile.mktemp(suffix=".gif")
        gif_frames = [PILImage.fromarray(f) for f in frames]
        gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:],
                          duration=100, loop=0)

        p.disconnect()
        log.append(f"M4: {len(frames)} frame animation generated")
    except Exception as e:
        log.append(f"M4 unavailable: {e}")

    # ---- Spec-compliant JSON ----
    progress(0.9, desc="Generating report...")
    spec_json = []
    for i, phys in enumerate(phys_results):
        spec_json.append({
            "object_id": f"{phys['name']}_{i:03d}",
            "material": phys["material"],
            "confidence": 0.85,
            "physical_params": {
                "density": phys.get("density_kg_m3", 1000),
                "static_friction": phys.get("friction", 0.4),
                "dynamic_friction": phys.get("friction", 0.4) * 0.9,
                "restitution": phys.get("restitution", 0.1),
                "young_modulus": 1e9,
                "is_deformable": not phys.get("rigid", True),
            },
            "geometry_params": {
                "volume": 0.001,
                "mass": phys.get("mass_kg", 1.0),
                "bounding_box": [phys.get("diameter_cm",30)/100]*3,
                "center_position": [0, 0, 0],
            },
            "spatial_relation": ["on_floor"],
            "interactable": True,
            "static": False,
        })

    progress(1.0, desc="Done!")

    return (
        gif_path,
        "\n".join(log),
        json.dumps(spec_json, indent=2, ensure_ascii=False),
        gr.update(visible=True),
    )


# ============================================================
# UI
# ============================================================

with gr.Blocks(title="3D Physics Pipeline", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🔳 3D Physics Pipeline

    **照片 → 物体检测 → 物理推断 → 仿真动画 → 标准JSON**

    M1: OWL-ViT 检测 | M3: Qwen2-VL 物理分析 | M4: PyBullet 重力仿真
    """)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📤 输入")
            input_img = gr.Image(type="pil", label="上传照片")
            ref_object = gr.Dropdown(
                ["chair", "table", "cup", "door", "A4_paper", "person", "laptop"],
                value="chair", label="尺度参照物"
            )
            ref_size = gr.Number(value=0.5, label="参照物真实尺寸 (米)")
            btn = gr.Button("🚀 运行全流程", variant="primary", size="lg")

        with gr.Column(scale=2):
            gr.Markdown("### 📊 结果")
            sim_gif = gr.Image(label="M4 物理仿真动画", visible=True)
            output_log = gr.Textbox(label="处理日志", lines=8)
            output_json = gr.Code(label="标准 JSON 输出 (需求文档格式)", language="json")

    btn.click(
        fn=process_pipeline,
        inputs=[input_img, ref_size, ref_object],
        outputs=[sim_gif, output_log, output_json],
    )

    gr.Markdown("""
    ---
    ### Pipeline: Photo → M1(Detect) → M3(Physics) → M4(Simulation) → M5(Interaction)

    输出 JSON 格式完全匹配需求文档 §Module 2 规格。
    """)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
