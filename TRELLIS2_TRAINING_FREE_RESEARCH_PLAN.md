# TRELLIS.2 无训练改进研究计划

状态：计划已批准，Phase 0 执行中。

最后更新：2026-07-21（Asia/Shanghai）

## 1. 目标与边界

目标是在冻结 TRELLIS.2-4B、SC-VAE 和图像编码器权重的前提下，探索五条可独立验证的推理或后处理改进路线，并与统一的官方基线做配对比较。

本项目中的“无训练”定义为：

- 不更新模型参数，不执行针对模型权重的 `optimizer.step()`。
- 允许每个测试样本上的优化，例如相机、网格顶点、O-Voxel 连续属性、光照和曝光优化。
- 允许替换 ODE 求解器、调整采样日程、候选选择和图优化。
- 允许调用冻结的预训练评价模型，但必须记录模型、版本和权重来源。
- 不允许用测试集拟合全局超参数；所有阈值先在独立开发子集上确定。
- 方向 5.1 不训练错误分类器，采用显式规则或图目标；方向 5.5 仅允许在 dev-50 上拟合低容量校准器，并单独披露其参数量和拟合数据。

首轮只运行 `512^3`。当前机器是 A100 40GB；论文和本地包装器均提示 `1024^3` 通常需要 80GB，因此高分辨率实验只能在确认显存策略后作为第二阶段工作。

## 2. 已确认的本地条件

- GPU：NVIDIA A100-PCIE-40GB。
- 可用磁盘：约 129GB。
- 官方 TRELLIS.2 源码位于 `trellis2-3d-generator-main/TRELLIS.2/`。
- TRELLIS.2-4B、TRELLIS-image-large、DINOv3 和 RMBG-2.0 权重已在 `/root/.cache/trellis2/`，不应重复下载。
- 官方仓库附带一批 image-to-3D 示例图、一个 PBR texturing 示例和多张 HDRI，可先用于 smoke test。
- 官方默认采样器是 12 步 `FlowEulerGuidanceIntervalSampler`。
- 官方 `FlexiDualGridVaeDecoder` 在推理时直接使用 `intersected_logits > 0`。
- 官方生成管线和 GLB 后处理已经调用 `fill_holes`，并包含非流形边、重复面和小连通分量修复。
- 官方提供 Mesh、Voxel 和 PBR renderer，可作为测试时优化的基础。

## 3. Git 与 worktree 前置问题

`/course476/aigc` 当前是一个尚无初始 commit 的仓库，且官方 `TRELLIS.2/` 被外层 `.gitignore` 排除。直接从该仓库创建五个 worktree，既不可行，也不会包含需要修改的官方源码。

执行阶段采用独立的 TRELLIS.2 研究仓库。所有路径置于当前可写工作区 `/course476/aigc/` 内：

1. 从 Microsoft 官方仓库建立一个独立 clone，并固定 upstream commit。
2. 核对该 commit 与当前本地源码；本地差异以 patch 形式审计后迁移，不覆盖现有目录。
3. 在共同基线和评价工具提交后创建五个分支与 worktree：

| 编号 | 分支 | worktree |
|---|---|---|
| 1 | `research/topology-consistency` | `/course476/aigc/trellis2-worktrees/01-topology` |
| 2 | `research/adaptive-flow` | `/course476/aigc/trellis2-worktrees/02-flow` |
| 3 | `research/single-view-tto` | `/course476/aigc/trellis2-worktrees/03-tto` |
| 4 | `research/pbr-inverse-rendering` | `/course476/aigc/trellis2-worktrees/04-pbr` |
| 5 | `research/uncertainty-guided` | `/course476/aigc/trellis2-worktrees/05-uncertainty` |

权重、数据、基线输出和 Python 环境不复制进 worktree，通过配置指向共享目录。每个分支只提交源码、测试、轻量配置和报告，不提交模型、数据、GLB、视频或大规模指标缓存。

当前协作环境最多有 4 个并发槽位，且主 Agent 占 1 个。因此五个子 Agent 不能同时运行。执行时采用两批调度：第一批 3 个 Agent，完成或暂停后再启动剩余 2 个；仍保留五个独立任务和五个 worktree。

## 4. 数据与统一基线计划

### 4.1 数据选择

采用分层基准，避免一开始下载全部训练集或不可复现的授权数据。

