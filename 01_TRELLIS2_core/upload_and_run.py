"""Upload chair image and run TRELLIS.2 inference."""
import paramiko, os

HOST = os.environ.get('A100_HOST', 'px-cloud2.matpool.com')
PORT = int(os.environ.get('A100_PORT', '28105'))
USER = os.environ.get('A100_USER', 'root')
PASSWORD = os.environ.get('A100_PASSWORD', '')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
sftp = ssh.open_sftp()
print("Connected.")

# Upload the chair image
print("Uploading chair_input.jpg...")
sftp.put('E:/Python_Study/generate_3Dmodel/chair_input.jpg', '/root/TRELLIS.2/assets/example_image/chair_input.jpg')
print("Uploaded.")

# Run inference
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
print(f"VRAM: free={mem[0]/1e9:.1f}GB / total={mem[1]/1e9:.1f}GB")

# Load pipeline
print("\n[1/5] Loading pipeline...")
t0 = time.time()
from trellis2.pipelines import Trellis2ImageTo3DPipeline
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
pipeline.low_vram = True
pipeline.default_pipeline_type = '512'
pipeline.cuda()
torch.cuda.empty_cache()
gc.collect()
print(f"  Loaded in {time.time()-t0:.1f}s")

# Envmap
print("\n[2/5] Loading envmap...")
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

# Input - the chair
input_path = '/root/TRELLIS.2/assets/example_image/chair_input.jpg'
image = Image.open(input_path).convert('RGB')
print(f"\n[3/5] Input: {image.size}")

# Inference
print("\n[4/5] Running inference...")
t0 = time.time()
torch.cuda.empty_cache()
gc.collect()
mesh = pipeline.run(
    image,
    pipeline_type='512',
    sparse_structure_sampler_params={'steps': 12},
    shape_slat_sampler_params={'steps': 12},
    tex_slat_sampler_params={'steps': 12},
)[0]
print(f"  Done in {time.time()-t0:.1f}s")
v = mesh.vertices.cpu().numpy()
print(f"  Vertices: {v.shape[0]:,}, Faces: {mesh.faces.shape[0]:,}")
print(f"  Bounds: [{v[:,0].min():.3f},{v[:,1].min():.3f},{v[:,2].min():.3f}] to [{v[:,0].max():.3f},{v[:,1].max():.3f},{v[:,2].max():.3f}]")

# Simplify + Export
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
output_path = "/root/TRELLIS.2/output_chair.glb"
glb.export(output_path, extension_webp=True)
sz_mb = os.path.getsize(output_path) / 1024**2
print(f"\n=== SUCCESS: {output_path} ({sz_mb:.1f} MB) ===")
'''

import io
f = io.BytesIO(inference.encode())
sftp.putfo(f, '/tmp/run_chair.py')
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/run_chair.py', timeout=1200)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    for line in err.split('\n'):
        if 'Error' in line or 'Traceback' in line:
            print('ERR:', line[:200])

# Download result
print("Downloading output_chair.glb...")
sftp.get('/root/TRELLIS.2/output_chair.glb', 'E:/Python_Study/generate_3Dmodel/output_chair.glb')
print("Downloaded to output_chair.glb")

ssh.close()
