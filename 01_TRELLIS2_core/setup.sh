#!/bin/bash
# ============================================================
# TRELLIS.2 → 3D Physics Pipeline — One-Click Setup
# ============================================================
set -e

echo "========================================="
echo " TRELLIS.2 + 3D Physics Pipeline Setup"
echo "========================================="

PYTHON=${PYTHON:-python3}
WORKSPACE="$(cd "$(dirname "$0")" && pwd)"

# ---- 1. System check ----
echo "[1/7] Checking environment..."
$PYTHON --version
if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "  GPU: not detected"
else
    echo "  WARNING: nvidia-smi not found. CPU mode will be very slow."
fi

# ---- 2. PyTorch ----
echo "[2/7] Installing PyTorch..."
$PYTHON -m pip install --upgrade pip -q 2>/dev/null

if $PYTHON -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
    echo "  PyTorch with CUDA already installed"
else
    echo "  Installing PyTorch CUDA 12.4..."
    $PYTHON -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
fi

# ---- 3. TRELLIS.2 ----
echo "[3/7] Installing TRELLIS.2..."
if [ ! -d "$WORKSPACE/pre-model/TRELLIS.2" ]; then
    git clone https://github.com/microsoft/TRELLIS.2.git "$WORKSPACE/pre-model/TRELLIS.2"
fi
cd "$WORKSPACE/pre-model/TRELLIS.2"
$PYTHON -m pip install -e . --no-build-isolation -q 2>&1 | tail -2
cd "$WORKSPACE"

# ---- 4. Pipeline dependencies ----
echo "[4/7] Installing pipeline dependencies..."
$PYTHON -m pip install -q \
    open3d trimesh pybullet pygltflib \
    transformers segment-anything matplotlib \
    scipy tqdm Pillow opencv-python \
    huggingface_hub 2>&1 | tail -2

# ---- 5. Download TRELLIS.2 weights ----
echo "[5/7] Downloading TRELLIS.2 model weights (~20GB)..."
$PYTHON pre-model/download_weights.py 2>&1 || echo "  Weight download skipped (may need HF token)"

# ---- 6. Download SAM weights (for Module 1) ----
echo "[6/7] Downloading SAM checkpoint..."
mkdir -p "$WORKSPACE/pipeline/module1_perception/weights"
if [ ! -f "$WORKSPACE/pipeline/module1_perception/weights/sam_vit_h_4b8939.pth" ]; then
    wget -q --show-progress -O "$WORKSPACE/pipeline/module1_perception/weights/sam_vit_h_4b8939.pth" \
        "https://hf-mirror.com/HCMUE-Research/SAM-vit-h/resolve/main/sam_vit_h_4b8939.pth?download=true" 2>&1 || \
    echo "  SAM download failed (run manually later)"
fi

# ---- 7. Verify ----
echo "[7/7] Verification..."
$PYTHON -c "
import sys, os
sys.path.insert(0, '$WORKSPACE')
sys.path.insert(0, '$WORKSPACE/pipeline')

# Test each module import
from pipeline.module1_perception.config import SegmentationConfig
from pipeline.module2_reconstruction.pipeline import ReconstructionPipeline
from pipeline.module3_physics.pipeline import PhysicsPipeline
from pipeline.module4_simulation.pipeline import SimulationPipeline
from pipeline.module5_interaction.controller import InteractionController
print('  [OK] All 5 modules imported successfully')

import torch
print(f'  [OK] PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')
" 2>&1

echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "  Quick start:"
echo "    python pre-model/generate.py photo.jpg -o model.glb"
echo "    python run_pipeline.py --image photo.jpg"
echo "    python app.py"
echo ""
