# Blender 实时机器人交互

实时模式由两个进程组成：Conda Python 运行 PyBullet 服务，Blender 插件显示交互界面并更新机械臂。网络只监听本机 `127.0.0.1`，默认端口为 `8765`。

## 一键启动

先关闭占用 `8765` 端口的旧进程，然后在项目根目录运行：

```powershell
cd D:\projects\aigc

D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction
```

该命令会启动 PyBullet、打开 Blender、加载 Robot 插件、生成演示工作台并自动连接。

接入前期 Blender 环境和重建物体：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --environment "D:\path\to\modeled_environment.blend" `
  --object "outputs\video_xxx\export\reconstructed.glb" `
  --object-scale 0.05 `
  --object-position 0.5,0,0.66
```

关闭 Blender 后，启动器会自动停止对应的 PyBullet 服务，不会遗留后台端口。

## Blender 中的操作

Blender 打开后：

1. 在 3D 视口按 `N` 打开右侧栏。
2. 控制区会直接出现在当前 `Item` 分类的 `Transform` 下方；也可以选择独立的 `Robot` 标签。
3. 如果窗口高度较小，在右侧栏内向下滚动找到 `Robot Interaction`。
4. 顶部显示 `Connected` 后即可操作。
5. 在输入框中输入中文或英文指令，点击 `Execute Command`。

可用快捷按钮：

- `Pick`：移动到物体上方、下降并抓取。
- `Lift`：抬起当前物体。
- `Release`：松开物体。
- `Open` / `Close`：控制夹爪。
- `Home`：机械臂平滑回到初始关节姿态。
- `Place L` / `Place R`：放到初始位置左侧或右侧。
- `Reset`：同时复位机械臂和物体。
- `Stop`：中断当前动作并清空排队命令。

文本指令示例：

```text
抓取
抬起
放到右边
向上移动 0.1
move 0.5 0.0 0.9
delta 0.0 0.1 0.0
打开夹爪
复位
```

## 物理控制与接触判定

实时模式不是预制动画。七个机械臂关节使用逆动力学计算力矩，并按 Franka Panda 的关节力矩上限截断；运行时轨迹不会调用 `resetJointState` 瞬移关节。桌面、机械臂和物体之间的碰撞始终启用。

抓取必须连续满足以下条件才会成功：

- 左右手指都与物体产生至少 `1 N` 的真实 PyBullet 接触力。
- 两侧接触法线方向相反，并且物体中心位于两个接触点之间。
- 条件连续稳定 8 个物理步后，才建立最大 `35 N` 的有限力固定约束，补偿 PyBullet 中小物体纯摩擦夹持容易数值滑落的问题。
- 未接触、单侧接触或物体尺寸超过夹爪开口时，命令返回 `failed`，不会从远处吸附物体。

Blender 视口在有效接触点显示蓝色和橙色力箭头，箭头指向手指施加到物体上的力方向，长度随力变化。面板中的 `Left finger`、`Right finger` 和 `Contact` 可用于核对接触力与力闭合状态。

GLB/GLTF 首次加载时会自动生成并缓存 VHACD 凸分解碰撞代理。视觉仍使用原始重建网格，接触计算使用贴合网格的凸块组合，不再使用整块包围盒。首次分解通常需要数秒，缓存位于 `outputs/simulation_cache`。

## 自适应 6D 抓取规划

`Pick` 不再使用固定的物体中心和俯视角。系统会从 Active Object 的原始网格采样表面点与法向，在夹爪最大开口 `0.078 m` 内搜索法向相反的接触点对，并为每个点对生成多个接近方向。候选包含三维抓取点和四元数朝向，因此能够处理斜面、非对称物体和偏心模型。

候选按对向接触质量、物体质心距离、顶部接近程度和夹爪余量评分，再使用 Panda 的真实关节上下限做 IK/FK 误差检查，并验证从当前姿态到预抓取点的无碰撞关节路径。Blender 中的 `LIVE_Planned_Grasp` 坐标轴显示最终候选，面板同时显示规划器来源和评分。网格无法解析时才退回包围盒候选，并在结果中标记为 `aabb_fallback`。

