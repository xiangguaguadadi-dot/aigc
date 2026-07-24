"""
Execute SETUP_SERVER.md steps 1-8 on the cloud server via paramiko.
"""
import paramiko
import sys
import time
import os

HOST = os.environ.get('A100_HOST', 'px-cloud1.matpool.com')
PORT = int(os.environ.get('A100_PORT', '27258'))
USER = os.environ.get('A100_USER', 'root')
PASSWORD = os.environ.get('A100_PASSWORD', '')

def ssh_command(ssh, cmd, timeout=120):
    """Run a command and print stdout/stderr in real time."""
    print(f"\n{'='*60}")
    print(f"$ {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
    print('='*60)
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    # Read stdout
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out:
        print(out)
    if err:
        print("[STDERR]", err)
    return out, err

def main():
    print(f"Connecting to {USER}@{HOST}:{PORT} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
        print("Connected!")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    # ---- Step 1: Verify environment ----
    print("\n### Step 1: Verify environment ###")
    ssh_command(ssh, "nvidia-smi")
    ssh_command(ssh, "python3 --version")
    ssh_command(ssh, "df -h /root/")

    # ---- Step 2: Install pip packages ----
    print("\n### Step 2: Install missing pip packages ###")
    ssh_command(ssh, "pip install -q scipy matplotlib 2>&1 | tail -3", timeout=120)

    # ---- Step 3: Download SAM weights ----
    print("\n### Step 3: Download SAM weights (2.4GB) ###")
    ssh_command(ssh, "mkdir -p /root/module1/model_weights")
    ssh_command(ssh,
        'wget -O /root/module1/model_weights/sam_vit_h_4b8939.pth '
        '"https://hf-mirror.com/HCMUE-Research/SAM-vit-h/resolve/main/sam_vit_h_4b8939.pth?download=true"',
        timeout=600)
    ssh_command(ssh, "ls -lh /root/module1/model_weights/sam_vit_h_4b8939.pth")

    # ---- Step 4: Cache Qwen2-VL-2B ----
    print("\n### Step 4: Cache Qwen2-VL-2B ###")
    ssh_command(ssh,
        'python3 -c "'
        'from modelscope import snapshot_download; '
        "p = snapshot_download('Qwen/Qwen2-VL-2B-Instruct'); "
        'print(p)"',
        timeout=300)
    ssh_command(ssh, "du -sh /root/.cache/modelscope/models/Qwen--Qwen2-VL-2B-Instruct/")

    # ---- Step 5: Verify OWL-ViT ----
    print("\n### Step 5: Verify OWL-ViT ###")
    ssh_command(ssh,
        'HF_ENDPOINT=https://hf-mirror.com python3 -c "'
        "from transformers import pipeline; "
        "p = pipeline('zero-shot-object-detection', model='google/owlvit-base-patch32'); "
        "print('OWL-ViT OK')\"",
        timeout=120)

    # ---- Step 6: Verify CLIP ----
    print("\n### Step 6: Verify CLIP ###")
    ssh_command(ssh,
        'HF_ENDPOINT=https://hf-mirror.com python3 -c "'
        "from transformers import CLIPModel; "
        "m = CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); "
        "print('CLIP OK')\"",
        timeout=120)

    # ---- Step 7: Full pipeline test ----
    print("\n### Step 7: Full pipeline test ###")
    ssh_command(ssh,
        'cd /root/trellis2-pipeline && python3 -c "'
        "import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'pipeline'); "
        "from pipeline.colmap_io import load_colmap_poses; "
        "from pipeline.engineering import calibrate_scale, make_watertight; "
        "from pipeline.spec_compliant import infer_properties, to_spec_json; "
        "from pipeline.production import ProductionPipeline; "
        "print('All modules OK')\"")

    ssh_command(ssh,
        'cd /root/trellis2-pipeline && python3 -c "'
        "from pipeline.production import demo; demo()\"",
        timeout=300)

    ssh_command(ssh,
        'cd /root/trellis2-pipeline && '
        'HF_ENDPOINT=https://hf-mirror.com python3 '
        'pipeline/module1_perception/run_detection.py '
        '--image room_photo.jpg '
        '--prompt "sofa . chair . table . laptop . plant . tv . lamp" '
        '--threshold 0.05',
        timeout=120)

    # ---- Step 8: Verify outputs ----
    print("\n### Step 8: Verify outputs ###")
    ssh_command(ssh, "ls -lh /root/trellis2-pipeline/production_output/")
    ssh_command(ssh, "cat /root/trellis2-pipeline/production_output/interaction_log.json")

    ssh.close()
    print("\n=== ALL STEPS COMPLETE ===")

if __name__ == "__main__":
    main()
