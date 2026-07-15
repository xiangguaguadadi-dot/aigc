# Physical Modeling Agent - 项目权威上下文

> 本文件是后续 AI 和开发者接手仓库时的第一阅读入口。
> 最后更新：2026-07-15（Asia/Shanghai）。

## 1. 项目最终目标

本项目要构建的不是一个普通的 image-to-3D 工具，而是一套“视觉场景到可执行物理场景”的编译系统：

```text
多视角室内图片 / 单物体参考图 / 人工测量信息
→ 视觉资产生成或导入
→ Blender 场景装配、校准和视觉验证
→ 统一 IndoorScene 场景表示
→ 视觉几何、碰撞几何、体积几何分离
→ 质量、质心、惯量、摩擦等物理属性生成
→ 多部件、关节、抓取点和 affordance 描述
→ 编译到物理仿真器
→ 自然语言任务转换为有限高层动作
→ 机器人导航、抓取和放置
→ 仿真、验证、误差分析和可视化
```

核心研究和工程价值是：

> 将“看起来像真的”AI 视觉资产转换为“能够碰撞、运动、抓取、验证”的物理资产。

DesignToolbox 不是不可替换的核心依赖。当前已经用开源路线替代：

```text
rembg + TripoSR + Blender + trimesh
```

DesignToolbox 将来只能作为可选的 `ImageTo3DBackend` 接入，不能污染内部领域协议。

## 2. 项目定位边界

### 2.1 当前不应过度宣称“真实数字孪生”

仅根据一张图片生成的模型缺少真实尺度、内部结构、材料密度、质量分布和实时状态同步，因此当前更准确的定位是：

> 基于视觉资产的室内物理场景重建与机器人仿真系统。

只有加入标定尺度、实测物性、真实位姿校准和现实状态同步后，才能严格称为物理数字孪生。

### 2.2 机器人和自然语言的角色

- 机器人是验证物理场景是否真正可交互的下游消费者。
- 大模型只负责目标理解、语义候选和高层动作分解。
- 大模型不能直接输出轮速、关节角、控制力矩或未经校验的仿真代码。
- 导航、IK、轨迹规划、碰撞检查和控制由确定性模块完成。

### 2.3 大模型的职责边界

大模型/VLM 可以：

- 识别类别、颜色、材料候选和场景关系；
- 选择基础体模板候选；
- 推测是否有门、抽屉、把手和可抓取区域；
- 输出结构化候选、置信度、假设和未知项。

大模型/VLM 不可以：

- 直接创建物理引擎对象；
- 编造真实尺寸、质量和密度；
- 直接生成最终惯量矩阵；
- 绕过 Schema、范围、几何和物理验证；
- 把视觉模型直接标记为合法碰撞体。

## 3. 不可破坏的核心原则

### 3.1 三重几何表示

每个物体必须区分：

```text
SceneObject
├── visual_geometry      # 渲染和展示，高细节
├── collision_geometry   # 碰撞检测，低复杂度
├── volume_geometry      # 体积、质心和惯量计算
└── physical_properties
```

三者可以来自同一个源模型，但不能默认相同。

### 3.2 统一单位和坐标约定

```text
长度：m
质量：kg
时间：s
角度：rad
坐标系：右手坐标系
竖直方向：+Z
四元数顺序：[x, y, z, w]
```

图片生成模型的默认坐标值不是实测米制尺度。没有测量值时必须写明 `scale_status: unscaled`。

### 3.3 参数来源必须可追踪

物理和语义参数应记录 provenance：

```text
measured
user_input
product_or_cad_data
category_prior
estimated
default
```

公式计算精确不代表输入参数真实。

### 3.4 每个阶段保存中间结果

原始输入、预处理图、原始网格、标准化网格、`.blend`、预览、日志、清单、仿真配置、轨迹和验证报告不能互相覆盖。

### 3.5 Domain 与具体工具解耦

领域层不能依赖 TripoSR、Blender、PyBullet、MuJoCo、VLM API 或 UI。外部工具通过接口和编译器接入。

## 4. 目标分层架构

依赖方向必须自上向下，Domain 保持稳定：

```text
Presentation Layer
CLI / macOS launcher / future Web / API / debug viewer
        ↓
Application Layer
流水线编排、PipelineContext、状态、重试、恢复、active query
        ↓
Domain Layer
IndoorScene、SceneObject、GeometryModel、PhysicalAsset、RobotTask、Result
        ↓ interfaces
Intelligence / Geometry / Simulation / Validation / Infrastructure
```

各模块职责：

