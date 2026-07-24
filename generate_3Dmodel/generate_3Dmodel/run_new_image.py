"""Upload new image and run TRELLIS.2 inference."""
import paramiko, io

HOST = 'px-cloud2.matpool.com'
PORT = 28105
USER = 'root'
PASSWORD = '1SgWD4Xo12BFBAMR'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
sftp = ssh.open_sftp()
print("Connected.")

# Upload
local_path = "c:/Users/LX/Documents/xwechat_files/wxid_bquybzk02pir22_89f0/temp/RWTemp/2026-07/ce86d5a2da238b5779e339500caa7e27/5b694188072b388bb56c85d5f1776640.jpg"
print("Uploading image...")
sftp.put(local_path, '/root/TRELLIS.2/assets/example_image/new_input.jpg')
print("Uploaded.")

# Run
inference = r'''
import os, sys, time, gc
sys.path.insert(0, "/root/TRELLIS.2")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import numpy as np
import torch
from PIL import Image

print(f"GPU: {torch.cuda.get_device_name(0)}")
mem = torch.cuda.mem_get_info()
print(f"VRAM: free={mem[0]/1e9:.1f}GB")

# Pipeline
print("\n[1/5] Loading pipeline...")
t0 = time.time()
from trellis2.pipelines import Trellis2ImageTo3DPipeline
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
pipeline.low_vram = True
pipeline.default_pipeline_type = '512'
pipeline.cuda()
torch.cuda.empty_cache()
gc.collect()
print(f"  Done in {time.time()-t0:.1f}s")

# Envmap
print("\n[2/5] Envmap...")
from trellis2.renderers import EnvMap
import OpenEXR, Imath

def load_exr(path):
    f = OpenEXR.InputFile(path)
    dw = f.header()['dataWindow']
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    pt = Imath.PixelType(Imath.PixelType.FLOAT)
    rgb = [np.frombuffer(f.channel(c, pt), dtype=np.float32).reshape(h, w) for c in 'RGB']
    return np.stack(rgb, axis=-1)

hdr = load_exr('/root/TRELLIS.2/assets/hdri/forest.exr')
envmap = EnvMap(torch.tensor(hdr, dtype=torch.float32, device='cuda'))

# Image
image = Image.open('/root/TRELLIS.2/assets/example_image/new_input.jpg').convert('RGB')
print(f"\n[3/5] Input: {image.size}")

# Inference
print("\n[4/5] Running inference...")
t0 = time.time()
torch.cuda.empty_cache()
gc.collect()
mesh = pipeline.run(
    image, pipeline_type='512',
    sparse_structure_sampler_params={'steps': 12},
    shape_slat_sampler_params={'steps': 12},
    tex_slat_sampler_params={'steps': 12},
)[0]
dt = time.time()-t0
v = mesh.vertices.cpu().numpy()
print(f"  Done in {dt:.1f}s | Verts: {v.shape[0]:,} | Faces: {mesh.faces.shape[0]:,}")
print(f"  Bounds: X[{v[:,0].min():.3f},{v[:,0].max():.3f}] Y[{v[:,1].min():.3f},{v[:,1].max():.3f}] Z[{v[:,2].min():.3f},{v[:,2].max():.3f}]")

# Export
mesh.simplify(5000000)
torch.cuda.empty_cache()

print("\n[5/5] Exporting GLB...")
t0 = time.time()
import o_voxel

glb = o_voxel.postprocess.to_glb(
    vertices=mesh.vertices, faces=mesh.faces,
    attr_volume=mesh.attrs, coords=mesh.coords,
    attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
    aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
    decimation_target=500000, texture_size=2048,
    remesh=True, remesh_band=1, remesh_project=0, verbose=True
)
output_path = "/root/TRELLIS.2/output_new.glb"
glb.export(output_path, extension_webp=True)
sz_mb = os.path.getsize(output_path) / 1024**2
print(f"\n=== SUCCESS: {output_path} ({sz_mb:.1f} MB) ===")
'''

f = io.BytesIO(inference.encode())
sftp.putfo(f, '/tmp/run_new.py')
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/run_new.py', timeout=1200)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    for line in err.split('\n'):
        if 'Error' in line or 'Traceback' in line:
            print('ERR:', line[:200])

# Download
print("Downloading output_new.glb...")
sftp.get('/root/TRELLIS.2/output_new.glb', 'E:/Python_Study/generate_3Dmodel/output_new.glb')
print("Done -> output_new.glb")
ssh.close()
