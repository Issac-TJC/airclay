# AirClay 实施方案

## 目标

普通单目摄像头驱动 Blender 双手分工建模。主手控制表面定位与拉伸，副手控制环绕视角，双手捏合控制笔刷范围。课程贡献是意图时序建模及误操作评估；关键点检测和网格形变不冒充原创深度学习模块。

## 模块和数据流

1. 外部 Python 用 OpenCV 读取镜像摄像头画面，MediaPipe Tasks 的 VIDEO 模式提取双手关键点。画面和显示使用同一镜像约定。
2. 根据左右手分类先验与上一时刻手腕位置分配稳定槽位，再进行指数平滑。左右手近距离交叉、严重遮挡仍可能出错，需要真人测试。
3. 因果重采样到 30 Hz，间隔超过 150 ms 的缺失输入设为空。训练与推理均不使用未来帧插值。
4. 规则、单帧 MLP 或 GRU 提出 idle/sculpt/orbit/resize 意图，共享同一个操作状态机。物理捏合阈值也用于重新张手解锁；已开始的操作不能被另一个模式接管。
5. UDP 发送完整状态到 127.0.0.1:8765。Blender 通过主线程 modal timer 接收，每次最多处理 64 个包，拒绝旧序号与过期状态。
6. 接收端在世界坐标中计算笔刷沿网格边的测地近似距离，将世界位移转换为网格局部位移。每帧从抓取快照重算；提交时进入有限撤销历史。

MediaPipe 的 world landmarks 以每只手自身为中心，不用于两手之间的全局深度比较。双手距离使用图像坐标。

## 接口

视频帧：`timestamp_ms`、`dominant`、`hands.Left/Right`。每只手包含 21×3 的 `image` 与 `world` 数组，以及 `valid`。不存在的手可省略。

UDP v1：`version/session/seq/timestamp_ms/sent_ms/operation_id/mode/paused/outcome/dominant/hands`。每只手只传 `valid` 与归一化 `pointer`。`outcome` 为 null、commit 或 cancel，在空闲状态持续发送，避免丢失单个结束事件。

同一会话序号严格增加；新会话先回滚旧操作，看到 idle 后才能开始。不同操作编号切换但没有收到旧结束状态时保守回滚旧操作。超过 300 ms 无新消息也回滚。Blender 面板通过回包通知追踪端惯用手变化；追踪端重置识别与操作状态，开启新会话。

## 形变与交互

默认对象为 10,242 顶点的单位 icosphere；不自动修改用户已有对象。面板允许选择其他网格，但首版验收以演示球为准。始终要求 Object Mode。

笔刷点由屏幕射线命中得到；以命中面的顶点为 Dijkstra 种子，沿网格边扩展到半径 R。权重为 `1 - 3(d/R)^2 + 2(d/R)^3`，R 以外为零。断开的表面不受影响。

拉伸固定起始视角、半径与抓取平面。世界位移上限 0.5，半径范围 0.08–0.60。旋转沿模型中心，双手开合按初始距离比例缩放半径。默认保留 30 次操作，Ctrl/Cmd+Z 由接收器处理项目内撤销，不与 Blender 的编辑模式撤销混用。

## 默认模型

主手在前、副手在后的 140 维特征：每手局部关键点 63 维、手腕位置 2 维、速度 2 维、捏合距离 1 维、有效 mask 1 维，加两手距离及速度 2 维。左手局部 x 反射，保留手腕的实际画面位置。

GRU：24×140 输入，两层 128 hidden，dropout 0.2，输出 4 类。MLP 只使用当前帧的 135 维静态特征，避免混入显式历史速度。在线窗口未满时输出 idle。

AdamW lr=0.001，batch=64，最多 50 epoch，patience=8。训练窗口步长 3，验证步长 1。类别权重只从训练集估计。使用验证集 Macro-F1 保存最优权重；checkpoint 包含特征版本、类别顺序和训练配置，加载时核对。

## 实施与交付边界

A：模拟数据驱动真实 Blender 操作。B：摄像头与规则交互。C：采集、标注、训练、评估和模型接入。D：真人采集、正式实验、真实动作效果验证由团队参与完成。E：运行文档、插件 ZIP、验证记录。

没有真人数据时，不声称 GRU 优于规则，不把合成样例准确率写入课程结论。性能目标为至少 20 Hz 和中位响应低于 250 ms；组合判定约占 200 ms，因此需要按测量结果讨论识别准确率与延迟取舍。

## 参考资源

- [MediaPipe Hand Landmarker Python](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python)
- [MediaPipe Hands 论文](https://arxiv.org/abs/2006.10214)
- [Blender Python API](https://docs.blender.org/api/current/)
- [Blender Python 线程限制](https://docs.blender.org/api/5.0/info_gotchas_threading.html)
- [PyTorch GRU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html)

使用官方发布的库与模型；没有复制第三方手势插件代码。
