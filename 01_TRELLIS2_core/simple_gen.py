"""Exactly the same method as the chair - no patching, no trimesh."""
import paramiko, io, os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ.get('A100_HOST', 'px-cloud2.matpool.com'), port=int(os.environ.get('A100_PORT', '28105')), username=os.environ.get('A100_USER', 'root'), password=os.environ.get('A100_PASSWORD', ''), timeout=30)
sftp = ssh.open_sftp()

script = r'''
import os, sys, time, gc
sys.path.insert(0, "/root/TRELLIS.2")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import numpy as np, torch
from PIL import Image

print(f"GPU: {torch.cuda.get_device_name(0)}")

from trellis2.pipelines import Trellis2ImageTo3DPipeline
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
pipeline.low_vram = True; pipeline.default_pipeline_type = '512'
pipeline.cuda(); torch.cuda.empty_cache(); gc.collect()

from trellis2.renderers import EnvMap
import OpenEXR, Imath
def load_exr(path):
    f = OpenEXR.InputFile(path); dw = f.header()['dataWindow']
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    pt = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.stack([np.frombuffer(f.channel(c, pt), dtype=np.float32).reshape(h, w) for c in 'RGB'], axis=-1)
hdr = load_exr('/root/TRELLIS.2/assets/hdri/forest.exr')
EnvMap(torch.tensor(hdr, dtype=torch.float32, device='cuda'))

img = Image.open("/root/TRELLIS.2/assets/example_image/oneshot.jpg").convert('RGB')
print(f"Input: {img.size}")

torch.cuda.empty_cache(); gc.collect()
t0 = time.time()
mesh = pipeline.run(img, pipeline_type='512',
    sparse_structure_sampler_params={'steps': 12},
    shape_slat_sampler_params={'steps': 12},
    tex_slat_sampler_params={'steps': 12})[0]
v = mesh.vertices.cpu().numpy()
print(f"Done {time.time()-t0:.1f}s | Verts: {v.shape[0]:,}")

mesh.simplify(5000000); torch.cuda.empty_cache()

import o_voxel
glb = o_voxel.postprocess.to_glb(
    vertices=mesh.vertices, faces=mesh.faces,
    attr_volume=mesh.attrs, coords=mesh.coords,
    attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
    aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
    decimation_target=500000, texture_size=2048,
    remesh=True, remesh_band=1, remesh_project=0, verbose=False)
out = "/root/TRELLIS.2/output_simple.glb"
glb.export(out, extension_webp=True)
print(f"-> output_simple.glb ({os.path.getsize(out)/1024**2:.1f} MB)")
'''

f = io.BytesIO(script.encode())
sftp.putfo(f, '/tmp/simple_gen.py')
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/simple_gen.py', timeout=1200)
print(stdout.read().decode())
err = stderr.read().decode()
for line in err.split('\n'):
    if 'Error' in line or 'Traceback' in line: print('ERR:', line[:200])

print("Downloading...")
sftp.get('/root/TRELLIS.2/output_simple.glb', 'E:/Python_Study/generate_3Dmodel/output_simple.glb')
print("Done -> output_simple.glb")
ssh.close()