执行时最多依次尝试评分最高的三个候选。只有双指实际接触力、相反法向和物体居中条件全部成立后才建立有限力约束；候选在几何上可行但未形成真实力闭合时，`Pick` 仍会失败，不会把物体吸到夹爪上。

## 目标点交互

1. 点击 `Create Target`，Blender 会创建带坐标轴的 `Robot_Target`。
2. 使用 Blender 移动和旋转工具设置目标位置与朝向。
3. `Snap Target` 会把目标投影到已知桌面或地面。
4. 从菜单选择操作，点击 `Check Feasibility` 查看物理可行性。
5. 使用 `Move EE`、`Place`、`Push` 或 `Rotate` 执行动作。

Target 是任务目标，不会直接改动物体位姿：

- `Move EE`：Target 位置是机械臂末端目标，桌面以下位置会触发安全限制。
- `Place`：Target 的 XY 是放置位置，Z 自动投影到桌面或地面；Target 旋转是物体最终朝向。
- `Push`：Target 的 XY 是物体目标位置。机械臂先沿无物体碰撞路径回到中立姿态，在四个物理等价腕部朝向中选择满足关节限制的解，建立真实接触后再用雅可比转置笛卡尔力控制推动；不创建抓取约束。
- `Rotate`：使用 Target 旋转作为物体目标朝向。只有双指真实抓取后才能执行。
- `Pick` 可行性：生成并评分 6D 对向抓取候选，检查夹爪宽度、物体质量、关节限制、IK/FK 误差和预抓取碰撞路径。

Target 颜色表示最近一次检查结果：绿色可行，红色不可行，橙色表示尚未检查。面板会显示不可行原因和预测指标，例如物体宽度、负载、启动推力或工作空间限制。

插件会自动把目标点从 Blender 世界坐标转换回 PyBullet 仿真坐标，因此 Replay Alignment 的平移、缩放和旋转同样有效。

目前 `Snap Target` 和物理支撑检测覆盖演示桌面与地面。导入自定义 `.blend` 只提供视觉环境；如果需要把物体放到自定义架子、柜面或斜坡上，还必须把对应碰撞体同步加入 PyBullet。

## 自动准备未知 GLB

未知 GLB 不再需要先写一套专用动作。预处理器会执行体素连通聚类，保留原始高分辨率网格和材质，为每个实体生成独立 GLB，并估计质量、摩擦区间及置信度：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.prepare_interactive_scene `
  --input "generate_3Dmodel\generate_3Dmodel\output_chair.glb" `
  --source-image "generate_3Dmodel\generate_3Dmodel\chair_input.jpg" `
  --output "outputs\prepared_chair_scene" `
  --target-max-dimension 0.90
```

没有本地语义模型时，实体会自动命名为 `entity_01`、`entity_02`；最大的实体默认设为动态 Active Object，其他实体为静态环境。名称不参与动作判断。上游视觉模型已经识别出类别时，可一次性写入标签和校准后的物理值：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.prepare_interactive_scene `
  --input "generate_3Dmodel\generate_3Dmodel\output_chair.glb" `
  --source-image "generate_3Dmodel\generate_3Dmodel\chair_input.jpg" `
  --output "outputs\prepared_chair_scene" `
  --scale 0.9 `
  --labels chair,plant `
  --active chair `
  --active-mass 6 `
  --active-friction 0.3
```

输出结构：

```text
outputs/prepared_chair_scene/
|-- scene_manifest.json
`-- objects/
    |-- chair.glb
    `-- plant.glb
```

启动多物体场景：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --scene-profile floor `
  --scene-manifest "outputs\prepared_chair_scene\scene_manifest.json" `
  --robot-base "0,-0.35,0"
