# `physical_agent` 内部架构说明

## 1. 文档目的

本文档用于说明 `src/physical_agent` 包内部的整体架构，包括：

- 各一级目录的职责；
- 各模块之间的依赖关系；
- 3D 建模相关代码应该放置的位置；
- 几何领域模型、几何生成算法与物理仿真的边界；
- 第一阶段建议创建的目录和空接口；
- 后续从图片理解扩展到物理仿真的完整流程。

本项目的最终目标是构建一个物理建模智能体：

```text
图片 / 文本描述
        ↓
物体与结构理解
        ↓
几何模型规划
        ↓
程序化 3D 建模
        ↓
物理属性补全
        ↓
仿真模型编译
        ↓
物理仿真
        ↓
结果检查、修正与解释
```

因此，`physical_agent` 不能只看作一个普通的 3D 建模程序，而应当被设计成一个由智能理解、领域建模、几何生成、物理仿真和验证模块组成的完整系统。

---

## 2. 当前一级目录

当前 `src/physical_agent` 下包含：

```text
physical_agent/
├── application/
├── domain/
├── geometry_engine/
├── infrastructure/
├── intelligence/
├── presentation/
├── simulation/
└── validation/
```

每一层的基本职责如下：

| 目录 | 核心职责 |
|---|---|
| `presentation` | 接收输入、展示结果 |
| `application` | 编排完整业务流程 |
| `domain` | 定义核心领域对象和规则 |
| `intelligence` | 图像理解、模型选择与几何规划 |
| `geometry_engine` | 将几何描述转换为实际 3D 几何 |
| `simulation` | 将模型编译并运行到物理引擎 |
| `validation` | 检查几何、物理和仿真结果 |
| `infrastructure` | 配置、日志、缓存、序列化和文件存储 |

---

## 3. 总体架构

推荐采用分层架构：

```text
┌──────────────────────────────────────┐
│ Presentation                         │
│ Web / API / CLI / 结果展示            │
├──────────────────────────────────────┤
│ Application                          │
│ 流程编排 / 状态管理 / 错误恢复         │
├──────────────────────────────────────┤
│ Domain                               │
│ 几何 / 物理 / 任务 / 不确定性模型      │
├──────────────────────────────────────┤
│ Intelligence                         │
│ VLM / 模型选择 / 几何规划 / 主动提问   │
├──────────────────────────────────────┤
│ Geometry Engine + Simulation         │
│ 几何生成 / 仿真编译 / 物理执行         │
├──────────────────────────────────────┤
│ Validation + Infrastructure          │
│ 校验 / 修复 / 配置 / 日志 / 存储       │
└──────────────────────────────────────┘
```

核心思想是：

> `domain` 定义“模型是什么”，  
> `geometry_engine` 实现“模型怎样生成”，  
> `simulation` 实现“模型怎样运动”。

---

## 4. 依赖方向

推荐的依赖方向为：

```text
presentation
      ↓
application
      ↓
domain
```

其他模块通过接口与应用层或领域层协作：

```text
intelligence ──────┐
geometry_engine ───┼──→ application / domain interfaces
simulation ────────┤
validation ────────┤
infrastructure ────┘
```

应避免以下依赖：

```text
domain → PyBullet
domain → trimesh
domain → Open3D
domain → VLM API
domain → Gradio

geometry_engine → presentation
simulation → intelligence
validation → presentation
```

特别是 `domain` 必须保持纯净，不能绑定具体外部库。

---

## 5. `application`

### 5.1 职责

`application` 是整个系统的流程编排层。

它负责：

- 接收经过表现层整理的输入；
- 调用感知模块；
- 调用模型选择模块；
- 调用几何规划模块；
- 调用几何引擎；
- 调用仿真编译器；
- 调用具体仿真后端；
- 调用验证模块；
- 管理任务状态；
- 保存中间结果；
- 在失败时决定重试、修复或向用户提问。

它不负责：

- 生成球体或圆环的顶点；
- 计算转动惯量；
- 调用 PyBullet 的底层 API；
- 直接解析图片内容。

### 5.2 推荐结构

