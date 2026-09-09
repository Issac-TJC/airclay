# 验证记录

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
