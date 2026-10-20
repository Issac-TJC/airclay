# UDP v2：M1 hover2d 预览

另有完整骨架的 `hand_preview` profile，见 [HAND_PREVIEW.md](HAND_PREVIEW.md)。它同样不提供
全局深度或操作，不改变本页定义的 `hover2d` schema；切换 profile 也必须创建新 session。

`configs/default.json` 默认 `interaction_version: 1`，保持现有操作。
`configs/hover.json` 显式设置为 `2`；发送端创建新 session，接收端按版本和 profile 分发。
本文件仅定义 M1 的二维预览。后续深度/意图协议必须使用新的显式 profile 或版本，
不能让当前接收端将其误读为可操作的状态。

## 消息接口

每条消息包含且仅包含：

| 字段 | M1 约定 |
|---|---|
| `version` / `profile` | 整数 `2` / 字符串 `hover2d` |
| `session` / `seq` | 长度不超过 100 的 session 字符串 / 非负整数递增序号 |
| `timestamp_ms` / `sent_ms` | 本机 monotonic 毫秒，必须为有限数值 |
| `dominant` | `Left` 或 `Right`，只表示控制角色，不改变手身份或颜色 |
| `coordinate_space` | `mirrored_image_normalized` 或 `camera_image_normalized` |
| `depth_available` | 固定 `false` |
| `hands` | 必须包含 `Left`、`Right` 两个槽位 |

每只手包含 `valid: bool`、`fingertips: list`；列表最多五项，顺序任意：

```json
{
  "finger_id": "index",
  "xy": [0.45, 0.52],
  "valid": true,
  "xyz": null,
  "depth_confidence": null
}
```

固定映射为 `thumb=4, index=8, middle=12, ring=16, pinky=20`，绘制符号为 `T/I/M/R/P`。
每只手不允许重复或未知 ID。有效指尖必须属于有效手，`xy` 为 `[0,1]` 内两个有限数值。
无效指尖允许 `xy: null`；所有指尖的 `xyz` 和 `depth_confidence` 必须为空。
MediaPipe 的 handedness score 不是关节追踪置信度，不写入深度或逐关节置信度。

发送器固定输出十个槽位，越界/非有限/缺失指尖转为 `valid:false, xy:null`，不钳制到画面边缘。
接收器也接受省略的指尖 ID；每帧都是完整快照，省略即隐藏，不继承上一帧。
接收到非法坐标、重复 ID、未知版本/profile 或操作字段时丢弃整包。

## 坐标、显示与安全边界

- 新相机帧保留原始方向，标记 `mirrored=false`，使用 `camera_image_normalized`。
  预览与传输共用关键点方向，不反射 x。旧帧缺少标记时保留 `mirrored_image_normalized`。
  已安装的旧 Blender 插件需要重新打包安装以接受新坐标空间值。
- 归一化图像原点在左上，x 向右、y 向下。Blender WINDOW 区域像素为
  `(x * region.width, (1-y) * region.height)`，不使用整个窗口尺寸或 CSS 像素。
- Left/Right 指解剖学左右手。左蓝、右橙；惯用手变更不交换颜色或指尖身份。
- Blender 对目标网格的第一射线命中做正面检查；未命中或首面背向时隐藏，不搜索更后面的面。
- 每个光标独立保存 hover 的对象局部点和 face ID，视图变化时重新求交；这些点不构成 contact anchor。
- 虚线圈按物体包围球尺度和距离投影，并设置可读性上下限，与 v1 笔刷半径无关。
- `Show all fingertips` 关闭时只绘制两手食指；`Show hover` 关闭时不绘制候选点。
- 预览既不驱动意图状态机，也不调用操作开始、形变或提交路径。切换自 v1 会按既有 session
  规则回滚尚未提交的 v1 操作。预览不生成撤销历史。

## 传输与兼容

仅使用 `127.0.0.1`。JSON 使用紧凑编码，发送指尖坐标保留六位小数；单包上限 4096 字节，
接收器按上限加一读取并拒绝超限包。该上限针对本机回环，不是远程网络 MTU 保证。
M1 十指包约 1.3 KB；有最大 session 长度和坐标精度的包体测试。

接收器拒绝重复/乱序序号、退休 session、超过 300 ms 的发送时间、未来时间和非有限时间。
同一 session 禁止切换版本。300 ms 无新有效包后清空光标；恢复后只显示新完整快照中的有效指尖。
预览没有需要重新激活的操作。回包继续仅发送惯用手设置。

## 验证

```bash
.venv/bin/python -m pytest -q
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_hover_gui.py -- --quit
```

GUI 测试在独立场景和端口 8767 运行，结果、源文件 SHA-256、截图和 `.blend` 保存在 `runs/m1/`。
测试验证十指投影、第一可见面、丢指/边缘/恢复、身份、显示开关、包拒绝、超时和预览无修改。
真人逐指与双手交叉验收必须单独记录，不能由合成测试替代。