| 层级 | 数据 | 用途 | 计划规模 |
|---|---|---|---|
| D0 | 官方仓库内置示例图和 texturing 样例 | 环境、导出和渲染 smoke test | 8 个代表样例 |
| D1 | 官方内置 image-to-3D 示例图 | 生成质量、速度和失败类型开发集 | 固定 32 个 |
| D2 | Toys4K-PBR-dev | 有真值的共同开发集 | 从论文 473 个口径中预先固定 50 个 |
| D3 | Toys4K-PBR-holdout | 最终形状和材质重建评估 | 剩余 423 个，开发阶段不可见 |
| D4 | 论文的 100 张 NanoBanana 条件图 | image-to-3D 生成评估 | 官方清单可获得时使用全部 100 张 |
| D5 | Sketchfab Featured/Picked | 复杂专业资产验证 | 仅在作者清单和许可证可核验后使用 |

选择理由：

- Toys4K-PBR 是论文正式重建测试集，可计算 Mesh Distance、Chamfer、normal PSNR/LPIPS 和 PBR 指标。
- 论文附录称 PBR 严格子集为 473 个，但数据统计表给出了更大的 Toys4K 可用数量。下载后必须复现“同时包含 base color、metallic、roughness”的筛选条件，并把最终 SHA256 清单固化，不能仅按总数猜测。
- 在任何改进实验开始前，按只依赖资产元数据的固定规则将 473 个对象划分为 dev-50 和 holdout-423。阈值、正则和停止条件只能使用 dev-50；主要结论只使用 holdout-423。完整 473 的结果仅作为与论文表格对齐的次级结果，并明确包含开发子集。
- 90 个 Sketchfab Featured 资产依赖作者选择和各资产许可证，不作为首轮阻塞项。
- 若论文的 100 张 NanoBanana 图片或清单未公开，不能用自建图片冒充论文测试集；届时将官方示例开发集明确标记为 local benchmark。

### 4.2 下载与存储规则

执行阶段的数据目录为 `/course476/aigc/trellis2-research-data/`：

```text
trellis2-research-data/
├── manifests/          # URL、许可证、SHA256、筛选原因
├── raw/                # 原始下载，只读
├── processed/          # mesh/PBR dump、O-Voxel、条件渲染
├── splits/             # smoke/dev/holdout/full 固定清单
├── baseline/           # 官方基线输出
└── experiments/        # 各方向实验输出
```

下载前先获取元数据和预估体积，首轮数据硬上限设为 60GB；超过上限则只处理固定的 Toys4K-PBR-dev-50。所有下载必须可恢复、带 checksum，并保留原许可证。模型权重使用现有缓存，不再次下载。

### 4.3 官方基线

共同基线必须先于五个方向生成，并锁定：

- 分辨率：`512^3`。
- 采样器：官方 Euler guidance-interval。
- 步数：12。
- pipeline 参数：使用官方 checkpoint 配置，不使用包装器中的未审计默认改动。
- 随机种子：开发集固定 3 个种子；大规模评估至少 1 个固定种子，关键结果补 3 个种子。
- 输出阶段：保存 sparse structure、shape SLat、原始 O-Voxel mesh、官方 postprocess mesh 和 PBR 属性。
- 环境记录：源码 commit、权重 checksum、CUDA/PyTorch/扩展版本、GPU、峰值显存和逐阶段时间。

先运行 D0；通过后在 D1 和 Toys4K-PBR-dev 上生成基线。holdout 的基线和改进结果只在方法冻结后统一生成。任何方向不得单独修改输入预处理、随机种子、导出参数或评价视角后再与基线比较。

### 4.4 统一指标

形状重建：

- Mesh Distance 与对应 F-score。
- 外表面 Chamfer Distance 与对应 F-score。
- normal PSNR、LPIPS。
- 顶点数、面数和 token 数。

拓扑与资产健康度：

- 边界环数量、边界总长度和小孔洞数量。
- 非流形边、重复面、孤立组件、自交统计。
- watertight rate 只作为描述性指标，不将合法开放表面判为失败。
- raw mesh、官方 postprocess 和改进方法三者都要报告。

材质：

- base color、metallic、roughness、alpha 的逐通道 PSNR/LPIPS 或 MAE。
- 固定 HDRI 与未见 HDRI 下的 shaded PSNR/LPIPS。
- 重光照稳定性和能量范围违规比例。

生成与效率：

- CLIP/CLIP-N；官方评价依赖可复现时增加 ULIP-2 和 Uni3D。
- 总延迟、三个阶段延迟、NFE、峰值显存和失败率。
- 多种子结果使用配对统计和 bootstrap 置信区间，不只展示最佳案例。

