# 验证记录

## 2026-10-20：Caleb 因果 TCN 阶段一

- 已实现固定因果 TCN：`140→64` 投影、三个 residual blocks、每块两个 kernel-3
  causal convolution，dilation 为 `1/2/4`，ReLU、dropout 0.2、四分类逐帧输出；
  `forward()` 使用最后一步。所有卷积只做左侧 padding，不使用跨时间 normalization。
- 默认模型共有 **83,396** 个可训练参数。自动测试覆盖 `[B,4]` 与 `[B,T,4]` 输出、
  future-input invariance、checkpoint round trip、类型/schema 拒绝、batch/online 特征一致性，
  以及第 23/24 帧 warm-up 边界。
- 完整 Python 回归为 **60 项通过**（`.venv/bin/python -m pytest -q`），原 MLP、GRU、协议和
  Blender 相关测试未回归。
- `scripts/make_smoke_data.py` 生成的合成 split 完成两轮 TCN 训练，validation Macro-F1
  为 0.919；test Macro-F1 为 0.922，状态机事件 false operations 与 misses 均为 0。
  checkpoint 随后完成 evaluate 和无预览 replay，验证 feature→TCN→state machine→UDP 链路。
- learned-model evaluation JSON 已记录参数量和公平的纯模型 CPU timing：batch 1、window 24、
  warm-up 50 次、测量 200 次；本次 median 0.300 ms、p95 0.304 ms。该计时不含特征、状态机、
  UDP、摄像头或显示延迟。
- 所有上述数值均标记 `synthetic_smoke_only=true`，不会进入正式中期表格。
  `scripts/run_tcn_midterm.py` 会在训练前拒绝 synthetic/未人工验证数据、subject leakage、
  不完整训练类别，以及非统一 EMA 0.45 的 preprocessing manifest；正式 split 与 EMA 数据
  尚未到位，因此三种子 human-data 结果保持 unmeasured。

## 2026-09-10：参考风格的光滑手型与蒙皮优化

目标为用户参考图右侧的浅蓝、圆润、无皮肤纹理的手部显示。默认模型改为 `Smooth blue hand`，
原写实皮肤与简化关节模型保留，可在面板切换。该扩展不增加 M0–M6 的验收要求。

- 焊接原 UV 接缝后每手 14,499 顶点、28,994 三角面；平滑表面、加长并收窄腕口，
  统一掌部权重并平滑八通道蒙皮，减少掌部折面。衍生模型和处理记录为插件内
  `assets/hand_smooth.npz` 与 `assets/smooth_manifest.json`，继续遵守 CC BY-SA 4.0。
- 骨骼方向改为从绑定姿态连续旋转；70°–110° 弯指扫描验证无 90° 朝向翻转。
  几何测试验证焊接模型为闭合流形、腕部加长、腕区根权重、绑定姿态还原与镜像。
- Python 共 **57 项通过**，保留原有 55 项；`runs/smooth_hand/python_tests.txt`。
- 三种手型的 Blender GUI + UDP 测试均通过。光滑模式额外验证两手统一蓝色、十个黄色方向线、
  方向线开关及丢手隐藏；模式切换、前后翻转、捏合、断流、资产缺失回退及资源清理通过。
  报告分别为 `runs/smooth_hand/gui_test.json`、`runs/realistic_hand/gui_test.json`、`runs/hand_preview/gui_test.json`。
- 光滑模式两手发送至网格更新中位约 20.6 ms，关节回投影最大误差约 0.017 像素。
  该耗时不含摄像头、推理与最终呈现，投影误差也不代表皮肤拟合精度。
- 实际 Cycles 渲染已对照参考图检查：`runs/smooth_hand/reference_pose.png` 显示浅蓝手型、
  连续腕部和黄色指尖方向线；`pose_study.png` 从左至右为张手、捏合、握拳。
  两者均由当前蒙皮算法驱动，配套 `.blend` 与 `render_manifest.json` 保存可复验来源。
- 默认光滑手的塑性 GUI 回归通过，关闭保留、取消、撤销/重做、断流暂停和保存清理正常；
  `runs/plasticity/gui_test.json`。方向线仅显示，不参与碰撞；物理开关仍默认关闭。
- 最终插件 ZIP 在独立临时目录解压后可加载三种手型，代码和资源一致、清理通过；
  `runs/smooth_hand/package_test.json`。

本轮采用合成骨架验证，未访问真人摄像头；个人手形差异、极端遮挡和皮肤自交仍需真人试用观察。

## 2026-09-10：写实蒙皮手模型

- 接入 Elena FF 的 `Rigged hand`，CC BY-SA 4.0。原 GLB、署名、来源及 SHA-256 已保存；
  插件附带提取的网格、UV、蒙皮权重、肤色与粗糙度贴图。资源细节见 [`HAND_PREVIEW.md`](HAND_PREVIEW.md)。
- Python 共 55 项通过（保留原有 51 项）：新增绑定姿态还原、旋转/缩放/平移、完整皮肤左右镜像与前后反转、
  局部手指形变、退化输入有限性及资产完整性验证；`runs/realistic_hand/python_tests.txt`。
- Blender 5.2.1 LTS GUI + UDP 合成测试通过：默认写实模型加载、每手 16,330 顶点、
  42 关节投影、捏合形变、前后翻转、网格复用、显示切换、丢手恢复、原目标不变、
  图像/材质/对象资源清理。报告及源码/资产哈希见 `runs/realistic_hand/gui_test.json`。
- 新模型与简化模型切换后追踪点完全一致；贴图打包到 `.blend`，翻转后的 UV 仍与顶点对应，
  模型文件缺失时自动回退至简化手并提示，恢复选择后正常加载。
- 两手 localhost 发送到皮肤更新的中位耗时约 14 ms（15 帧样本），不包含摄像头、推理和最终屏幕呈现。
  骨架回投影最大误差约 0.017 像素；这是关节误差，不代表皮肤表面匹配真实手的精度。
- 实际 Blender 截图已检查：`runs/realistic_hand/hands_solid.png` 为身份色实体视图，
  `hands.png` 为皮肤贴图视图；配套 `hands.blend` 含内嵌贴图。
- 使用默认写实手的原生塑性 GUI 回归通过：关闭保留、取消、撤销/重做、断流暂停和保存清理均正常；
  `runs/plasticity/gui_test.json`。碰撞仍使用相同十指代理，开关仍默认关闭。
- 备用简化手完整 GUI 回归通过；`runs/hand_preview/gui_test.json`。
- ZIP 解压至独立临时目录后，代码、模型、贴图及许可完整且可加载，默认写实、物理默认关闭；
  `runs/realistic_hand/package_test.json`。

本轮未访问摄像头；截图使用合成捏合姿态。写实皮肤在真人握拳、拇指遮挡和交叉双手下的拟合与性能仍待试用。
本功能继续属于 checklist 第 13 节的可选扩展，不增加 M0–M6 的必需验收项。

## 2026-09-10：默认关闭的原生碰撞塑性实验

Blender 5.2.1 LTS，本轮使用合成输入，没有访问摄像头。使用说明见 [PLASTICITY.md](PLASTICITY.md)。

| 检查 | 结果 / 证据 |
|---|---|
| Python 回归 | 51 项通过；`runs/plasticity/python_tests.txt` |
| 原生软体与碰撞 | 643 顶点代理驱动原始 10,242 顶点球体，330 帧捏压、释放、稳定通过；`runs/plasticity/native_test.json` |
| 松手保留 | 半径 1 的球体释放后最大顶点位移约 0.437；宽度从 2 变为约 1.626，后续稳定帧与缓存重建后保持 |
| 缓存和资源 | 有界 300 帧缓存，测试内重建 2 次；结束后场景、对象和网格数量恢复，无目标修改器、无时间轴推进 |
| 真实 Blender GUI + UDP 骨架 | 十个原生指尖碰撞体、默认关闭、关闭保留、取消、整次撤销/重做、丢手暂停及保存结束通过；`runs/plasticity/gui_test.json` |
| 保存与加载 | 保存进行中的实验后保留形状并移除求解器；加载强制关闭实验并清理中断遗留场景；`runs/plasticity/load_test.json` |
| 手型回归 | 前后反转、42 关节投影、丢手恢复、原目标不变通过；`runs/hand_preview/gui_test.json` |
| 默认 v1 回归 | 四次操作、笔刷调整、撤销/重做、投影和断流回滚通过；`runs/plasticity/v1/gui_test.json` |
| 插件 ZIP | 独立导入、注册/注销、默认关闭、打包源码一致；`runs/plasticity/package_test.json` |

数值双指测试更新中位约 6.4 ms；GUI 十指测试约 30.7 ms，均为本机求解及网格更新耗时，
不是摄像头到屏幕的端到端延迟。GUI 合成轨迹最大保留位移约 0.168；测试中使用较大的碰撞半径。
原生数值及 GUI 报告保存对应源码 SHA-256。截图 `runs/plasticity/plastic_hands.png` 已视觉检查，
显示球体受压后的轮廓；配套场景为 `plastic_hands.blend` 和 `native_plasticity.blend`。

本轮仅十个指尖参与碰撞，深度为手动显示平面，未完成真实根深度或接触标定；
不勾选 M2/M3/M4 的验收项。真人捏泥手感、体积变化、遮挡误触发及长时间稳定性仍待测试。

## 2026-09-10：完整骨架驱动的三维手型预览

- Python 测试共 51 项通过：`runs/hand_preview/python_tests.txt`。
- Blender 三维手 GUI 测试通过：`runs/hand_preview/gui_test.json`，包含对应源码 SHA-256。
- 两手各 21 个关节回投影最大误差约 0.017 像素；每手 876 顶点；实际示例包约 1.75 KB。
- 前后反转适配：`Flip hand front/back` 默认开启；实际 Blender 测试证明腕部相对视向深度
  反号，腕部位置、二维投影、左右手对象身份和捏合反馈不变，`front_back_flip_passed: true`。
- 合成捏合时手网格与 `PINCH` 显示更新，张手/丢手/超时恢复通过；对象和网格复用，清理后
  Blender 对象、网格、材质数量恢复；原目标几何与对象变换保持不变。
- 同一进程内 localhost 发送到手网格更新的中位耗时约 3.2 ms（15 帧样本），不包含摄像头、
  MediaPipe 推理和屏幕显示，不代表真人端到端延迟。
- 可检查截图和场景：`runs/hand_preview/hands.png`、`runs/hand_preview/hands.blend`。截图已视觉检查。
- M1 hover 回归仍通过，见 `runs/m1/hover_gui.json`。
- 默认 v1 的四次操作、撤销/重做、投影和断流回滚通过，见 `runs/hand_preview/v1/gui_test.json`。
- 插件 ZIP 已重新打包，完整骨架协议与 `hand_display` 模块独立加载、注册通过；
  打包源码与当前文件一致。

该手型只是未标定显示深度的三维预览，不能作为深度/contact 或物理形变验证。用户选择的
后续目标为“像黏土，松手后保留形状”；此阶段尚无物理，后续实验见本页上方的新记录。
真人手型跟随、握拳遮挡与捏合手感仍待实际测试；本轮没有打开摄像头。

## 2026-09-10：M1 十指二维 hover

当前源码的独立验证结果：

| 检查 | 结果 / 证据 |
|---|---|
| Python 核心与 v2 测试 | 41 项通过，保留原有 13 项；`runs/m1/python_tests.txt` |
| Blender 无界面 v1 网格 | 10,242 顶点、127 个受影响顶点；形变、恢复和保存通过 |
| Blender v1 GUI + UDP 回归 | 4 次提交、撤销/重做、投影和断流回滚通过；`runs/m1/v1/gui_test.json` |
| 十指 M1 GUI + UDP | 第一可见表面、丢指/丢手/边缘/恢复、身份、显示开关、旧包/非法包拒绝和超时通过；`runs/m1/hover_gui.json` |
| 十指回投影误差 | 最大约 0.000492 像素，低于 2 像素目标 |
| 预览无操作 | 网格、对象变换、笔刷和视图保持不变，不产生操作或撤销历史 |
| v1 切换到预览 | 尚未提交的 v1 雕刻回滚，v2 不提交旧操作；`v1_to_preview_rollback_passed: true` |
| 视口验证 | 透视、正交、视图旋转及 Retina `pixel_size=2`；本次 WINDOW 区域为 2408×1399 |
| 可检查产物 | `runs/m1/hover_preview.png`、`runs/m1/hover_demo.blend`；截图已视觉检查十指颜色和符号 |
| 插件 ZIP | 已重新打包；在 Blender 中独立加载、注册和注销通过，打包源码与当前文件一致；`runs/m1/package_test.json` |

M1 GUI 报告保存相关源码 SHA-256，避免把其他版本的运行产物当作当前实现的证据。
测得十指示例包约 1.3 KB，上限为本机回环的 4096 字节。
本轮 Blender 沙箱内启动崩溃，改在沙箱外运行上述独立测试并通过；没有修改系统权限数据库。

这些结果均为自动/合成验证。**真人逐指、双手交叉遮挡、惯用手交换、十分钟稳定性和干净环境复现仍待验收。**
没有访问摄像头或声称已验证真人识别。

### 旧证据核对

旧 `runs/track_latency.json` 有 1853 帧、约 99.192 秒，包含 `object_grip` 和
`sculpt+object_grip`；对应 manifest 包含深度配置，与本轮开始时检出的 v1 源码不一致。
这些旧文件保留，但不能证明当前源码的真人演示或十分钟稳定性。未找到干净环境复现记录，
因此 checklist 中原来勾选的三项恢复为待验收。以下 2026-09-09 记录保留为历史记录，
不能据其当时的摄像头失败判断设备当前是否仍被权限阻止。

### M1 复验与真人验收

```bash
.venv/bin/python -m pytest -q
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/test_blender.py
AIRCLAY_TEST_OUTPUT_DIR="$PWD/runs/m1/v1" "$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_gui.py -- --quit
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_hover_gui.py -- --quit
```

GUI 脚本的 JSON `passed` 必须为 true；`--quit` 只负责自动退出，不能用进程退出码代替该结果。
v1 测试端口为 8766，M1 为 8767，均创建独立场景，不使用真人摄像头。

真人验收时启动正常接收器，再运行：

```bash
.venv/bin/airclay --config configs/hover.json track --backend rules --output runs/m1/manual_track.json
```

逐一展示十根手指、双手交叉/短时遮挡、一只手离开并返回、切换惯用手。
记录实际解剖学左右手是否与蓝/橙颜色一致，逐指符号是否正确，丢失是否隐藏及恢复是否串位。
保存测试者、时间、源码版本、配置、截图/视频及失败区间，完成后才勾选真人验收项。

## 历史记录：2026-09-09

验证日期：2026-09-09。平台：Apple Silicon（本机渲染器报告 Apple M4）、macOS 26.6.2、Python 3.12.11、Blender 5.2.1 LTS。

## 已通过

| 检查 | 结果 |
|---|---|
| 13 项 Python 自动测试 | 通过：组合判定、模式锁定、释放去抖、丢手回滚、包序号、因果重采样、特征一致、手身份匹配、标签编辑、受试者隔离、形变、权重加载、事件指标及联合录制时间戳隔离 |
| 真实 Blender 网格 | 10,242 顶点；测试抓取影响 127 个顶点；形变、恢复、再次应用及保存通过 |
| 完整 GUI + UDP | 提交 4 次操作：两次拉伸、一次旋转、一次调笔刷 |
| GUI 撤销 / 重做 | 半径恢复和重做通过 |
| 光标投影 | 表面射线命中点回投影误差小于 1 像素 |
| 断流 | 进行中的网格变化在超时后恢复到操作前快照 |
| 官方关键点模型 | MediaPipe 0.10.21 成功加载并完成空白图像原生推理，检测到 0 只手 |
| MLP / GRU 管线 | 合成数据各完成 2 epoch，保存并加载权重，生成评估 JSON 和混淆矩阵 |
| 无权重模型启动 | 明确报错，没有静默切换为规则 |
| 交付场景 | `runs/airclay_demo.blend` 已保存；`runs/airclay_demo.png` 为该模型的实际渲染 |

GUI 测试记录在 `runs/gui_test.json`。首次通过测试时最大顶点位移约 0.453，笔刷半径由 0.25 变为约 0.385。本机模拟消息的传输到应用中位数约 16.4 ms；这不包含摄像头、关键点识别和意图等待时间，不能称为完整手势响应延迟。

## 需要真人参与 / 尚未验证

后续代码核对发现并修复：联合录制原先会把实时帧的绝对时间戳就地改为录像相对时间，影响重采样对上一帧的使用。现在录制独立副本，并用不对齐 30 Hz 的模拟相机输入完成回归测试；不替代真人采集验收。

- 摄像头短时检查被 macOS 隐私权限拦截，`runs/camera_probe.json` 为 0 帧。未保存任何相机图像。
- 未完成真人抓取手感、跨手遮挡、左手惯用设置、跨用户准确率或十分钟相机稳定性测试。
- 没有真人训练数据，因此当前合成权重不能代表可用的手势识别模型；默认应使用规则模式。
- 未录制真人操作演示视频。已提供可执行模拟动作和真实模型渲染。

在 macOS 系统设置 → 隐私与安全性 → 摄像头，允许启动 AirClay 的 Terminal/Codex 应用后，重新运行 `airclay track --backend rules`。系统权限应由设备使用者确认；不要通过修改权限数据库绕过。

## 环境兼容性记录

- MediaPipe 1.0.1 在本机加载模型时发生原生 `graph_service` / Metal 服务崩溃；沙箱外也复现。最终固定到 0.10.21，并通过原生推理验证。
- MediaPipe 0.10.21 官方 wheel 文件名是 universal2，二进制经 `file` 检查同时包含 arm64 和 x86_64，但内部 WHEEL 标签是 `macosx_14_0_x86_64`。因此 `pip check` 会提示该包的平台标签不匹配；实际 arm64 导入和推理成功。保留上游原始元数据，并在此记录例外。
- Blender 在 Codex 沙箱内初始化 Metal 时崩溃；同一程序在沙箱外通过无界面及 GUI 检查。正常 Terminal 启动不使用该沙箱。
- 未验证 Windows、Linux、其他 Blender 版本或 Intel Mac。`requirements.lock` 针对当前平台生成。

## 可复验命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_model.py
"$AIRCLAY_BLENDER" --background --factory-startup --python scripts/test_blender.py
"$AIRCLAY_BLENDER" --factory-startup --python scripts/test_gui.py
```

`AIRCLAY_BLENDER` 应设为本机 Blender 可执行文件；本项目 `scripts/start_blender.sh` 中有已验证的默认路径。GUI 测试独立使用端口 8766；正式演示默认使用 8765。