```text
application/
├── __init__.py
├── pipeline.py
├── context.py
├── modeling_service.py
├── simulation_service.py
└── exceptions.py
```

`pipeline.py` 负责串联完整流程；`context.py` 保存中间状态；`modeling_service.py` 编排建模过程。

---

## 6. `domain`

### 6.1 职责

`domain` 保存项目最核心、最稳定的领域模型。

它描述：

- 物体是什么；
- 几何结构是什么；
- 物理属性是什么；
- 一次仿真任务是什么；
- 哪些信息是观测、假设和未知；
- 仿真结果如何表示。

`domain` 中的代码应与任何具体外部库无关。

### 6.2 推荐结构

```text
domain/
├── __init__.py
├── object_model.py
│
├── geometry/
│   ├── __init__.py
│   ├── geometry.py
│   ├── nodes.py
│   ├── primitives.py
│   ├── operations.py
│   ├── transform.py
│   └── mesh_reference.py
│
├── physics/
│   ├── __init__.py
│   ├── body.py
│   ├── material.py
│   ├── contact.py
│   ├── inertia.py
│   └── state.py
│
├── task/
│   ├── __init__.py
│   ├── simulation_task.py
│   └── target_quantity.py
│
├── uncertainty/
│   ├── __init__.py
│   ├── estimate.py
│   ├── hypothesis.py
│   └── provenance.py
│
└── results/
    ├── __init__.py
    ├── trajectory.py
    └── simulation_result.py
```

### 6.3 `domain/geometry`

这里负责描述“一个几何模型是什么”，不生成顶点，也不执行布尔运算。

`nodes.py` 定义几何节点基类：

```python
class GeometryNode:
    node_id: str
    transform: "Transform"
```

`primitives.py` 定义参数化基础体：

```python
class SphereNode(GeometryNode):
    radius: float

class BoxNode(GeometryNode):
    size: tuple[float, float, float]

class CylinderNode(GeometryNode):
    radius: float
    height: float

class TorusNode(GeometryNode):
    major_radius: float
    minor_radius: float
```

后续可以扩展：

```text
EllipsoidNode
ConeNode
FrustumNode
CapsuleNode
PlaneNode
AnnularCylinderNode
```

`operations.py` 定义组合关系：

```python
class UnionNode(GeometryNode):
    children: list[GeometryNode]

class DifferenceNode(GeometryNode):
    base: GeometryNode
    subtract: GeometryNode

class IntersectionNode(GeometryNode):
    children: list[GeometryNode]
```

`transform.py` 定义局部变换：

```python
class Transform:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    scale: tuple[float, float, float]
```

建议统一：

```text
长度单位：m
质量单位：kg
时间单位：s
坐标系：右手系
竖直方向：+z
四元数顺序：[x, y, z, w]
```

`geometry.py` 定义完整几何模型：

```python
class GeometryModel:
    visual_geometry: GeometryNode
    collision_geometry: GeometryNode | None
    volume_geometry: GeometryNode | None
```

三种几何分别用于渲染、碰撞和质量属性计算。

### 6.4 `domain/physics`

这里定义物体的物理属性：

- `body.py`：动态、静态和运动学物体；
- `material.py`：密度、材料类别和参数来源；
- `contact.py`：摩擦、恢复系数和接触参数；
- `inertia.py`：惯量表示；
- `state.py`：位姿、线速度和角速度。

### 6.5 `object_model.py`

完整物体模型由几何与物理属性组成：

```python
class ObjectModel:
    object_id: str
    name: str
    category: str
    geometry: GeometryModel
    physics: PhysicalProperties
    appearance: object | None
    uncertainty: object | None
```

---

## 7. `geometry_engine`

### 7.1 职责

`geometry_engine` 负责将 `domain/geometry` 中的抽象模型转换为实际几何。

输入：

```text
GeometryModel / GeometryNode
```

输出：

```text
MeshData
CollisionGeometry
MassProperties
```

它负责：

- 生成基础体；
- 执行几何变换；
- 执行 CSG 布尔运算；
- 生成旋转体和扫掠体；
- 加载外部 mesh；
- 清理和验证网格；
- 构造碰撞代理；
- 计算体积、质心和惯量。

