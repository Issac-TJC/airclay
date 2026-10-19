# 实时骨架驱动的三维手型预览

## 当前能力

`configs/hands.json` 启用 UDP v2 `hand_preview`。发送两手各 21 个二维关节和每手局部
MediaPipe world landmarks，Blender 用这些点驱动手型。面板 `Hand model` 提供三种显示：

- **Smooth blue hand（默认）**：按参考图右侧优化的浅蓝光滑手型，每手 14,499 顶点。
  焊接原模型接缝、平滑表面，加长并收窄腕口；统一掌部权重，避免掌骨独立拉伸形成折面。
  不使用皮肤纹理，实体视图与材质预览均显示蓝色。`Fingertip direction guides` 控制黄色指尖方向线，
  只用于观察，不代表接触或施力。
- **Realistic skin**：Elena FF 的写实手模型，保留原蒙皮权重、UV、肤色和粗糙度贴图；
  每手 16,330 顶点、28,994 三角面。映射到 21 个追踪点，生成左右手镜像，使用加权蒙皮更新网格。
- **Simple joints**：原来的球形指节、指段和实体手掌，每手 876 顶点，适合作为轻量调试显示。

三种模式均复用已有对象和拓扑，不逐帧创建 Blender 对象，可在接收中切换。
光滑模式的两手均为浅蓝色，以蓝/橙光标和图例区分身份；另外两种模式在默认实体视图中显示左蓝右橙。
写实模式切到 **Material Preview（材质预览）** 可看皮肤贴图，
也可在实体视图的着色下拉菜单中把 Color 改为 Texture。肤色模式下仍用蓝/橙光标和图例区分手身份。
不会自动改变用户的视口着色模式。身份不随惯用手设置改变。

物体中心前方的视图平面作为显示基准；图像位置决定关节的屏幕位置，每手腕部相对 z
用于呈现局部立体结构。场景尺度从显示平面的手掌大小得到。没有估计真实腕部根深度，
因此 UI 标注 `uncalibrated depth`。`Hand display depth` 只是显示平面偏移，不能当作物理标定。

为匹配当前反转摄像头的观察方向，默认开启 `Flip hand front/back`，翻转每手相对腕部的前后深度，
让手型与使用者的手平行。写实模型的皮肤厚度和表面朝向也随之翻转。
屏幕二维位置、腕部位置、左右手身份和捏合判定保持不变；不额外镜像输入画面。
如需恢复原先面对镜子的效果，可在 AirClay 面板关闭该开关，立即生效。

捏合反馈根据局部三维拇指—食指距离除以腕部—中指 MCP 距离计算，使用已有
`pinch_close/pinch_open` 迟滞阈值；仅显示 `PINCH/OPEN`，不发出雕刻或抓取命令。
无效骨架与断流隐藏手型、清除捏合显示；停止接收器时清理该接收器创建的手网格和材质。
关闭 `Show tracked hands` 只隐藏预览。生成的手对象不能被选择为雕刻目标，也没有刚体或碰撞修改器。
保存的 `.blend` 包含当时的静态手姿态；写实模式同时内嵌皮肤贴图。它不是完整动作录制。
模型资源不可读取时会回退至简化手，并在面板显示原因提示。

## 写实模型来源与适配

