# 机器人交互与 Blender 高质量回放

这一部分连接项目的前期建模和后期机器人交互：

```text
相机/视频 -> Blender/GLB 场景 -> PyBullet 执行用户指令
         -> 逐帧轨迹 JSON -> Blender 动画、预览图和 MP4
```

PyBullet 负责机械臂运动、抓取逻辑和轨迹计算；Blender 负责最终场景、材质、灯光、相机和动画渲染。Blender 不会重新计算 IK，因此回放姿态与仿真完全一致。

现在同时支持两种工作模式：

- **实时交互**：Blender 连接 PyBullet，用户输入指令后直接在当前场景中看到机械臂运动。
- **离线回放**：记录完整轨迹后生成 Blender 工程、预览图和 MP4。

实时模式的完整运行方法见 [LIVE_INTERACTION.md](LIVE_INTERACTION.md)。

## 最快演示

在项目根目录执行：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.record_robot_run `
  --run-id final_demo `
  --commands "抓取; 抬起; 放到右边; 复位" `
  --render
```

没有传入模型或环境时，系统自动使用红色方块和 Blender 工作台场景。

## 接入前期模型

`--object` 是需要操作的重建物体，`--environment` 是前期搭建的完整环境：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.record_robot_run `
  --run-id final_scene `
  --object outputs\video_xxx\export\reconstructed.glb `
  --object-scale 0.05 `
  --object-position 0.5,0,0.66 `
  --environment path\to\modeled_environment.blend `
  --commands "抓取; 抬起; 放到右边; 复位"
```

PyBullet 不能原生读取 GLB 碰撞网格。本项目会把 GLB/GLTF 自动转换成缓存 OBJ，并完成 glTF 的 Y-up 到项目 Z-up 坐标转换；Blender 回放仍使用原始 GLB，保留材质和细节。

## Blender 渲染

快速预览：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.render_robot_run_blender `
  --run-dir outputs\robot_runs\final_scene `
  --samples 4 `
  --resolution 960x540
```

最终视频：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.render_robot_run_blender `
  --run-dir outputs\robot_runs\final_scene `
  --samples 16 `
  --resolution 1280x720 `
  --video
```

需要更高画质时可加 `--engine cycles --samples 64`，但 CPU 渲染会明显变慢。

## 场景对齐

项目默认使用右手坐标系、Z 轴向上、单位为米：

- 默认桌面高度：`z=0.626`
- 默认机械臂基座：`0,-0.35,0.626`
- 默认物体基座：`0.5,0,0.66`

仿真阶段可用 `--robot-base x,y,z` 和 `--object-position x,y,z` 调整机械臂与物体。

Blender 环境的原点或朝向不同时，在渲染命令中使用：

```powershell
--world-offset 0,0,0.124 --world-scale 1.0 --world-rotation-z 90
```

`--world-offset` 平移整段交互，`--world-scale` 缩放机械臂和交互物体，`--world-rotation-z` 绕 Z 轴旋转。建议先用低采样预览校准，再生成最终视频。

## 输出文件

```text
outputs/robot_runs/<run_id>/
|-- trajectory.json              # 每帧连杆、夹爪、末端和物体位姿
|-- commands.json                # 用户指令及起止帧
|-- scene_manifest.json          # 模型、环境、坐标系和采样参数
`-- render/
    |-- robot_replay.blend        # 可直接打开和继续调整
    |-- preview.png
    |-- robot_interaction.mp4     # 使用 --video 时生成
    `-- render_report.json
```

源环境 `.blend` 不会被覆盖；回放始终保存到当前 run 的 `render/robot_replay.blend`。

## 其他入口

实时命令控制：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.command_robot
```

交互训练基线：

```powershell
D:\Anaconda_envs\envs\x\python.exe -m simulation.scripts.train_interaction `
  --episodes 8 --eval-episodes 4 --no-gui
```