### 7.2 推荐结构

```text
geometry_engine/
├── __init__.py
├── interface.py
├── compiler.py
├── mesh_data.py
│
├── procedural/
│   ├── __init__.py
│   ├── primitives.py
│   ├── transforms.py
│   ├── csg.py
│   ├── revolve.py
│   └── sweep.py
│
├── mesh/
│   ├── __init__.py
│   ├── loader.py
│   ├── validation.py
│   ├── cleanup.py
│   └── mass_properties.py
│
└── collision/
    ├── __init__.py
    ├── proxy.py
    ├── convex_hull.py
    └── decomposition.py
```

### 7.3 统一接口

```python
from abc import ABC, abstractmethod

class GeometryEngine(ABC):

    @abstractmethod
    def build_visual_mesh(
        self,
        geometry: "GeometryModel",
    ) -> "MeshData":
        raise NotImplementedError

    @abstractmethod
    def build_collision_geometry(
        self,
        geometry: "GeometryModel",
    ) -> "CollisionGeometry":
        raise NotImplementedError

    @abstractmethod
    def compute_mass_properties(
        self,
        geometry: "GeometryModel",
        density: float,
    ) -> "MassProperties":
        raise NotImplementedError
```

### 7.4 `compiler.py`

`GeometryCompiler` 递归读取 Geometry Tree：

```text
SphereNode       → build_sphere
BoxNode          → build_box
CylinderNode     → build_cylinder
TorusNode        → build_torus
UnionNode        → 编译子节点并执行并集
DifferenceNode   → 编译 base 和 subtract 后执行差集
MeshReferenceNode→ 加载外部文件
```

### 7.5 `mesh_data.py`

定义统一网格输出：

```python
class MeshData:
    vertices: object
    faces: object
    normals: object | None
    bounds: object | None
```

实际运行时可以用 NumPy 数组。

---

## 8. `intelligence`

### 8.1 职责

`intelligence` 负责决定：

- 图片里是什么物体；
- 应选择什么物理模型；
- 应使用哪些基础几何；
- 几何树应该如何构造；
- 哪些参数来自观察；
- 哪些参数是推测；
- 哪些信息需要向用户询问。

它不负责生成顶点、执行布尔运算或调用 PyBullet。

### 8.2 推荐结构

```text
intelligence/
├── __init__.py
├── perception/
│   ├── __init__.py
│   ├── interface.py
│   ├── mock_perception.py
│   └── vlm_adapter.py
├── model_selection/
│   ├── __init__.py
│   ├── selector.py
│   └── rules.py
├── geometry_planning/
│   ├── __init__.py
│   ├── planner.py
│   └── parser.py
├── hypothesis/
│   ├── __init__.py
│   ├── generator.py
│   └── material_priors.py
└── active_query/
    ├── __init__.py
    ├── sensitivity.py
    └── question_generator.py
```

`geometry_planning` 负责把感知结果转换为 Geometry Tree，例如：

```text
识别为甜甜圈
→ TorusNode

识别为杯子
→ DifferenceNode(CylinderNode, CylinderNode)
  + TorusNode

识别为瓶子
→ RevolveNode(profile)
```

---

## 9. `simulation`

### 9.1 职责

`simulation` 只负责将已经完成的物体模型编译并运行到具体物理引擎。

输入：

```text
ObjectModel
SimulationTask
BuiltGeometry
```

输出：

```text
CompiledSimulation
SimulationResult
```

### 9.2 推荐结构

```text
simulation/
├── __init__.py
├── interface.py
├── compiler.py
├── backends/
│   ├── __init__.py
│   ├── mock_backend.py
│   ├── analytical_backend.py
│   └── pybullet_backend.py
└── recording/
    ├── __init__.py
    ├── trajectory_recorder.py
    └── video_recorder.py
```

`compiler.py` 负责：

- 将 mesh 转换为仿真器资源；
- 建立碰撞体；
- 设置质量、质心和惯量；
- 设置摩擦和恢复系数；
- 设置初始位姿、重力和外力。

`pybullet_backend.py` 只放与 PyBullet 直接相关的代码。

---

## 10. `validation`