| 模块 | 职责 |
|---|---|
| `presentation` | 文件输入、CLI、Web、结果展示、调试开关 |
| `application` | 流程编排、阶段状态、错误恢复、产物路径 |
| `domain` | 与工具无关的场景、几何、物理、任务、不确定性对象 |
| `intelligence` | VLM、语义识别、候选假设、材料先验、主动提问 |
| `geometry_engine` | 基础体、CSG、网格检查、拟合、碰撞代理、质量属性 |
| `simulation` | 仿真编译器、PyBullet/MuJoCo 适配、轨迹记录 |
| `validation` | Schema、几何、物理、任务结果和回归检查 |
| `infrastructure` | 配置、日志、缓存、序列化、文件存储、外部工具适配 |

推荐核心接口：

```text
ImageTo3DBackend
PerceptionService
GeometryEngine
SimulationCompiler
SimulationBackend
ResultValidator
```

## 5. 目标领域对象

后续 WP0 应优先定义并测试以下对象：

```text
IndoorScene
SceneObject
GeometryModel
Primitive / PrimitiveAssembly
PhysicalAsset
ArticulatedObject / Link / Joint
Affordance / GraspCandidate
RobotTask
SimulationResult
ValidationReport
ModelHypothesis / Estimate / Provenance
PipelineContext / PipelineError
```

对象分类至少支持：

```text
room_structure
static_object
movable_object
articulated_object
robot
```

第一批基础体：

```text
box sphere ellipsoid cylinder capsule cone frustum torus plane
```

复杂网格的碰撞表示使用分级回退：

```text
单基础体
→ 多基础体组合
→ 基础体 + 凸包
→ 凸分解
→ 简化网格兜底
```

## 6. 目标完整流水线

### Stage A：视觉资产输入（当前已打通单物体 MVP）

```text
单物体图片
→ rembg
→ TripoSR
→ raw.glb
→ Blender 标准化
→ final.glb + normalized.blend + preview + manifest
```

### Stage B：室内场景装配

- 房间骨架用 box/plane 表示地板、墙、顶面、门窗。
- 导入家具视觉资产。
- 使用测量信息统一真实尺度。
- 校准位置、旋转、原点和层级。
- 生成 `IndoorScene` 和场景关系图。

### Stage C：物理资产化

- 检查网格封闭性、自交、法线和薄面。
- 生成基础体/凸包/凸分解碰撞代理。
- 单独构造可用于体积计算的几何。
- 根据测量或材料先验计算质量、质心和惯量。
- 参数来源和不确定性必须进入清单。

### Stage D：关节和交互语义

- 支持 fixed、revolute、prismatic。
- 描述 parent/child、axis、origin、limits、damping、collision rules。
- 添加 graspable、pushable、openable、support_surface、container、handle。
- 抓取候选必须经过夹爪宽度、IK、可达性和碰撞验证。

### Stage E：仿真和机器人任务

- 编译到开源物理仿真器；当前尚未最终选择 PyBullet 或 MuJoCo。
- 使用现成机器人模型，不自行设计完整机器人。
- 支持有限任务：移动、抓取、放置。
- 自然语言只转换为有限动作序列。
- 记录导航路径、接触、轨迹、成功/失败和性能指标。

## 7. 当前实现状态（2026-07-15）

当前真正完成的是 Stage A 的单物体视觉资产链路。物理资产化、场景协议、仿真和机器人尚未实现。

### 7.1 当前可运行入口

#### macOS 拖拽入口

把单主体图片放入 `drop_images/`，然后双击：

```text
run_image_to_3d.command
```

脚本选择 `drop_images/` 中最后修改的受支持图片，创建带时间戳的资产 ID，运行完整流水线，成功后自动用 Blender 打开 `normalized.blend`。

也可在终端运行：

```bash
./run_image_to_3d.command /absolute/path/to/object.webp
```

#### 正式 Python CLI

```bash
.venv/bin/python scripts/run_visual_asset_pipeline.py \
  --image /absolute/path/to/object.webp \
  --asset-id object_001
```

常用参数：

```text
--device auto|mps|cuda|cpu
--mc-resolution 128
--chunk-size 4096
--foreground-ratio 0.85
--rotate-x-degrees -90
--output-root assets
--force
```

默认不覆盖已有资产。只有用户明确要求重建时才使用 `--force`。

### 7.2 代码文件职责

#### `scripts/run_visual_asset_pipeline.py`

统一应用层入口，负责：