## 5. 最终五个研究方向

### 5.1 结构置信度感知的 O-Voxel 解码

保留，但将原来的“拓扑修复”收窄为解码前的结构一致性问题，避免重复官方 `fill_holes`。

核心假设：`intersected_logits > 0` 的逐边独立阈值丢失置信度并造成局部连接错误。保留 logits，在活动体素图上联合决定低置信度边，仅对小范围、低置信度结构做修正，然后再运行 Flexible Dual Grid。

首轮原型：

- 暴露 intersected logits、dual vertex 和 split weight。
- 建立相邻体素/quad 一致性检查和错误分类器。
- 比较固定阈值、阈值扫描、局部图优化和官方 mesh repair。
- 对合法开放面设置保护规则，不强制全局 watertight。

Go/No-Go：在 dev-50 上减少至少 30% 的非预期小边界环或孤立组件，同时 MD/normal PSNR 不恶化超过 1%，额外解码时间低于 20%。

主要风险：生成模型可能以低置信度表达真实开放边；没有语义标签时，过度修复会破坏 O-Voxel 的任意拓扑优势。

### 5.2 误差控制的自适应 Rectified-Flow 推理

核心假设：三个阶段统一使用固定 12 步 Euler 并非最优；不同样本和不同阶段需要的 NFE 不同。

首轮原型：

- 实现 Heun 作为高阶对照，按 NFE 而不是按“步数”比较。
- 使用 Euler-Heun 局部误差估计进行自适应步长和提前停止。
- 分别分析 sparse structure、shape、texture 三个阶段，避免用一个阈值覆盖所有阶段。
- 保留官方 guidance interval，并单独消融 guidance schedule，防止同时改变过多变量。

Go/No-Go：在质量指标等价区间内减少至少 25% NFE 或端到端延迟；或者在相同 NFE 下取得稳定的质量提升。报告均值和尾延迟。

主要风险：Heun 每步两次网络调用，减少步数不一定降低总时间；自适应分支也可能降低 GPU 执行稳定性。

### 5.3 冻结先验的单图几何测试时优化

该方向只处理相机和几何，避免与 PBR 方向重叠。

核心假设：冻结生成模型给出的 3D 结果可作为强先验，再通过单张条件图的 silhouette、DINO patch 和边缘约束优化可见几何。

首轮原型：

- 先优化相机姿态、焦距和尺度，再优化固定拓扑的 mesh vertex offset。
- 使用官方 MeshRenderer；优化目标包括 mask、特征、边缘、Laplacian 和偏离初始模型的正则。
- 不在首轮优化离散 edge flags；拓扑错误交由方向 5.1 或重新采样。
- 对不可见区域加入强先验和对称性可选约束，记录正面改善与背面退化。

Go/No-Go：条件视角 silhouette IoU 平均提高至少 0.03，DINO/LPIPS 显著改善，同时新视角 normal 质量、组件数和自交不出现系统性退化。

主要风险：单图监督会把几何过拟合到投影；可微渲染和大网格优化可能显存或时间过高。

### 5.4 光照解耦的 PBR 逆渲染校正

该方向替代当前包装器中按 RGB 均值/方差校色并强制 `metallic=0, roughness=0.5` 的做法；后者会破坏模型预测的 PBR 属性。

核心假设：以生成 PBR 为先验，联合优化 base color、metallic、roughness、alpha、曝光和低维环境光，可以改善输入一致性，同时保留可重光照能力。

首轮原型：

- 冻结几何，仅优化连续 PBR 属性与每图曝光/白平衡。
- 使用官方 PBR renderer 和提供的多张 HDRI。
- 加入材质先验、TV、能量范围和 alpha 稀疏正则。
- 在 Toys4K-PBR-dev 的合成观测上先验证，因为该设置有真实 PBR 属性可对照。
- 同时评估条件光照和未见 HDRI，防止把阴影烘焙进 base color。

Go/No-Go：PBR 属性平均 PSNR 提升至少 1dB或 LPIPS/MAE 改善至少 10%，且未见 HDRI 下的 shaded 指标不下降。

主要风险：单图材质与光照高度不适定；必须限制自由度，不能用任意高分辨率环境贴图吸收材质误差。

### 5.5 校准不确定性驱动的预算分配与重试

该方向不修改 ODE 积分器，与方向 5.2 分离；它研究样本级候选、失败预测和算力调度。

核心假设：不同种子和中间 `pred_x_0` 的分歧能够预测最终拓扑或材质失败，可用低成本预跑决定是否继续、换种子或提升分辨率。

