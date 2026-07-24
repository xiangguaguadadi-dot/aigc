# 云服务器部署指令

## 连接信息

```
ssh -p 27258 root@px-cloud1.matpool.com
密码: 5ZPy](PPjow[KBa+
```

## 执行顺序

### 第1步：验证环境

```bash
nvidia-smi
# 预期: NVIDIA A100-PCIE-40GB

python3 --version
# 预期: Python 3.10.12

df -h /root/
# 预期: 200G 总量, 至少 100G 剩余
```

### 第2步：安装缺失的 pip 包

```bash
pip install -q scipy matplotlib 2>&1 | tail -3
```

### 第3步：下载 SAM 权重 (2.4GB)

```bash
mkdir -p /root/module1/model_weights

wget -O /root/module1/model_weights/sam_vit_h_4b8939.pth \
  "https://hf-mirror.com/HCMUE-Research/SAM-vit-h/resolve/main/sam_vit_h_4b8939.pth?download=true"

# 验证
ls -lh /root/module1/model_weights/sam_vit_h_4b8939.pth
# 预期: 约 2.4GB
```

### 第4步：确认 Qwen2-VL-2B 已缓存

```bash
python3 -c "
from modelscope import snapshot_download
p = snapshot_download('Qwen/Qwen2-VL-2B-Instruct')
print(p)
"
# 预期: /root/.cache/modelscope/models/Qwen--Qwen2-VL-2B-Instruct/snapshots/master

# 验证大小
du -sh /root/.cache/modelscope/models/Qwen--Qwen2-VL-2B-Instruct/
# 预期: 约 4GB
```

### 第5步：确认 OWL-ViT 可加载

```bash
HF_ENDPOINT=https://hf-mirror.com python3 -c "
from transformers import pipeline
p = pipeline('zero-shot-object-detection', model='google/owlvit-base-patch32')
print('OWL-ViT OK')
"
# 预期: OWL-ViT OK
```

### 第6步：确认 CLIP 可加载

```bash
HF_ENDPOINT=https://hf-mirror.com python3 -c "
from transformers import CLIPModel
m = CLIPModel.from_pretrained('openai/clip-vit-base-patch32')
print('CLIP OK')
"
# 预期: CLIP OK
```

### 第7步：运行全流程测试

```bash
cd /root/trellis2-pipeline

# 测试1：模块导入
python3 -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'pipeline')
from pipeline.colmap_io import load_colmap_poses
from pipeline.engineering import calibrate_scale, make_watertight
from pipeline.spec_compliant import infer_properties, to_spec_json
from pipeline.production import ProductionPipeline
print('All modules OK')
"

# 测试2：生产管线 (3个物体 → 物理仿真 → 交互)
python3 -c "
from pipeline.production import demo
demo()
"
# 预期: 输出 "Production Pipeline Complete"
# 确认 chair≈3.2kg, apple≈0.045kg, cup≈0.3kg

# 测试3：M1 检测 (用房间照片)
HF_ENDPOINT=https://hf-mirror.com python3 \
  pipeline/module1_perception/run_detection.py \
  --image room_photo.jpg \
  --prompt "sofa . chair . table . laptop . plant . tv . lamp" \
  --threshold 0.05
# 预期: 检测到 N 个物体，输出 room_photo_m1.json
```

### 第8步：验证输出

```bash
ls -lh /root/trellis2-pipeline/production_output/
# 应有 chair/apple/cup 三个子目录，每个包含:
#   *_physics.json  (物理参数)
#   *.glb           (水密网格)
#   *_collision_0.glb (碰撞体)

cat /root/trellis2-pipeline/production_output/interaction_log.json
# 应有 3 个物体的交互记录 (ray→grasp→lift→release)
```

### 故障排查

| 问题 | 解决 |
|------|------|
| SAM 下载失败 | 换个镜像: 把 hf-mirror.com 换成 hf.phngo.com |
| OWL-ViT 加载失败 | `pip install transformers -U` 然后重试 |
| PyBullet 报错 | `apt-get install -y libegl1-mesa-dev libgl1-mesa-dev` |
| 磁盘不足 | `rm -rf /root/.cache/modelscope/models/qwen--Qwen2.5*` (删掉空的) |