### 10.1 职责

`validation` 负责检查输入模型、生成几何和仿真结果是否合理。

### 10.2 推荐结构

```text
validation/
├── __init__.py
├── schema_checker.py
├── geometry_checker.py
├── physics_checker.py
├── result_checker.py
└── repair.py
```

检查内容包括：

- 参数范围；
- Geometry Tree 合法性；
- mesh 是否封闭；
- 是否存在退化面；
- 质量和惯量是否合法；
- 恢复系数是否在 `[0, 1]`；
- 是否出现 NaN；
- 是否存在严重穿透；
- 能量是否异常增长。

---

## 11. `infrastructure`

### 11.1 职责

`infrastructure` 负责：

- 配置读取；
- 日志；
- 文件路径；
- JSON/YAML 序列化；
- 缓存；
- 外部 API；
- 资源存储。

### 11.2 推荐结构

```text
infrastructure/
├── __init__.py
├── config.py
├── logging.py
├── cache.py
├── serialization.py
├── file_storage.py
└── external_clients/
    ├── __init__.py
    └── vlm_client.py
```

VLM 的业务适配逻辑放在 `intelligence`，底层 API 客户端放在 `infrastructure`。

---

## 12. `presentation`

### 12.1 职责

`presentation` 负责：

- 上传图片；
- 输入问题；
- 补充尺寸或材料；
- 展示 Geometry Tree；
- 展示候选模型；
- 展示仿真动画；
- 展示验证报告；
- 接收主动提问的回答。

### 12.2 推荐结构

```text
presentation/
├── __init__.py
├── cli.py
├── api/
│   ├── __init__.py
│   ├── routes.py
│   └── schemas.py
└── web/
    ├── __init__.py
    └── app.py
```

第一阶段可以暂时只保留空目录。

---

## 13. 3D 建模代码的位置总结

3D 建模分布在三个模块中。

### 13.1 建模数据定义

放在：

```text
domain/geometry/
```

负责定义基础体、Geometry Tree、变换、布尔关系和 mesh 引用。

### 13.2 建模算法实现

放在：

```text
geometry_engine/
```

负责生成顶点和三角形、执行变换与布尔运算、生成碰撞体和计算质量属性。

### 13.3 智能几何规划

放在：

```text
intelligence/geometry_planning/
```

负责根据图片理解结果选择基础体、规划 Geometry Tree，并判断使用 primitive、CSG、revolve 或 sweep。

三者关系为：

```text
Intelligence
决定“用什么结构表示”
        ↓
Domain
保存“结构是什么”
        ↓
Geometry Engine
实现“如何生成实际几何”
```

---

## 14. 第一阶段建议创建的空架构

```text
src/physical_agent/
├── application/
│   ├── __init__.py
│   ├── pipeline.py
│   ├── context.py
│   └── modeling_service.py
├── domain/
│   ├── __init__.py
│   ├── object_model.py
│   ├── geometry/
│   │   ├── __init__.py
│   │   ├── geometry.py
│   │   ├── nodes.py
│   │   ├── primitives.py
│   │   ├── operations.py
│   │   ├── transform.py
│   │   └── mesh_reference.py
│   ├── physics/
│   │   ├── __init__.py
│   │   ├── body.py
│   │   ├── material.py
│   │   ├── contact.py
│   │   ├── inertia.py
│   │   └── state.py
│   ├── task/
│   │   ├── __init__.py
│   │   └── simulation_task.py
│   └── results/
│       ├── __init__.py
│       └── simulation_result.py
├── geometry_engine/
│   ├── __init__.py
│   ├── interface.py
│   ├── compiler.py
│   ├── mesh_data.py
│   ├── procedural/
│   │   ├── __init__.py
│   │   ├── primitives.py
│   │   ├── transforms.py
│   │   ├── csg.py
│   │   ├── revolve.py
│   │   └── sweep.py
│   ├── mesh/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   ├── validation.py
│   │   ├── cleanup.py
│   │   └── mass_properties.py
│   └── collision/
│       ├── __init__.py
│       ├── proxy.py
│       ├── convex_hull.py
│       └── decomposition.py
├── intelligence/
│   ├── __init__.py
│   ├── perception/
│   │   ├── __init__.py
│   │   ├── interface.py
│   │   └── mock_perception.py
│   └── geometry_planning/
│       ├── __init__.py
│       ├── planner.py
│       └── parser.py
├── simulation/
│   ├── __init__.py
│   ├── interface.py
│   ├── compiler.py
│   └── backends/
│       ├── __init__.py
│       ├── analytical_backend.py
│       └── pybullet_backend.py
├── validation/
│   ├── __init__.py
│   ├── geometry_checker.py
│   └── physics_checker.py
├── infrastructure/
│   ├── __init__.py
│   ├── config.py
│   ├── logging.py
│   ├── serialization.py
│   └── file_storage.py
└── presentation/
    ├── __init__.py
    ├── cli.py
    └── web/
        ├── __init__.py
        └── app.py
```

