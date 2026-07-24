"""Upload 3 images + batch inference sharing one pipeline load."""
import paramiko, io, time, os

HOST = 'px-cloud2.matpool.com'
PORT = 28105
USER = 'root'
PASSWORD = '1SgWD4Xo12BFBAMR'

BASE = "c:/Users/LX/Documents/xwechat_files/wxid_bquybzk02pir22_89f0/temp/RWTemp/2026-07/ce86d5a2da238b5779e339500caa7e27"
FILES = [
    "b36688a36fb24187dc4a791d27564e1b.jpg",
    "23d235dde3f3e01fe0af3fa561e3cff3.jpg",
    "f2b4ad3db5eeb78b2384d3dd128bfe9e.jpg",
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
sftp = ssh.open_sftp()
print("Connected.\n")

# Upload all 3 images
for f in FILES:
    local = f"{BASE}/{f}"
    remote = f"/root/TRELLIS.2/assets/example_image/{f}"
    print(f"Uploading {f}...")
    sftp.put(local, remote)
print("All 3 uploaded.\n")

# Build the batch inference script
file_list = "', '".join(f"/root/TRELLIS.2/assets/example_image/{f}" for f in FILES)

batch_script = f'''
import os, sys, time, gc
sys.path.insert(0, "/root/TRELLIS.2")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import numpy as np
import torch
from PIL import Image

print(f"GPU: {{torch.cuda.get_device_name(0)}}")

# Load pipeline ONCE
print("\\nLoading pipeline (once)...")
t0 = time.time()
from trellis2.pipelines import Trellis2ImageTo3DPipeline
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
pipeline.low_vram = True
pipeline.default_pipeline_type = '512'
pipeline.cuda()
print(f"  Done in {{time.time()-t0:.1f}}s")

# Envmap
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

import o_voxel

input_files = ['{file_list}']
output_names = ['output_1.glb', 'output_2.glb', 'output_3.glb']

for idx, (input_path, output_name) in enumerate(zip(input_files, output_names)):
    print(f"\\n{{'='*50}}")
    print(f"[{{idx+1}}/3] Processing: {{os.path.basename(input_path)}}")
    print(f"{{'='*50}}")

    image = Image.open(input_path).convert('RGB')
    print(f"  Size: {{image.size}}")

    torch.cuda.empty_cache()
    gc.collect()

    t0 = time.time()
    mesh = pipeline.run(
        image, pipeline_type='512',
        sparse_structure_sampler_params={{'steps': 12}},
        shape_slat_sampler_params={{'steps': 12}},
        tex_slat_sampler_params={{'steps': 12}},
    )[0]
    dt = time.time()-t0

    v = mesh.vertices.cpu().numpy()
    print(f"  Done in {{dt:.1f}}s | Verts: {{v.shape[0]:,}} | Faces: {{mesh.faces.shape[0]:,}}")
    print(f"  X[{{v[:,0].min():.3f}},{{v[:,0].max():.3f}}] Y[{{v[:,1].min():.3f}},{{v[:,1].max():.3f}}] Z[{{v[:,2].min():.3f}},{{v[:,2].max():.3f}}]")

    mesh.simplify(5000000)
    torch.cuda.empty_cache()

    output_path = f"/root/TRELLIS.2/{{output_name}}"
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=500000, texture_size=2048,
        remesh=True, remesh_band=1, remesh_project=0, verbose=False
    )
    glb.export(output_path, extension_webp=True)
    sz_mb = os.path.getsize(output_path) / 1024**2
    print(f"  -> {{output_name}} ({{sz_mb:.1f}} MB)")

print("\\n=== ALL 3 DONE ===")
'''

f = io.BytesIO(batch_script.encode())
sftp.putfo(f, '/tmp/batch_run.py')
print("Running batch inference...")
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/batch_run.py', timeout=1800)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    for line in err.split('\n'):
        if 'Error' in line or 'Traceback' in line:
            print('ERR:', line[:200])

# Download all 3
for i, fname in enumerate(FILES):
    remote = f"/root/TRELLIS.2/output_{i+1}.glb"
    local = f"E:/Python_Study/generate_3Dmodel/output_{i+1}.glb"
    print(f"Downloading output_{i+1}.glb...")
    sftp.get(remote, local)
    print(f"  -> {local}")

ssh.close()
print("\nAll done!")