首轮原型：

- 采集多种子 sparse occupancy、shape vertex/edge 和 PBR 方差。
- 从中间步骤构造不确定性特征，并与最终 MD、边界环、CLIP-N、PBR 误差关联。
- 设计固定预算下的 early reject、best-of-N 和按需增加步骤策略。
- 输出可靠性图与样本级置信度，不只输出一个未经校准的分数。

Go/No-Go：失败检测 AUROC 至少 0.75，或者在匹配质量下减少至少 20% 平均计算预算；同时报告 risk-coverage 曲线。

主要风险：多种子本身增加计算；若置信度只能在完整生成后得到，就没有调度价值。

## 6. 暂不进入五个主方向的想法

“语义化资产后处理”本轮不设独立 worktree。它与 Physical Modeling Agent 的长期目标一致，但主要提升部件编辑、碰撞和结构约束能力，不能直接用论文的重建或生成指标证明 TRELLIS.2 本体得到改善。

待五个方向完成首轮后，可把语义/物理资产化作为集成阶段：将最佳生成结果拆分为 visual、collision 和 volume geometry，并添加尺度、部件、关节和物性 provenance。它不与本轮五个无训练质量方向竞争资源。

多图联合生成也暂不设独立方向，因为真正的多图特征融合通常需要微调条件模块。多图仅可在单图 TTO 或 PBR 校正中作为额外观测扩展，不改变本轮“单图先验证”的基线。

## 7. 子 Agent 任务边界与交付物

每个子 Agent 只修改自己的 worktree，并交付：

1. `reports/idea.md`：假设、相关代码入口、与官方实现的差异。
2. 最小原型及单元测试。
3. `configs/` 下的可复现实验配置。
4. D0/D1/Toys4K-PBR-dev 的原始指标清单和汇总表。
5. 至少一个失败案例分析，不能只展示成功样例。
6. 明确的继续、合并或放弃建议。

公共评价代码和数据清单由主 Agent 维护。子 Agent 不得自行改变数据 split、基线输出、评价相机、后处理开关或模型权重。

## 8. 执行阶段与停止门槛

### Phase 0：基线冻结

- 建立独立官方源码仓库和初始 commit。
- 检查现有权重完整性和环境可导入性。
- 运行 D0 smoke test。
- 下载 Toys4K 元数据，复现 473 个 PBR 筛选口径，冻结 dev-50/holdout-423 清单并确认预计体积。
- 生成统一 `512^3` 基线与评价报告。

停止条件：权重或官方扩展不可用、D0 无法稳定运行、数据许可证不允许使用，或预计磁盘超过硬上限。

### Phase 1：五方向最小可行性

- 创建五个 worktree。
- 第一批运行 topology、flow、TTO；第二批运行 PBR、uncertainty。
- 每个方向先用 D0/D1 和固定的 Toys4K-PBR-dev-50。
- 达不到各自 Go/No-Go 门槛的方向停止扩展，但保留负结果报告。

### Phase 2：扩大评价

- 只扩大通过门槛的方向。
- 主要重建评价使用从未参与开发的 Toys4K-PBR-holdout-423；另报告完整 473 的论文口径次级结果，并使用可获得的 100 张官方生成条件图。
- 运行多种子、统计显著性和交叉失败分析。
- 选择最多两个方向做组合实验，避免五项同时叠加后无法归因。

### Phase 3：集成候选

优先组合互补模块，例如：

```text
自适应 Flow
→ 不确定性筛选
→ 结构一致性解码
→ 单图几何 TTO
→ PBR 逆渲染
```

组合实验仍需逐项消融，并与相同总计算预算的官方基线比较。

## 9. 执行前检查清单

- [ ] 用户批准本计划和最终五个方向。
- [ ] 确认建立独立 TRELLIS.2 研究仓库，而不是提交当前外层仓库的全部 staged 文件。
- [ ] 固定官方源码 commit 和权重 checksum。
- [ ] 确认数据下载许可证、URL、体积和磁盘预算。
- [ ] 确认不重复下载现有约 20GB 权重。
- [ ] 先跑 D0，再下载或处理完整测试集。
- [ ] 基线报告通过后才创建五个 worktree。
- [ ] 五个子 Agent 分两批运行，遵守最多 4 个并发槽位限制。
- [ ] 所有大文件路径均在 Git 之外，并有 manifest 可追踪。
- [ ] 每个方向先报告失败模式，再决定是否扩大实验。