```

Blender 面板中的 `Scene Objects > Active` 用于选择当前操作实体。动态椅子可以进行 Push 可行性检查；静态绿植会明确返回 `active object is static`。所有实体拥有独立 PyBullet Body、碰撞体、实时位姿和录制轨道，因此推动椅子不会再绑定绿植。

GLB 本身不能提供真实质量和摩擦。自动值的 `property_status` 为 `estimated`，manifest 同时保存 `min/estimate/max/source/confidence`，表示虚拟仿真的合理假设，不是现实测量结果。`--active-mass` 和 `--active-friction` 会把 Active Object 对应属性标记为用户校准且置信度为 `1.0`。

`Move EE` 现在是无接触动作：执行前会采样关节路径检查所有场景实体，执行中非预期接触超过 `2 N` 会停止。需要主动接触物体时必须使用 `Push`。

## 桌面与地面场景

小物体使用默认桌面场景：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --object "D:\path\to\apple.glb" `
  --object-scale 0.08 `
  --object-mass 0.18 `
  --object-friction 0.6
```

地面物体使用 `floor` 场景。启动器会移除演示桌面、把物体底部放到 `z=0`，并默认把 Panda 基座放到地面：

### 椅子：真实接触推动

仓库中的椅子模型可以直接用下面的参数运行。`0.9` 是把生成模型标定到约 `0.90 x 0.65 x 0.77 m` 的现实尺寸，不是为了适配夹爪而缩小：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --scene-profile floor `
  --object "generate_3Dmodel\generate_3Dmodel\output_chair.glb" `
  --object-scale 0.9 `
  --object-position "0.75,0.15,0.70" `
  --object-mass 6.0 `
  --object-friction 0.3 `
  --robot-base "0,-0.35,0"
```

进入 Blender 后：

1. 点击 `Create Target`，把 Target 放在椅子当前位置的 `+X` 方向约 `0.10-0.15 m`。
2. 点击 `Snap Target`，在操作菜单选择 `Push`。
3. 点击 `Check Feasibility`；Target 变绿后点击 `Push`。

椅子是镂空模型，系统会对 VHACD 碰撞代理做射线探测，选择真实存在的椅面或框架作为受力点，再验证预接触、接触和推动终点三个姿态的 IK/FK 误差。不要把 Target 一次移动超过 `0.40 m`；固定基座 Panda 无法围到椅子背面时，换推动方向或用 `--robot-base` 调整基座位置。

### 沙发：保留真实尺寸并拒绝不可行动作

三人沙发应先按已知宽度做一次米制标定。当前 `output_1.glb` 以最大尺寸约 `2 m` 演示时可使用：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --scene-profile floor `
  --object "generate_3Dmodel\generate_3Dmodel\output_1.glb" `
  --object-scale 2.0 `
  --object-position "1.40,0.75,1.20" `
  --object-mass 60.0 `
  --object-friction 0.5 `
  --robot-base "0,-0.35,0"
