#!/usr/bin/env python3
"""
TRELLIS.2 Web Demo — 图片上传 → A100 推理 → 3D 预览
Usage: python app.py    (opens http://localhost:7860)
"""
import gradio as gr
import paramiko, io, os, time, tempfile, uuid

HOST = os.environ.get('A100_HOST', 'px-cloud2.matpool.com')
PORT = int(os.environ.get('A100_PORT', '28105'))
USER = os.environ.get('A100_USER', 'root')
PASSWORD = os.environ.get('A100_PASSWORD', '')


def generate_3d(image, steps=12):
    """Upload image to A100, run TRELLIS.2, return GLB path and info."""
    if image is None:
        return None, "请先上传图片", ""

    # Save uploaded image locally
    img_path = f"/tmp/upload_{uuid.uuid4().hex[:8]}.jpg"
    image.save(img_path)

    # Connect to server
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)
        sftp = ssh.open_sftp()
    except Exception as e:
        return None, f"❌ 无法连接 GPU 服务器: {e}", ""

    try:
        # Upload image
        remote_img = f"/root/TRELLIS.2/demo_input.jpg"
        sftp.put(img_path, remote_img)

        # Run inference script on server
        script = f'''
import os, sys, time, gc
sys.path.insert(0, "/root/TRELLIS.2")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import numpy as np, torch
from PIL import Image

from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.renderers import EnvMap
import OpenEXR, Imath

pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
pipeline.low_vram = True; pipeline.default_pipeline_type = "512"
pipeline.cuda(); torch.cuda.empty_cache(); gc.collect()

f = OpenEXR.InputFile("/root/TRELLIS.2/assets/hdri/forest.exr")
dw = f.header()["dataWindow"]
w, h = dw.max.x-dw.min.x+1, dw.max.y-dw.min.y+1
pt = Imath.PixelType(Imath.PixelType.FLOAT)
hdr = np.stack([np.frombuffer(f.channel(c,pt),dtype=np.float32).reshape(h,w) for c in "RGB"], axis=-1)
EnvMap(torch.tensor(hdr, dtype=torch.float32, device="cuda"))

img = Image.open("{remote_img}").convert("RGB")
print(f"SIZE:{{img.size[0]}}x{{img.size[1]}}")

torch.cuda.empty_cache(); gc.collect()
t0 = time.time()
mesh = pipeline.run(img, pipeline_type="512",
    sparse_structure_sampler_params={{"steps": {steps}}},
    shape_slat_sampler_params={{"steps": {steps}}},
    tex_slat_sampler_params={{"steps": {steps}}})[0]

v = mesh.vertices.cpu().numpy()
dt = time.time()-t0
print(f"TIME:{{dt:.1f}}")
print(f"VERTS:{{v.shape[0]}}")
print(f"FACES:{{mesh.faces.shape[0]}}")
print(f"ATTRS:{{mesh.attrs.shape[1]}}ch")
print(f"RGB:[{{mesh.attrs[:,0].mean():.3f}},{{mesh.attrs[:,1].mean():.3f}},{{mesh.attrs[:,2].mean():.3f}}]")

mesh.simplify(5000000); torch.cuda.empty_cache()

import o_voxel
glb = o_voxel.postprocess.to_glb(
    vertices=mesh.vertices, faces=mesh.faces,
    attr_volume=mesh.attrs, coords=mesh.coords,
    attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
    aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
    decimation_target=500000, texture_size=2048,
    remesh=True, remesh_band=1, remesh_project=0, verbose=False)
glb.export("/root/TRELLIS.2/demo_output.glb", extension_webp=True)
print("DONE")
'''

        f = io.BytesIO(script.encode())
        sftp.putfo(f, '/tmp/demo_run.py')

        # Run
        stdin, stdout, stderr = ssh.exec_command('python3 /tmp/demo_run.py', timeout=600)
        out = stdout.read().decode()
        err = stderr.read().decode()

        # Parse output
        info = {}
        for line in out.split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                info[k.strip()] = v.strip()

        img_size = info.get('SIZE', '?')
        gen_time = info.get('TIME', '?')
        verts = info.get('VERTS', '?')
        faces = info.get('FACES', '?')
        rgb = info.get('RGB', '?')

        if 'DONE' not in out:
            return None, f"❌ 推理失败\n{err[:500]}", ""

        # Download result
        out_path = f"{tempfile.gettempdir()}/demo_{uuid.uuid4().hex[:8]}.glb"
        sftp.get('/root/TRELLIS.2/demo_output.glb', out_path)

        info_text = f"""
        ✅ 生成成功！
        ⏱ 推理时间: {gen_time}秒
        📐 顶点数: {verts}  |  面数: {faces}
        🎨 纹理RGB: {rgb}
        📷 输入尺寸: {img_size}
        """.strip()

        ssh.close()
        return out_path, info_text, out_path

    except Exception as e:
        try: ssh.close()
        except: pass
        return None, f"❌ 错误: {e}", ""


# ── Gradio UI ──────────────────────────────────────────

with gr.Blocks(title="TRELLIS.2 3D Generator", theme=gr.themes.Soft()) as app:
    gr.Markdown("""
    # 🧊 TRELLIS.2 Image-to-3D Generator
    上传一张图片，AI 自动生成带 PBR 材质的 3D 模型。
    """)

    with gr.Row():
        with gr.Column(scale=1):
            input_img = gr.Image(label="📷 上传图片", type="pil", height=300)
            steps = gr.Slider(4, 20, value=12, step=2, label="⚙ 采样步数 (越少越快)")
            btn = gr.Button("🚀 生成 3D 模型", variant="primary", size="lg")

        with gr.Column(scale=1):
            output_3d = gr.Model3D(label="🎯 3D 预览", height=350)
            download_btn = gr.DownloadButton("💾 下载 GLB", variant="secondary")
            info = gr.Textbox(label="📊 生成信息", lines=6)

    btn.click(
        fn=generate_3d,
        inputs=[input_img, steps],
        outputs=[output_3d, info, download_btn],
    )

    gr.Markdown("""
    ---
    **硬件**: NVIDIA A100 40GB  |  **模型**: TRELLIS.2-4B (512 mode)  |  **PBR**: baseColor + metallic + roughness
    """)


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