- 参数与环境检查；
- ASCII 资产 ID 校验；
- 拒绝静默覆盖；
- 原图复制和 SHA-256；
- rembg 去背景；
- TripoSR 模型加载和推理；
- MPS/CPU marching-cubes 兼容处理；
- 原始网格非空、有限坐标检查；
- 调用 Blender 后台脚本；
- 最终 GLB、预览和 Blender 回读结果检查；
- 生成 `asset_manifest.json`；
- 输出 pipeline/blender 日志。

#### `scripts/blender/normalize_asset.py`

Blender 4.5 后台脚本，负责：

- 从空场景导入 raw GLB；
- 明确记录轴旋转；
- 水平居中并将底部移动到 `z=0`；
- 不在缺少测量值时伪造真实尺度；
- 保存纯资产 `normalized.blend`；
- 导出标准 GLB；
- 创建临时相机、灯光和地面并渲染预览；
- 清空场景后重新导入最终 GLB；
- 记录 mesh 数、顶点/面数、包围盒和 round-trip 结果。

#### `run_image_to_3d.command`

macOS Finder 入口，负责：

- 从 `drop_images/` 选择最新图片，或接受命令行图片路径；
- 检查 Python、CLI 和 Blender；
- 将文件名转成安全、限长、带时间戳的资产 ID；
- 调用 Python CLI；
- 成功后自动用 Blender 打开三维模型；
- 支持 `--dry-run` 检查但不生成。

#### `drop_images/`

用户图片投放目录。图片被 `.gitignore` 忽略，`README.md` 保留。

### 7.3 资产输出协议

```text
assets/<asset_id>/
├── source/reference.<ext>
├── preprocessed/
│   ├── foreground.png
│   └── triposr_input.png
├── generated/raw.glb
├── blender/
│   ├── normalized.blend
│   └── normalization_report.json
├── export/<asset_id>.glb
├── preview/preview.png
├── logs/
│   ├── pipeline.log
│   └── blender.log
└── asset_manifest.json
```

`asset_manifest.json` 是该阶段的事实来源，记录：

- 输入文件、尺寸和哈希；
- 模型、源码提交、依赖版本和计算设备；
- 生成参数和各阶段耗时；
- 原始网格指标；
- Blender 变换和坐标信息；
- 最终 GLB 哈希与 round-trip；
- 已知限制和警告。

## 8. 当前本机环境

本机是 Apple Silicon Mac（Apple M5，24 GB 统一内存）。不要记录或输出序列号、UDID 等设备敏感信息。

```text
uv:                  ~/.local/bin/uv (0.11.28)
Python:              3.11.15
project venv:        .venv/
PyTorch:             2.13.0
MPS:                 available and smoke-tested
Blender:             ~/Applications/Blender.app
Blender version:     4.5.11 LTS
TripoSR source:      ~/Library/Caches/physical-modeling-agent/TripoSR
TripoSR commit:      107cefdc244c39106fa830359024f6a2f1c78871
TripoSR model:       ~/Library/Caches/physical-modeling-agent/models/TripoSR-5b521936
model SHA-256:       429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee
rembg U2Net:         ~/.u2net/u2net.onnx
U2Net MD5:           60024c5c889badc19c04ad937298a77b
```

环境路径可通过以下变量覆盖：

```text
TRIPOSR_SOURCE
TRIPOSR_MODEL_DIR
BLENDER_BIN
```

外部源码和权重不进入 Git。若路径存在，应先复用，不要重复下载。

## 9. 本轮代码和环境工作记录

### 9.1 路线选择

- 对原 DesignToolbox 方案进行可行性评估。
- 确认 DesignToolbox 的公开版本、许可证和批处理能力未在仓库中得到证明，因此不能作为硬依赖。
- 选择开源视觉链路：TripoSR + Blender 官方版本 + Blender Python API。
- 明确不依赖 Blender MCP；Blender 运行时自动化使用 `--background --python`。
- 创建 `阶段一Prompt-图片到Blender开源链路.md`，定义目标、非目标、输入、步骤、验收和回退。

### 9.2 安装和依赖处理

- 安装用户目录 `uv 0.11.28`，未覆盖系统 Python。
- 安装 uv 管理的 Python 3.11.15 并创建 `.venv`。
- 安装 PyTorch 2.13.0，MPS 矩阵 smoke test 通过。
- 从 Blender 官方源下载 4.5.11 LTS ARM64，SHA-256 校验通过，安装到用户应用目录。
- 下载 TripoSR 固定提交和固定模型权重，模型大小 1,677,246,742 字节，SHA-256 校验通过。
- `xatlas==0.0.9` 在当前 CMake 上构建失败；改用 API 兼容的 `xatlas==0.0.11`。
- `torchmcubes` 从提交 `3381600ddc3d2e4d74222f8495866be5fafbace4` 编译 CPU 版本。
- 安装并校验 rembg U2Net；首次内置下载器中断后，使用可恢复下载完成并按官方 MD5 校验。