```

对沙发仍然使用同样的 `Create Target -> Snap Target -> Push -> Check Feasibility` 流程。该参数下启动推力估算约为 `294 N`，超过 Panda 的安全推力 `35 N`，Target 应变红并拒绝执行。这是正确结果：固定基座 Panda 既不能抓取沙发，也不应假装能推动它。要让沙发真正移动，需要把执行器换成移动底盘或更高推力机器人，再相应提高控制器的力矩、接触和稳定性限制。

系统不会为了完成动作自动缩小模型。`--object-scale` 只负责把生成器的归一化坐标标定为真实米制尺寸。推力估算超过 `35 N`、目标超出固定基座工作范围、抓取宽度超过 `0.078 m` 或质量超过 `3 kg` 时，对应操作会被拒绝。

## 实时录制

点击 `Record` 后，每个实时状态都会写入机械臂 11 个可视连杆和物体的 Blender 关键帧。点击 `Stop Recording` 结束，时间轴终点会停在最后一个录制状态。

录制完成后使用 Blender 的 `File > Save As` 保存 `.blend`，之后可以继续调整材质、灯光、相机或直接渲染。垃圾桶按钮会清除本次实时对象上的关键帧。

## 对齐前期环境

插件的 `Replay Alignment` 提供：

- `Offset`：平移整套机械臂、操作物体和演示工作台。
- `Scale`：统一缩放交互系统。
- `Z Rotation (deg)`：绕 Z 轴旋转。

仿真默认参数：

```text
桌面高度       z = 0.626 m
机械臂基座     0, -0.35, 0.626
物体初始基座   0.5, 0, 0.66
```

尽量让 Blender 环境使用 Z-up 和米制单位。环境不是米制时先调 `Scale`，再调旋转和平移。

Panda 夹爪最大开口约为 `0.08 m`。`--object-scale` 应让预期夹持方向的物体宽度小于该值，并留出手指厚度；尺寸不满足时物理抓取应当失败。例如当前样例 `reconstructed.glb` 的原始尺寸约为 `5.53 x 8.11 x 5.86`，使用默认 `0.05` 会得到约 `0.28 x 0.41 x 0.29 m`，无法抓取；该样例已验证可使用 `--object-scale 0.008`。

## 绑定环境中已有物体

如果操作物体已经包含在环境 `.blend` 中，不希望插件再次导入一份：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.launch_live_interaction `
  --environment "D:\path\to\environment.blend" `
  --object "D:\path\to\the_same_object.glb" `
  --no-auto-connect
```

Blender 打开后，选中环境中的目标物体，在 Robot 面板点击 `Bind Selected Object`，再点击 `Connect`。绑定必须在连接前完成。

## 分开启动

需要保留 Blender 会话或单独调试服务时，先运行：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.robot_server `
  --object "outputs\video_xxx\export\reconstructed.glb" `
  --object-scale 0.05
```

终端出现以下内容说明服务就绪：

```text
ROBOT_SERVER_READY 127.0.0.1:8765
```

服务可用终端客户端检查：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.live_robot_client `
  --commands "抓取; 抬起; 复位" `
  --move-to 0.5,0,0.9
```

## 持久安装 Blender 插件

生成安装包：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.package_blender_addon
```

输出文件为：

```text
outputs\blender_addons\robot_interaction.zip
```

在 Blender 中打开 `Edit > Preferences > Add-ons > Install from Disk`，选择该 ZIP 并启用 `Robot Interaction`。之后手动打开任意 `.blend`，运行 `robot_server`，再从 Robot 面板连接即可。

## 常见问题

- `Connection refused`：PyBullet 服务尚未启动，或面板端口与服务端口不同。
- `Port already in use`：已有服务占用 `8765`，关闭旧终端或改用 `--port 8766`。
- 机械臂不在桌面上：调整 Replay Alignment，或启动时修改 `--robot-base`。
- 环境里出现两个物体：使用 `--no-auto-connect` 和 `Bind Selected Object`。
- Blender 界面没有 Robot 标签：确认鼠标位于 3D 视口后按 `N`。
- 指令执行后立刻失败：查看面板中的 `Last Result`，未知指令会返回 `failed`，不会伪装成完成。
- `Grasp failed: both fingers...`：双指没有形成真实对向接触。检查物体缩放、碰撞代理、初始位置以及夹持方向。
- 首次加载 GLB 较慢：正在生成 VHACD 碰撞代理；相同模型后续启动会直接使用缓存。

## 自动验收

验证力矩上限、双指接触、抬升、自由落放、错位抓取失败和中途停止：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.verify_physical_interaction
```

验证 Target 可行性、两个方向的桌面推动、地面推动、旋转和定向放置：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.verify_target_actions
```

Blender 端到端报告保存在 `outputs/live_interaction_test/live_interaction_report.json`。当前验收覆盖抓取接触力箭头、录制、停止、目标点移动和复位。
