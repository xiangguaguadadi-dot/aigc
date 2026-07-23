"""
3D Pipeline 全局配置
===============
集中管理所有路径、API 密钥和物理仿真参数。
"""

import os
import sys
from pathlib import Path

# ============================================================
# 代理配置 — 自动检测系统代理并设置环境变量
# ============================================================
def _detect_proxy():
    """检测系统代理并设置 HTTPS_PROXY / HTTP_PROXY 环境变量"""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return  # 已经设置了，不用管

    try:
        # Windows: 读取系统代理设置
        if sys.platform == "win32":
            import urllib.request
            proxies = urllib.request.getproxies()
            https_proxy = proxies.get("https") or proxies.get("http")
            if https_proxy:
                os.environ["HTTPS_PROXY"] = https_proxy
                os.environ["HTTP_PROXY"] = https_proxy
                print(f"[config] Proxy detected: {https_proxy}")
    except Exception:
        pass

_detect_proxy()

# ============================================================
# 项目路径
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()

INPUT_DIR = BASE_DIR / "input"              # 输入图片/视频目录
OUTPUT_DIR = BASE_DIR / "output"            # 输出根目录
MODELS_DIR = OUTPUT_DIR / "models"          # 下载的 3D 模型 (GLB)
RENDERS_DIR = OUTPUT_DIR / "renders"        # 仿真渲染结果
TEMP_DIR = OUTPUT_DIR / "temp"              # 临时文件（提取的视频帧等）
BLEND_DIR = OUTPUT_DIR / "blend"            # 保存的 .blend 文件

# 确保目录存在
for _dir in (INPUT_DIR, MODELS_DIR, RENDERS_DIR, TEMP_DIR, BLEND_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ============================================================
# Tripo API 配置
# ============================================================
# 从环境变量获取 API Key，也可直接设置
TRIPO_API_KEY = os.environ.get("TRIPO_API_KEY", "tsk_TmsFmH16ONo_Hh4QKXPaGdztyx9z5eBHSURypKc--S6")

# Tripo 模型参数
TRIPO_MODEL_VERSION = "v2.5-20250123"           # 模型版本
TRIPO_TEXTURE_QUALITY = "detailed"          # 贴图质量
TRIPO_FACE_LIMIT = 50000                    # 面数上限
TRIPO_PBR = True                            # 是否生成 PBR 材质

# ============================================================
# Blender 配置
# ============================================================
# Blender 可执行文件路径（None 表示自动检测）
BLENDER_EXECUTABLE = r"E:\blender.exe"
# 常见路径参考（按需取消注释）:
# BLENDER_EXECUTABLE = r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
# BLENDER_EXECUTABLE = "/Applications/Blender.app/Contents/MacOS/Blender"

# ============================================================
# 物理仿真参数
# ============================================================
SIM_START_FRAME = 1                         # 仿真起始帧
SIM_END_FRAME = 150                         # 仿真结束帧 (30fps × 5秒)
SIM_FPS = 30                                # 仿真帧率
SIM_SUBSTEPS = 20                           # 每帧子步数（越高越精确）
SIM_SOLVER_ITERS = 20                       # 求解器迭代次数

# 重力加速度 (m/s²)
GRAVITY_X = 0.0
GRAVITY_Y = 0.0
GRAVITY_Z = -9.81

# 地面参数
GROUND_SIZE = 20.0                          # 地面边长（米）
GROUND_HEIGHT = 0.1                         # 地面厚度

# 物体刚体参数
OBJECT_MASS = 1.0                           # 质量 (kg)
OBJECT_FRICTION = 0.5                       # 摩擦系数
OBJECT_RESTITUTION = 0.1                    # 弹性恢复系数 (0=完全非弹性, 1=完全弹性)
OBJECT_COLLISION_SHAPE = "CONVEX_HULL"      # 碰撞形状: BOX, SPHERE, CONVEX_HULL, MESH
OBJECT_LINEAR_DAMPING = 0.3                 # 线性阻尼
OBJECT_ANGULAR_DAMPING = 0.4                # 角阻尼

# 物体初始状态
OBJECT_START_Z = 5.0                        # 初始掉落高度（米）
OBJECT_RANDOM_ROTATION = True               # 是否随机初始旋转

# ============================================================
# 渲染参数
# ============================================================
RENDER_ENGINE = "CYCLES"                    # 渲染引擎: CYCLES, EEVEE, WORKBENCH
RENDER_RESOLUTION_X = 1920                  # 渲染分辨率 X
RENDER_RESOLUTION_Y = 1080                  # 渲染分辨率 Y
RENDER_SAMPLES = 128                        # 采样数（Cycles）
RENDER_OUTPUT_FORMAT = "PNG"                # 输出格式
RENDER_FRAME_STEP = 1                       # 每隔几帧渲染一次（1=每帧都渲染）

# ============================================================
# 输入配置
# ============================================================
SUPPORTED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"}
SUPPORTED_VIDEO_FORMATS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# 视频帧提取参数
VIDEO_FRAME_INTERVAL = 10                   # 每隔多少帧提取一张（避免重复图片）