模型：[Rigged hand — Elena FF](https://sketchfab.com/3d-models/rigged-hand-eae97cc2a742413cb5338ab942b12c1e)，
按 **CC BY-SA 4.0** 使用，署名与许可随插件 ZIP 一起提供。
公开分发副本、原始 GLB 校验值、处理方式和衍生资源校验值记录在
[`hand_manifest.json`](../blender_addon/airclay_blender/assets/hand_manifest.json)，
完整署名见 [`HAND_LICENSE.txt`](../blender_addon/airclay_blender/assets/HAND_LICENSE.txt)。
发布包含该模型的修改版本时保留署名和相同资产许可。

`scripts/prepare_hand_asset.py` 从仓库内原始 GLB 提取绑定空间网格、UV、贴图和实际蒙皮权重。
运行时根据掌骨和指骨对应关系计算皮肤顶点；不加载源文件的动画、控制骨骼或外部脚本。
`scripts/prepare_smooth_hand.py` 生成参考风格衍生模型：焊接接缝、Taubin 平滑、修整腕部，
统一掌部并平滑蒙皮权重。处理记录见 `assets/smooth_manifest.json`（插件目录内）。
骨骼朝向使用绑定姿态的连续旋转，避免手指弯到视向约 90° 时因叉乘退化而突然翻转。
这是预设手型的实时拟合，不会重建使用者本人的皮肤、手形或准确手指厚度。
极端握拳、遮挡和不合理的关键点仍可能产生皮肤交叠，真人适配效果需单独检查。

实验性塑性开关仍默认关闭，碰撞继续使用追踪点驱动的十个简化指尖球；
替换显示皮肤不改变接触阈值、物理行为或 M0–M6 的主线验收范围。

## 运行

分别在两个终端运行：

```bash
bash scripts/start_blender.sh
```

```bash
.venv/bin/airclay --config configs/hands.json track --backend rules
```

`simulate` 可代替 `track` 展示合成开合与丢手恢复；旧 v1 录制可用相同配置 `replay`，
但只读取录制中已有的 21 关节与局部 world 信息，不生成相机深度。
旧 `configs/hover.json` 保持十指候选点显示，无配置仍运行 v1 操作。

## 协议补充

与 `hover2d` 使用相同版本号但独立 profile；同一 session 禁止切换 profile。
顶层增加 `local_world_space: "mediapipe_hand_centered_m"`，`depth_available` 仍为 `false`。
每只手改为 `valid`、`image`（21×2）、`local_world`（21×3）；不重复发送可从骨架提取的五个指尖。
坐标保留六位小数，测试覆盖双手最坏精度包体低于 4096 字节。
全部坐标必须为有限数值；图像坐标允许暂时越界但绝对值不超过 4，局部米坐标绝对值不超过 2。
这些是异常输入保护范围，不是相机测量精度。无效手的两组坐标都必须为空。
旧接收器会明确拒绝该 profile，需要重新启动或安装新版插件。

## 黏土形变方向（用户选择）

目标是**松手后保留捏出的形状**。原生 Blender Soft Body 可以通过 Collision 接收外部物体碰撞，
Edges 的 Plasticity 支持碰撞后的永久变形；普通 Rigid Body 只改变位置/朝向，不改变网格形状。
参考：[Soft Body Plasticity](https://docs.blender.org/manual/en/latest/physics/soft_body/settings/edges.html)、
[Rigid Body](https://docs.blender.org/manual/en/5.0/physics/rigid_body/introduction.html)。

已接入默认关闭的原生碰撞塑性实验，操作见 [PLASTICITY.md](PLASTICITY.md)。
它使用十个指尖碰撞球和独立场景中的低分辨率软体代理，把 Blender 计算出的位移映射到原网格。
可观察物体凹陷并在松手后保留，支持退出、取消、撤销/重做和断流暂停；不推进用户场景的时间轴。
可见手模型本身仍只是显示对象，碰撞代理由实验开关管理。

深度仍需手动调整，尚未实现摄像机到工作空间标定；手掌/指段碰撞、可靠的三维接触判定、
体积变化与真人手感比较仍待后续验证。原生软体塑性不保证黏土体积守恒。

仿真手的视觉重叠不等于真实接触；当前不把它当作 contact 或深度模型的验收证据。

## 自动验证

```bash
.venv/bin/python -m pytest -q
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_hand_preview_gui.py -- --quit
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_hand_preview_gui.py -- --realistic --quit
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_hand_preview_gui.py -- --smooth --quit
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/render_smooth_hand.py
```

脚本在独立场景、端口 8768 中验证 42 关节投影、捏合姿态、网格复用、丢手/超时恢复、显示开关、
对象清理和原目标不变。JSON、源码 SHA-256、截图与 `.blend` 位于 `runs/hand_preview/`。
GUI `passed:true` 才表示通过；合成测试不替代真人手型、左右手交叉及遮挡验收。
写实模式另验证真实模型加载、内嵌贴图、模式切换及图像资源清理，证据位于 `runs/realistic_hand/`。
光滑模式的 GUI、方向线、模型切换与清理验证位于 `runs/smooth_hand/`；
`reference_pose.png` 对照参考图，`pose_study.png` 从左至右展示张手、捏合和握拳的合成骨架驱动结果。