---

## 15. 第一阶段真正需要实现的内容

第一阶段只需实现最小链路：

```text
domain/geometry/nodes.py
domain/geometry/primitives.py
domain/geometry/geometry.py
domain/physics/body.py
domain/object_model.py

geometry_engine/interface.py
geometry_engine/compiler.py
geometry_engine/mesh_data.py
geometry_engine/procedural/primitives.py

simulation/interface.py
simulation/backends/analytical_backend.py
simulation/backends/pybullet_backend.py

validation/geometry_checker.py
validation/physics_checker.py

application/pipeline.py
application/context.py

intelligence/perception/mock_perception.py
```

第一批基础体：

```text
sphere
box
cylinder
torus
```

第一条完整链路：

```text
Mock 输入
→ TorusNode
→ GeometryModel
→ GeometryCompiler
→ MeshData
→ ObjectModel
→ PyBulletBackend
→ SimulationResult
→ PhysicsChecker
```

推荐第一个 Demo：

> 一个圆环从固定高度自由下落，记录其轨迹、姿态和第一次碰撞。

---

## 16. 代码组织规则

1. 每个 Python 包都创建 `__init__.py`。
2. `domain` 不导入 PyBullet、trimesh、Open3D、Gradio 等外部实现库。
3. 模块间传递明确的领域对象，不长期传递任意字典。
4. 所有外部能力通过接口接入。
5. 优先使用 Mock 模块打通流程。
6. 避免循环依赖。
7. 几何描述、几何实现和仿真运行必须分离。
8. 每个阶段保留可测试、可替换的边界。

---

## 17. 完整调用示意

```python
request = presentation.read_request()

context = PipelineContext(
    request_id=request.request_id,
    input_request=request,
)

perception_result = perception_service.analyze(request)
context.perception_result = perception_result

geometry_model = geometry_planner.plan(perception_result)

visual_mesh = geometry_engine.build_visual_mesh(
    geometry_model
)

collision_geometry = geometry_engine.build_collision_geometry(
    geometry_model
)

object_model = modeling_service.create_object_model(
    geometry_model=geometry_model,
    visual_mesh=visual_mesh,
    collision_geometry=collision_geometry,
)

compiled_simulation = simulation_backend.compile(
    object_model,
    request.simulation_task,
)

simulation_result = simulation_backend.run(
    compiled_simulation
)

validation_report = result_validator.validate(
    request.simulation_task,
    simulation_result,
)

presentation.show_result(
    object_model,
    simulation_result,
    validation_report,
)
```

---

## 18. 架构结论

当前应正式确定：

1. `domain/geometry` 保存几何领域模型；
2. `geometry_engine` 保存实际几何生成算法；
3. `intelligence/geometry_planning` 保存智能几何规划逻辑；
4. `domain/physics` 保存物理属性；
5. `simulation` 负责具体物理引擎；
6. `application` 负责串联流程；
7. `validation` 负责检查和修复；
8. `infrastructure` 负责配置、日志和存储；
9. `presentation` 只负责用户交互；
10. 所有模块通过明确接口和领域对象通信。

最重要的一句话是：

> 建模的“描述”属于 `domain`，建模的“实现”属于 `geometry_engine`，建模的“智能决策”属于 `intelligence`，建模后的“物理运行”属于 `simulation`。