### 9.3 Apple MPS 兼容修复

TripoSR 官方 `run.py` 在没有 CUDA 时会强制回退 CPU，即使 MPS 可用。当前 CLI 不调用该入口，而是直接使用 `TSR` API：

- 神经网络推理在 `mps` 执行；
- macOS 编译的 `torchmcubes` 只接受 CPU tensor；
- 在 `set_marching_cubes_resolution()` 创建 helper 后，将体素场复制到 CPU 执行 marching-cubes；
- 结果再回到原设备继续颜色查询和导出。

不要把注入时机改到 helper 创建前，否则 `isosurface_helper` 为 `None`。

### 9.4 Blender 兼容和验证修复

- TripoSR/GLB/Blender 轴转换使首个沙发宽度落到 Z 轴；增加显式 `--rotate-x-degrees`，当前 TripoSR 默认 `-90`。
- 空白 Blender 工厂场景没有默认 `World`；预览脚本显式创建 `preview_world`。
- 第一次手工 round-trip 验证误把默认立方体计入 mesh；正式脚本在验证前使用 `read_factory_settings(use_empty=True)`。
- Blender 导出可能因顶点颜色、法线和 corner attributes 拆分顶点；三角面数应保持，顶点数不要求与原始 mesh 相同。
- `.blend` 在添加预览相机、灯光和地面前保存，因此它保持为纯资产文件。

### 9.5 统一 CLI 和拖拽入口

- 新增 `scripts/run_visual_asset_pipeline.py`。
- 新增 `scripts/blender/normalize_asset.py`。
- 新增可执行 `run_image_to_3d.command`。
- 新增 `drop_images/README.md`。
- `.gitignore` 忽略用户投放图片，但保留目录说明。
- README 增加 CLI、参数、输出目录和 macOS 拖拽说明。

### 9.6 实际验证

首个输入：蓝色沙发 550x550 WebP，SHA-256：

```text
66fcc804e3a7fe64418dcc82b677d125e9abba1f5ae7deab205992ee41737bad
```

低分辨率 smoke test 结果：

```text
device:                 mps
marching-cubes:         cpu
resolution:             128
raw vertices:           10,286
raw triangles:          20,484
MPS inference:          ~0.5 s (warm run)
generation total:       ~5.7 s (model cached)
raw mesh watertight:    false
Blender round-trip:     passed
orientation correction: X = -90 degrees
physical scale:         unknown
```

已验证：

- TripoSR 模型 CPU 加载和迁移到 `mps:0`；
- CPU marching-cubes 小测试；
- 单图生成非空 GLB；
- 顶点均为有限值；
- Blender 后台导入、落地、保存、导出和渲染；
- 最终 GLB 从空白 Blender 场景重新导入；
- 预览像素非空、非纯色；
- `asset_manifest.json` 和 normalization report 为合法 JSON；
- CLI `--help`、资产 ID 校验、默认拒绝覆盖；
- 完整 CLI 临时资产端到端测试，成功后删除临时测试资产；
- `run_image_to_3d.command` 的 zsh 语法、可执行权限、drop folder 选图和 dry-run；
- Blender 应用可被 macOS `open` 定位。

现有 `assets/` 下包含多次用户/开发验证资产。它们是生成产物，不代表全部达到高保真或物理可用标准。

## 10. 当前已知限制

### 10.1 视觉质量

- 单张正视图无法观测背面和真实深度。
- TripoSR 会推测遮挡和背面结构。
- 128 marching-cubes 是流程验证配置，细节有限。
- 首个沙发颜色偏白、织物与靠垫细节明显弱于原图。
- 提高到 256 会增加内存、耗时和面数，但不保证解决单视图不可观测问题。

### 10.2 物理不可用性

- 当前生成网格可能不封闭、自交或包含薄面。
- 当前 GLB 只能作为 `visual_geometry`。
- 不得直接用它计算体积、质量、质心和惯量。
- 不得直接用高面数视觉网格作为动态碰撞体。
- 当前没有真实尺度、材料、质量、关节、抓取点或 affordance。

### 10.3 自动方向和尺度

- `X=-90°` 是当前 TripoSR 到 Blender 链路的显式默认修正，不是任意后端的通用规则。
- 未来接入新生成器时必须通过 adapter 指定坐标变换。
- 自动判断物体“哪一面朝前”尚未实现。
- 没有用户测量值时不能声称单位值对应真实米制尺寸。

