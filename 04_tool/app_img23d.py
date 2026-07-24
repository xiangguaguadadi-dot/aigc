"""Start TRELLIS image-to-3D Gradio app using local cached model."""
import os
import sys

# Force use of HF mirror for any API calls
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

# TRELLIS setup
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

os.chdir("/root/TRELLIS.2")
sys.path.insert(0, "/root/TRELLIS.2")

import cv2
import imageio
from PIL import Image
import torch
import numpy as np
import gradio as gr
import tempfile
import shutil

from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.utils import render_utils
from trellis2.renderers import EnvMap
import o_voxel

# Setup EnvMap from local assets
envmap_path = "assets/hdri/forest.exr"
if os.path.exists(envmap_path):
    envmap = EnvMap(torch.tensor(
        cv2.cvtColor(cv2.imread(envmap_path, cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB),
        dtype=torch.float32, device='cuda'
    ))
else:
    envmap = None

# Load pipeline from local cache
CACHE_DIR = "/root/TRELLIS.2-cache"
print("Loading TRELLIS.2-4B pipeline from local cache...")
pipe = Trellis2ImageTo3DPipeline.from_pretrained(f"{CACHE_DIR}/pipeline")
pipe.cuda()
print("Model loaded successfully!")


def image_to_3d(input_image, seed=42, texture_resolution=1024, simplify_faces=50000):
    """Convert input image to 3D GLB mesh."""
    if input_image is None:
        return None, None, "Please upload an image first."

    try:
        # Load image
        if isinstance(input_image, str):
            img = Image.open(input_image).convert("RGB")
        elif isinstance(input_image, np.ndarray):
            img = Image.fromarray(input_image).convert("RGB")
        else:
            img = input_image.convert("RGB")

        w, h = img.size
        progress_msg = f"Input: {w}x{h} image | Generating 3D model..."

        # Run TRELLIS pipeline
        torch.manual_seed(int(seed))
        outputs = pipe.run(img)

        if not outputs or len(outputs) == 0:
            return None, None, "Generation failed: no output from pipeline."

        mesh = outputs[0]
        progress_msg += f"\nMesh generated: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces"

        # Simplify mesh
        target = min(int(simplify_faces), 16777216)
        mesh.simplify(target)
        progress_msg += f"\nSimplified to: {len(mesh.faces)} faces"

        # Export to GLB
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=target,
            texture_size=texture_resolution,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=True
        )

        # Save to temp file
        output_path = tempfile.mktemp(suffix=".glb")
        glb.export(output_path, extension_webp=True)

        file_size = os.path.getsize(output_path) / 1024
        progress_msg += f"\nExported GLB: {file_size:.1f} KB"

        # Generate preview video (optional)
        preview_path = None
        if envmap is not None:
            try:
                preview_path = tempfile.mktemp(suffix=".mp4")
                video = render_utils.make_pbr_vis_frames(
                    render_utils.render_video(mesh, envmap=envmap)
                )
                imageio.mimsave(preview_path, video, fps=15)
                progress_msg += f"\nPreview video generated"
            except Exception as e:
                progress_msg += f"\nPreview skipped: {e}"

        return output_path, preview_path, progress_msg

    except Exception as e:
        import traceback
        return None, None, f"Error: {traceback.format_exc()}"


# Build Gradio UI
with gr.Blocks(title="Image-to-3D (TRELLIS.2)", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🎨 Image to 3D Model — TRELLIS.2

    Upload a photo of an object → get a **textured 3D GLB model** you can download and use.
    Powered by Microsoft TRELLIS.2-4B on NVIDIA A100.
    """)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📤 Input")
            input_img = gr.Image(label="Upload Image", type="filepath", height=300)

            with gr.Row():
                seed = gr.Number(label="Seed", value=42, precision=0)
                tex_res = gr.Slider(label="Texture Resolution", minimum=512, maximum=2048, value=1024, step=256)
            simplify = gr.Slider(label="Max Faces", minimum=10000, maximum=200000, value=50000, step=10000)

            btn = gr.Button("🚀 Generate 3D Model", variant="primary", size="lg")

        with gr.Column(scale=1):
            gr.Markdown("### 📦 Output")
            output_glb = gr.File(label="Download 3D Model (GLB)")
            output_video = gr.Video(label="360 Preview", height=300)
            output_log = gr.Textbox(label="Status", lines=6)

    btn.click(
        fn=image_to_3d,
        inputs=[input_img, seed, tex_res, simplify],
        outputs=[output_glb, output_video, output_log],
    )

    gr.Markdown("""
    ---
    ### 💡 Tips
    - Best results: front-facing object, good lighting, clean background
    - GLB files can be opened in Blender, Windows 3D Viewer, or any 3D software
    - Higher texture resolution = better quality but larger file size
    """)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7861, share=False)
