# 原生碰撞塑性实验

使用 Blender 原生 Collision 和 Soft Body 的 Plasticity，让指尖推压物体并在松手后保留形状。
开关 **默认关闭**；普通手型预览保持原来的行为。重新加载 `.blend` 后也会关闭，需主动重新开启。

## 真人试用

1. 保存当前工作，重启 Blender 加载新版插件。项目演示可运行 `bash scripts/start_blender.sh`，
   该脚本创建新的演示场景，不会加载你当前的文件。
2. 保持现有追踪命令：`.venv/bin/airclay --config configs/hands.json track --backend rules`。
3. 在 AirClay 面板确认目标是球体，手型跟随正常，再开启 `Plastic collision (experimental)`。
4. 先把手指放在球体轮廓外，再缓慢向内捏压。状态行显示已参与碰撞的指尖数；
   `Move unarmed fingers outside clay` 表示有手指需要先离开物体再进入。
5. 若有视觉重叠却没有接触，调整 `Collision plane depth`：0 为物体中心平面，
   正值朝向观察者、负值远离观察者。`Finger collision size` 可放大接触范围，默认 1.5。
   调整视图、深度、前后翻转或碰撞大小后，要重新把手指移到物体外。
6. 松手并移开，形状会保留。关闭开关或停止接收器会结束本次实验并保留结果；
   AirClay 面板的 Undo/Redo 把整次实验作为一个操作。`Cancel plastic experiment` 恢复开启前形状。

开启时，指尖实际碰撞即会推压，`PINCH` 仍是姿态反馈，不是接触开关。隐藏手型会暂停碰撞。
丢手/断流暂停并保留当前形状；恢复后先把手指移出物体，避免重新识别时突然穿入。
保存文件会结束实验并保存当前形状，移除临时求解器；加载时不会自动继续模拟。

## 实现范围

- 十个指尖分别使用原生 Collision 球；本轮不含手掌和指段碰撞。
- 目标需为 Object Mode 下无活动修改器、无形态键、网格数据独占的表面网格。
  默认演示球符合条件。不支持实验中直接修改目标拓扑或对象变换。
- 独立临时场景中的约 642 顶点代理运行 Soft Body（Plasticity=100、无重力），
  用三角形重心权重把代理位移传给原网格，保留原拓扑。演示球实际代理为 643 顶点。
- 用户场景的时间轴、对象变换保持不变。求解缓存上限为 300 帧，达到上限以当前形状继续；
  结束或取消会删除临时物理场景、对象和网格。
- 这是原生软体的塑性近似，不保证黏土体积守恒，也没有重拓扑。
  显示根深度仍为手动值；摄像机前后移动尚未标定成真实接触距离。
- 更新目标为最高 30 Hz，实际速度取决于碰撞数量和求解开销。异常大位移会停止实验并保留最后稳定形状。

## 自动验证

```bash
.venv/bin/python -m pytest -q
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/test_plasticity.py
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_plasticity_gui.py -- --quit
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/test_plasticity_load.py
```

GUI 测试使用独立端口 8769 和合成骨架，不访问摄像头。以 `runs/plasticity/` 内各 JSON 的
`passed: true` 为准；退出码不代替 GUI 断言。数值测试覆盖 330 帧捏压、释放、稳定、缓存重建，
GUI 测试覆盖十指输入、默认关闭、关闭保留、取消、撤销/重做、断流和保存清理。
加载测试还覆盖残留的临时物理场景清理及强制关闭。真人效果与长时间稳定性仍需单独记录。