### 10.4 许可证

- Blender 为 GPL，但普通导出资产不会自动变成 GPL。
- 代码许可证、模型权重许可证、输入图片许可证和生成资产权利必须分别检查。
- 当前记录 TripoSR 源码和模型为 MIT；分发或商用前仍应核对固定版本原始许可文件。
- 不要把来源不明的家具图片或模型提交到公共仓库。

## 11. 下一步推荐顺序

不要立即跳到机器人。建议按以下顺序继续：

1. **WP0 数据协议**：定义 `IndoorScene`、`SceneObject`、三重几何、provenance 和 JSON Schema。
2. **Stage A 加固**：支持真实基准尺寸、可配置方向、更多输入样本、错误清单和依赖锁定。
3. **网格检查**：封闭性、自交、连通分量、法线、退化面和薄结构报告。
4. **碰撞代理**：box/sphere/cylinder 模板、凸包、VHACD/CoACD 回退。
5. **体积与质量属性**：只对合法 volume geometry 计算，并与解析基础体基准比较。
6. **房间骨架与场景装配**：固定房间、桌椅柜和三个小物体。
7. **关节/affordance**：先使用模板和人工确认，不承诺通用自动恢复。
8. **选择仿真器和机器人**：实现 compiler/adapter，再做固定任务。
9. **有限自然语言**：结构化任务和状态机，最后接语言模型。
10. **对比实验**：原始碰撞网格 vs 简化碰撞几何的性能和任务成功率。

下一阶段最小验收应包括：

- 一个视觉 GLB 能转换为独立 collision geometry；
- 原始视觉 GLB 保持不变；
- 碰撞表示可视化；
- 面数、体积/表面近似误差和耗时被记录；
- 非封闭视觉网格不会被错误用于质量计算。

## 12. 测试与完成标准

任何阶段不能只凭“生成了文件”判定成功。至少检查：

- 进程退出码；
- 输出存在且非空；
- 数值有限，无 NaN/Infinity；
- 包围盒合理；
- 坐标和单位明确；
- 新空场景/新进程可重新读取；
- 预览非空且主体完整；
- 参数、版本、哈希、假设和警告进入 manifest；
- 未运行的测试明确说明原因。

视觉资产阶段不要求 watertight，但必须报告。物理资产阶段则必须使用合法体积表示或明确回退。

## 13. 仓库状态与工作安全

当前工作树是脏的。存在大量已跟踪骨架文件的删除记录，包括旧 `src/`、`tests/`、`configs/`、`examples/` 和 `scripts/run_vlm_parse.py`。这些删除不是本轮自动恢复的内容。

后续 AI 必须：

- 开始工作前运行 `git status --short`；
- 不得擅自恢复或回滚用户删除的文件；
- 不得使用 `git reset --hard` 或 `git checkout --` 清理工作区；
- 不得假设 README 中旧 VLM 示例当前仍可运行，因为对应脚本已被删除；
- 不得提交 `.env`、模型权重、uv 缓存、`.venv` 或用户投放图片；
- 不得删除 `~/Library/Caches/physical-modeling-agent`、`~/.u2net` 或 Blender，除非用户明确要求；
- 不得覆盖已有 `assets/<asset_id>`，除非用户明确使用 `--force`；
- 不得把生成产物的视觉成功等同于物理正确。

本轮新增/修改的重要文件可能仍未提交：

```text
CLAUDE.md
README.md
.gitignore
阶段一Prompt-图片到Blender开源链路.md
scripts/run_visual_asset_pipeline.py
scripts/blender/normalize_asset.py
run_image_to_3d.command
drop_images/README.md
assets/*
```

不要自行提交，除非用户明确要求。

## 14. 参考文档优先级

1. `CLAUDE.md`：当前权威架构、状态和接手说明。
2. `基于DesignToolbox与Blender的室内物理数字孪生方案.md`：长期产品范围和 WP0-WP12。
3. `阶段一Prompt-图片到Blender开源链路.md`：视觉资产阶段的严格验收任务书。
4. `README.md`：当前用户运行命令。
5. `/Users/t/Downloads/Physical_Modeling_Agent_代码结构与流程设计.md`：早期通用分层设计参考；文件存在编码异常，而且部分实施顺序已被当前路线取代。

发生冲突时，以本文件的“当前实现状态”和实际代码/测试结果为准；长期目标仍以室内物理场景和机器人交互为主线。
