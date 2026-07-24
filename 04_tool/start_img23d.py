"""Image-to-3D service using TRELLIS.2-4B (local cache only, no network needed)."""
import os
import sys

# IMPORTANT: Set BEFORE any HF imports to prevent network calls
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["ATTN_BACKEND"] = "sdpa"  # Use PyTorch built-in attention (flash_attn not installed)

import time
import tempfile
import cv2
import imageio
from PIL import Image
import torch
import numpy as np
import gradio as gr

# Add TRELLIS.2 to path
sys.path.insert(0, "/root/TRELLIS.2")
os.chdir("/root/TRELLIS.2")

from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.utils import render_utils
from trellis2.renderers import EnvMap
import o_voxel

# Load pipeline from LOCAL cache (no network needed)
CACHE_DIR = "/root/TRELLIS.2-cache"
print(f"Loading TRELLIS.2-4B from local cache: {CACHE_DIR}")

start = time.time()
pipe = Trellis2ImageTo3DPipeline.from_pretrained(CACHE_DIR)
pipe.cuda()
print(f"Pipeline loaded in {time.time() - start:.1f}s")

# Setup EnvMap for preview renders
envmap_path = "assets/hdri/forest.exr"
if os.path.exists(envmap_path):
    envmap = EnvMap(torch.tensor(
        cv2.cvtColor(cv2.imread(envmap_path, cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB),
        dtype=torch.float32, device='cuda'
    ))
else:
    envmap = None
    print("WARNING: No HDRI env map for previews")


def process_image(image, seed_val):
    """Core conversion: image -> 3D mesh -> GLB file + preview video."""
    if image is None:
        return None, None, "Please upload an image first."

    t0 = time.time()
    log_lines = []

    try:
        # Load image
        if isinstance(image, str):
            img = Image.open(image).convert("RGB")
        elif isinstance(image, np.ndarray):
            img = Image.fromarray(image).convert("RGB")
        else:
            img = image.convert("RGB")

        w, h = img.size
        log_lines.append(f"Image: {w}x{h}")

        # Run pipeline (use 512 mode for reliability)
        torch.manual_seed(int(seed_val))
        outputs = pipe.run(img, pipeline_type='512')

        if not outputs or len(outputs) == 0:
            return None, None, "ERROR: No output from pipeline."

        mesh = outputs[0]
        log_lines.append(f"Mesh: {len(mesh.vertices):,} verts, {len(mesh.faces):,} faces")
        log_lines.append(f"Time: {time.time() - t0:.1f}s")

        # Simplify for export
        mesh.simplify(16777216)

        # Export GLB
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=100000,
            texture_size=1024,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )

        glb_path = tempfile.mktemp(suffix=".glb")
        glb.export(glb_path, extension_webp=True)
        glb_size = os.path.getsize(glb_path) / 1024
        log_lines.append(f"GLB: {glb_size:.1f} KB")

        # Preview video
        video_path = None
        if envmap is not None:
            try:
                video_path = tempfile.mktemp(suffix=".mp4")
                video = render_utils.make_pbr_vis_frames(
                    render_utils.render_video(mesh, envmap=envmap)
                )
                imageio.mimsave(video_path, video, fps=15)
                log_lines.append(f"Preview: 360 video ready")
            except Exception as e:
                log_lines.append(f"Preview skipped: {e}")

        log_lines.append(f"Total time: {time.time() - t0:.1f}s")
        return glb_path, video_path, "\n".join(log_lines)

    except Exception as e:
        import traceback
        return None, None, f"ERROR:\n{traceback.format_exc()}"


# ==== Gradio UI ====
css = """
.gradio-container { max-width: 900px !important; margin: auto !important; }
"""

with gr.Blocks(title="Image to 3D - TRELLIS.2", theme=gr.themes.Soft(), css=css) as demo:
    gr.Markdown("""
    # 🎨 Image → 3D Model

    Upload a photo of an object and get a **textured 3D GLB model**.
    Powered by **Microsoft TRELLIS.2-4B** on NVIDIA A100 (40GB).
    """)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📤 Upload Image")
            input_img = gr.Image(label="", type="filepath", height=320)

            seed = gr.Number(label="Random Seed", value=42, precision=0)
            btn = gr.Button("🚀 Generate 3D Model", variant="primary", size="lg")

        with gr.Column(scale=1):
            gr.Markdown("### 📦 Result")
            output_glb = gr.File(label="Download GLB Model")
            output_video = gr.Video(label="360 Preview", height=280)
            output_log = gr.Textbox(label="Details", lines=5)

    btn.click(
        fn=process_image,
        inputs=[input_img, seed],
        outputs=[output_glb, output_video, output_log],
    )

    gr.Markdown("""
    ---
    ### 💡 Tips for best results
    - **Front-facing** object, well-lit, simple background
    - Works best with: furniture, toys, electronics, sculptures, vehicles
    - GLB files open in: Blender, Windows 3D Viewer, Unity, Unreal, web viewers
    """)

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Starting Image-to-3D service on port 7860...")
    print("=" * 50)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )
