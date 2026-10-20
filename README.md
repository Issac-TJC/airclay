# AirClay：双手手势捏泥

普通摄像头 → MediaPipe 关键点 → 规则 / MLP / GRU → 本机通信 → Blender 局部拉伸。

惯用手编辑，另一只手旋转，双手调节笔刷。默认右手编辑。预训练关键点检测器不参与训练；课程训练部分是你们自己的意图识别器。

## 快速运行

本机已配置项目 `.venv`。分别在两个终端运行：

```bash
cd /Users/issactjc/dev/18794
bash scripts/start_blender.sh
```

```bash
cd /Users/issactjc/dev/18794
.venv/bin/airclay track --backend rules
```

Blender 会打开独立的新场景并自动创建球体、启动接收器。第一次可能显示 Blender 启动画面，点击画面外关闭即可。侧栏 `N → AirClay` 可切换惯用手、修改半径和撤销。相机窗口按 **Q** 停止；Blender 按 **Esc** 停止接收。

macOS 如果请求摄像头权限，请允许你用于启动程序的终端应用访问摄像头。Codex 沙箱可能限制本机 UDP、Metal 或摄像头访问；在正常 Terminal 中运行以上命令。不要在 Blender 自带 Python 中安装机器学习依赖。

### 没有摄像头也能体验

保持 Blender 接收器运行，将第二条命令换成：

```bash
.venv/bin/airclay simulate
```

它会发送约 13 秒模拟手势：两次局部拉伸、旋转、调笔刷。这验证交互和通信，**不验证真人识别**。每次运行前可点击 `Create clay sphere` 创建新的球；不会删除已有模型。

### M1：十指二维 hover 预览（显式启用）

先按上文启动 Blender 接收器，再任选一种输入：

```bash
# 无摄像头：十指移动、丢指、越界、丢手和恢复的固定序列
.venv/bin/airclay --config configs/hover.json simulate

# 真人摄像头：与 v1 共用原始画面和左右手身份
.venv/bin/airclay --config configs/hover.json track --backend rules
```

v2 当前仅提供 `hover2d` 预览，不触发雕刻、抓取、旋转或缩放。左手蓝色、右手橙色，
`T/I/M/R/P` 分别表示拇指、食指、中指、无名指、小指；颜色不随惯用手设置交换。
半透明虚线圈表示目标网格第一可见表面的候选点，不代表接触。缺失、越界、未命中或
断流超过 300 ms 时隐藏。深度明确不可用，不使用每手局部 world landmarks 冒充全局深度。

AirClay 面板的 `Show all fingertips` 关闭时只显示两手食指；`Show hover` 可隐藏全部候选点。
不指定配置仍运行原有 v1 操作。切换版本需要重启追踪端以创建新 session；接收端自动识别
v1 或 v2 `hover2d`，拒绝未知版本和同一 session 内的版本切换。

预览也支持 `--config configs/hover.json replay <recording>`，从 v1 录制的 21 个图像关键点提取
指尖，不修改旧录制或标签。v2 不运行 MLP/GRU。协议约定见 [docs/PROTOCOL_V2.md](docs/PROTOCOL_V2.md)。

### 三维手型预览：观察捏合姿态

重启 Blender 加载新插件后，完整的 21 关节骨架默认驱动参考风格的 **Smooth blue hand**：
浅蓝光滑表面、连续掌部、修整后的腕口及可关闭的黄色指尖方向线。
面板 `Hand model` 还可选择 `Realistic skin` 写实皮肤或 `Simple joints` 简化手：

```bash
.venv/bin/airclay --config configs/hands.json track --backend rules
# 或先运行无摄像头的张手/捏合/丢手演示：
.venv/bin/airclay --config configs/hands.json simulate
```

光标与图例按左蓝右橙区分，底部显示每只手的 `OPEN / PINCH / LOST`。`PINCH` 是姿态反馈，
不触发雕刻。`Show tracked hands` 控制手模型显示；`Hand display depth` 调整显示位置，
不是相机标定或真实深度。模型使用图像位置和每手局部三维结构，丢手/断流时隐藏。
`Flip hand front/back` 默认开启，适配当前反转摄像头；只翻转相对腕部的前后方向，不交换左右手或屏幕位置。
写实模型为 [Elena FF 的 Rigged hand](https://sketchfab.com/3d-models/rigged-hand-eae97cc2a742413cb5338ab942b12c1e)，
CC BY-SA 4.0，光滑手为其衍生模型，署名与资源随插件打包。写实模式实体视图保持蓝/橙对象颜色；切换到材质预览可显示皮肤贴图，
光标和图例继续区分左右手。无需修改追踪配置，也无需另行下载模型。
新增默认关闭的 `Plastic collision (experimental)`：开启后，十个指尖通过 Blender 原生
Collision + Soft Body Plasticity 推压物体，关闭后保留形状。先把手指放在物体外，再缓慢向内捏；
深度暂由 `Collision plane depth` 手动调整。面板提供取消、撤销/重做，保存时自动结束实验。
使用步骤与限制见 [docs/PLASTICITY.md](docs/PLASTICITY.md)；手型说明见 [docs/HAND_PREVIEW.md](docs/HAND_PREVIEW.md)。

## 操作方法（默认 v1）

| 操作 | 手势 |
|---|---|
| 定位 | 右手食指移动，观察球面笔刷圈 |
| 拉伸 | 右手拇指和食指捏合，等待约 0.2 秒，再移动；松开提交 |
| 旋转视角 | 左手单独捏合后移动 |
| 改变笔刷范围 | 两只手在约 0.2 秒内捏合，然后开合；松开结束 |
| 撤销 / 重做 | AirClay 面板按钮，或接收器运行时 Ctrl/Cmd+Z、Shift+Ctrl/Cmd+Z |
| 保存 | Blender 的 File → Save As，保存 `.blend` |

操作期间不会切换模式。**每次操作结束后先张开手，再开始下一次。** 丢失操作所需的手时立即暂停；超过 0.3 秒则回滚未完成操作。摄像头断流也会触发回滚。初次连接先张开双手。

拉伸发生在平行于屏幕的平面；想从另一方向塑形，先旋转视角再拉。默认球体约 10,000 顶点，半径 1；笔刷 0.08–0.60，单次最大位移 0.5。多次大幅拉伸可能造成网格拉长；首版没有重拓扑、切割或真实泥土物理。

## 数据 → 训练 → 评估

### 1. 采集

英文录制说明见 [data/README.md](data/README.md)。每次启动录制都会先显示说明窗口；阅读后必须点击 Continue，摄像头才会打开。窗口省略命令行启动步骤。

```bash
.venv/bin/airclay record --subject p01 --session s01 --guided --interact
```

默认引导流程共 20 轮（`--repetitions`）：每轮先准备 5 秒，然后按 sculpt → orbit → resize 各做一次，每个动作 4 秒操作 + 2 秒松手。画面同时显示当前动作、下一个动作及距离下一个动作开始的秒数，倒计时包括松手时间。最后一个动作显示距离暂停的秒数。

每轮三个动作结束后自动暂停，预览继续，但暂停期间不保存数据。在摄像头预览窗口中按键：

| 按键 | 功能 |
|---|---|
| R | 重录刚结束的整轮；轮数不增加，重新准备 5 秒 |
| N / Space / Enter | 接受这一轮，准备下一轮 |
| Q / Esc | 放弃并丢弃本次整个录制，包括已接受的轮次；下次从第一轮重录 |

最后一轮按 N 后，准备 5 秒再录 2 分钟自然动作，之后自动保存并结束。需要更长准备时间可加 `--prepare-seconds 8`。不含暂停、重录，默认流程约 9 分 45 秒。也可省略 `--guided`、用 `--seconds 60` 自由采集；自由采集可按 S 提前保存，Q 仍是放弃。默认只存关键点；`--video` 额外保存本地参考视频。

完成并保存的 session 会在 `takes/` 保留重录前的尝试，但从根目录的正式关键点、视频和粗标签中排除。`recording_takes.json` 记录每次接受或重录。正式文件去掉暂停时间，保留每轮内的实际帧间隔，训练窗口不会跨轮拼接。Q 不保存本次录制，也不是暂停或续录功能；以前已完成的 session 不受影响。所有标签仍需人工核验。

`--interact` 用同一个摄像头流同时驱动 Blender 规则模式，便于采集带实际反馈的动作；省略时仅录制。不需要另外运行 `track`，不要让两个进程争用摄像头。录制期间保持惯用手配置不变。
引导录制暂停时也暂停发送交互；R 只重录数据，不撤销 Blender 中已经提交的编辑。

每人使用唯一 subject，两次采集使用不同 session。目录已存在时拒绝覆盖。

识别、视频、关键点和预览统一使用摄像头原始画面，程序不镜像、不交换 Left/Right。
左右手按身体定义，不按画面位置定义；`dominant` 只选择操作角色。旧录制保持原样。

### 2. 人工检查标签

```bash
.venv/bin/airclay annotate data/p01_s01
```

标注窗口显示已录制的关键点骨架。提示时间只是粗标签，必须校正实际意图边界。

| 按键 | 功能 |
|---|---|
| Space | 播放 / 暂停 |
| A / D | 前 / 后一帧 |
| J / L | 前 / 后 30 帧 |
| I / O | 选择区间开始 / 结束（结束为当前帧之后） |
| 0 / 1 / 2 / 3 | 将区间标为 idle / sculpt / orbit / resize |
| V | 切换人工验证标记 |
| S | 保存，保留上一次标签备份 |
| Q | 退出；未保存修改会丢弃 |

### 3. 按受试者划分

```bash
.venv/bin/airclay split data --output data/split.json
```

正式建议 10 人，按 6/2/2 划分 train/val/test；划分后所有模型使用同一份文件。至少 5 人才能默认划分。只有用于流程测试时使用 `--allow-small`，最低 3 人；这不等同于有效的跨用户实验。

### 4. 训练

```bash
.venv/bin/airclay train --model gru --split data/split.json --output runs/gru_seed42
.venv/bin/airclay train --model mlp --split data/split.json --output runs/mlp_seed42
```

默认 CPU，GRU 为 2 层、128 hidden、24 帧因果窗口；最多 50 epoch，验证集 Macro-F1 早停。可指定 `--device mps`、`--epochs`、`--seed`。正式实验再用 43、44 两个种子重复。

所有训练标签必须人工验证，四个类别必须在训练集出现。没有真实采集时只提供合成冒烟权重，不能用于性能报告。

### 5. 评估与接入

```bash
.venv/bin/airclay evaluate --backend rules --split data/split.json --output runs/eval_rules
.venv/bin/airclay evaluate --backend gru --checkpoint runs/gru_seed42/best.pt --split data/split.json --output runs/eval_gru
.venv/bin/airclay evaluate --backend mlp --checkpoint runs/mlp_seed42/best.pt --split data/split.json --output runs/eval_mlp
.venv/bin/airclay track --backend gru --checkpoint runs/gru_seed42/best.pt
```

输出包含分类报告、混淆矩阵 PNG、连续操作事件统计。默认评估 test；调参仅使用 `--partition val`。指定模型但未提供正确权重会报错，不会悄悄切换规则。

按原时间戳回放录制数据：

```bash
.venv/bin/airclay replay data/p01_s01 --backend rules
```

## 环境与打包

```bash
bash scripts/bootstrap.sh
.venv/bin/airclay doctor
.venv/bin/python scripts/package_addon.py
```

本机 Python 默认 `/Users/issactjc/dev/tools/miniconda3/bin/python3.12`，可用 `AIRCLAY_PYTHON` 覆盖；Blender 路径可用 `AIRCLAY_BLENDER` 覆盖。目标平台是 macOS Apple Silicon + Blender 5.2，其他平台尚未验证。

依赖精确锁定在 `requirements.lock`。MediaPipe 固定 0.10.21、NumPy 1.26.4、OpenCV 4.11.0.86；本机测试中 MediaPipe 1.0.1 原生崩溃，因此没有使用最新版本。官方模型来源和 SHA-256 在 `assets/model_manifest.json`。

该 MediaPipe 官方 universal2 wheel 的内部 WHEEL 标签误写为 x86_64，`pip check` 会报告平台标签警告；实际二进制同时包含 arm64/x86_64，已通过本机原生模型推理测试。未篡改第三方包元数据以隐藏警告。

`dist/airclay_blender.zip` 可通过 Blender 的 Install from Disk 安装。默认启动脚本仅临时加载插件，不修改用户偏好设置。安装版提供同样的接收器，但相机和训练程序仍在外部运行。

全局配置参数放在子命令前：`airclay --config configs/my_config.json track`。该文件只需包含要覆盖的值。接收端的高级几何参数默认读取项目配置；发布 ZIP 使用内置默认值。

## 测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/make_smoke_data.py
.venv/bin/airclay train --model gru --split runs/smoke_split.json --output runs/smoke_gru --epochs 2 --allow-synthetic
.venv/bin/airclay evaluate --backend gru --checkpoint runs/smoke_gru/best.pt --split runs/smoke_split.json --output runs/smoke_gru/evaluation --allow-synthetic
```

真实 Blender 网格测试与完整 GUI 测试分别是 `scripts/test_blender.py` 和 `scripts/test_gui.py`，通过 Blender `--python` 启动。GUI 测试使用端口 8766，在独立场景中测试模拟操作、撤销和断流回滚。

详细设计见 [docs/PLAN.md](docs/PLAN.md)，分组件实现与验收清单见
[docs/IMPLEMENTATION_CHECKLIST.md](docs/IMPLEMENTATION_CHECKLIST.md)，数据和实验约定见
[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md)，当前验证结果见
[docs/VALIDATION.md](docs/VALIDATION.md)。
