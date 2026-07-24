"""Run A/B/C/D experiment on MatPool A100."""
import paramiko, io, os, time

HOST = 'px-cloud2.matpool.com'
PORT = 28105
USER = 'root'
PASSWORD = '1SgWD4Xo12BFBAMR'

LABELS = ['A-SoftLight', 'B-HardLight', 'C-Droplets', 'D-ComplexBG']
IMAGES = ['A.jpg', 'B.jpg', 'C.jpg', 'D.jpg']

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
sftp = ssh.open_sftp()
print("Connected to A100\n")

# Upload images
for img, lbl in zip(IMAGES, LABELS):
    local = f"E:/Python_Study/generate_3Dmodel/{img}"
    remote = f"/root/TRELLIS.2/assets/example_image/exp_{lbl}.jpg"
    print(f"Uploading {img}...")
    sftp.put(local, remote)
print("All uploaded.\n")

# Build batch inference script
jobs = []
for lbl in LABELS:
    jobs.append((f"/root/TRELLIS.2/assets/example_image/exp_{lbl}.jpg",
                 f"/root/TRELLIS.2/output_exp_{lbl}.glb",
                 lbl))

job_lines = ", ".join(f'("{img}", "{glb}", "{lbl}")' for img, glb, lbl in jobs)

batch_script = f'''
import os, sys, time, gc
sys.path.insert(0, "/root/TRELLIS.2")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import numpy as np, torch, json
from PIL import Image

print(f"GPU: {{torch.cuda.get_device_name(0)}}")

from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.renderers import EnvMap
import OpenEXR, Imath

# Load once
print("Loading pipeline...")
t0 = time.time()
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/root/TRELLIS.2-cache")
pipeline.low_vram = True; pipeline.default_pipeline_type = "512"
pipeline.cuda(); torch.cuda.empty_cache(); gc.collect()
print(f"  Done in {{time.time()-t0:.1f}}s")

def load_exr(path):
    f = OpenEXR.InputFile(path); dw = f.header()["dataWindow"]
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    pt = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.stack([np.frombuffer(f.channel(c, pt), dtype=np.float32).reshape(h, w) for c in "RGB"], axis=-1)

hdr = load_exr("/root/TRELLIS.2/assets/hdri/forest.exr")
EnvMap(torch.tensor(hdr, dtype=torch.float32, device="cuda"))

import o_voxel

jobs = [{job_lines}]
results = []

for img_path, glb_path, label in jobs:
    print(f"\\n{{'='*40}}")
    print(f"[{{label}}]")
    print(f"{{'='*40}}")

    img = Image.open(img_path).convert("RGB")
    print(f"  Size: {{img.size}}")
    torch.cuda.empty_cache(); gc.collect()

    t0 = time.time()
    mesh = pipeline.run(img, pipeline_type="512",
        sparse_structure_sampler_params={{"steps": 12}},
        shape_slat_sampler_params={{"steps": 12}},
        tex_slat_sampler_params={{"steps": 12}})[0]
    dt = time.time() - t0

    v = mesh.vertices.cpu().numpy()
    print(f"  Done in {{dt:.1f}}s | Verts: {{v.shape[0]:,}} | Faces: {{mesh.faces.shape[0]:,}}")
    print(f"  X[{{v[:,0].min():.3f}},{{v[:,0].max():.3f}}] Y[{{v[:,1].min():.3f}},{{v[:,1].max():.3f}}] Z[{{v[:,2].min():.3f}},{{v[:,2].max():.3f}}]")
    print(f"  Attrs: {{mesh.attrs.shape[1]}}ch, mean RGB [{{mesh.attrs[:,0].mean():.3f}},{{mesh.attrs[:,1].mean():.3f}},{{mesh.attrs[:,2].mean():.3f}}]")

    # Save mesh data for local analysis
    np.savez(f"/tmp/exp_mesh_{{{{label}}}}.npz",
        vertices=mesh.vertices.cpu().numpy(),
        faces=mesh.faces.cpu().numpy(),
        attrs=mesh.attrs.cpu().numpy())

    mesh.simplify(5000000); torch.cuda.empty_cache()

    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=500000, texture_size=2048,
        remesh=True, remesh_band=1, remesh_project=0, verbose=False)

    glb.export(glb_path, extension_webp=True)
    sz_mb = os.path.getsize(glb_path) / 1024**2
    print(f"  -> {{glb_path}} ({{sz_mb:.1f}} MB)")

print("\\n=== ALL DONE ===")
'''

f = io.BytesIO(batch_script.encode())
sftp.putfo(f, '/tmp/exp_batch.py')
print("Running batch inference on A100...")
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/exp_batch.py', timeout=1200)
out = stdout.read().decode()
print(out)
err = stderr.read().decode()
for line in err.split('\n'):
    if 'Error' in line or 'Traceback' in line:
        print('ERR:', line[:200])

# Download results
os.makedirs("E:/Python_Study/generate_3Dmodel/results", exist_ok=True)
for lbl in LABELS:
    glb = f"/root/TRELLIS.2/output_exp_{lbl}.glb"
    local_glb = f"E:/Python_Study/generate_3Dmodel/results/{lbl}.glb"
    print(f"Downloading {lbl}.glb...")
    sftp.get(glb, local_glb)
    # Download NPZ
    npz = f"/tmp/exp_mesh_{lbl}.npz"
    local_npz = local_glb.replace('.glb', '.npz')
    try:
        sftp.get(npz, local_npz)
        print(f"  + {lbl}.npz")
    except:
        pass

ssh.close()
print("\nDone! Results in results/")
