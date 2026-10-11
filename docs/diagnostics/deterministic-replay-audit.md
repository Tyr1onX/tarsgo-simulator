# 确定性整场比赛复现与 2027 迁移前基础设施审计

基线：`main` @ `eca789d404e5438510ca91aef556d76a8c690cc5`（2026-10-11）。
本轮只处理赛季无关能力，不新增 2027 机器人或场地机制。PR #101 未合并，且不纳入本轮变更。

## 核查结论

| 项目 | 基线现状 | 本轮 |
| --- | --- | --- |
| 可重放的随机种子 | RMUC AI 有常量 `_RMUC_AI_SEED=2026`；RMUC 能量机关和前哨站使用带 `generation` 的独立种子，`Match.reset()` 会改变同场景初始随机状态 | `Match(..., seed=N)` 可显式控制这两处随机源；指定种子时重置可复现，未指定则维持原行为 |
| 状态及事件 | `Match` 保持单一比赛状态；`current_events`、`zone_events`、`rfid_read_events` 是已有每 tick 事实；`battle_report`、`ruleset.display_state` 和投射物诊断可读取 | 复用现有事实与状态计算 checkpoint SHA-256，不建立第二套事件总线或比赛状态 |
| 无界面完整比赛 | `Match.from_scenario` / `update(dt)` 与规则胜负判断不依赖 Pygame；原有 CI 对 3 种规则各做 1 tick smoke，单元测试已有部分长局 | 提供命令行完整比赛录制 / 验证并覆盖 Training、RMUL、RMUC |
| 赛季硬编码 | `Match.uses_physical_projectiles` 和 RMUC 观战 AI 使用精确规则 ID；`Match.reset` 按 `type == "drone"` 设置 `aerial`，RMUC AI 显式枚举五种角色；RMUC RuleSet 约束固定 2026 阵容 | 保留本轮无关逻辑，标记新规则发布后逐项核对是否需要抽离，不为猜测的机制提前抽象 |

现有 `RuleSet` 注册、场地 YAML、机器人参数来源、单一 Match 状态、事件、统计、AI 路径诊断均无需重复实现。

## 使用方式

先在仓库根目录安装 `requirements-dev.txt`。无需启动桌面窗口。

```bash
python -m tarsgo_simulator.core.replay \
  --record /tmp/rmuc-trace.json \
  --scenario configs/scenarios/rmuc-2026-region-rules-lab.yaml \
  --seed 42 --spectator-ai
python -m tarsgo_simulator.core.replay --verify /tmp/rmuc-trace.json
```

可为 Training/RMUL 指定其场景文件并省略 `--spectator-ai`。传入 `--inputs moves.json` 可以按 tick 回放用户移动指令，文件示例：

```json
[{"tick": 0, "robot_ids": ["tarsgo-infantry-1"], "goal": [230, 120]}]
```

输入通过已有 `Match.order_group_move` 执行，拒绝的命令会报错。记录包含种子、时间步长、场景路径、输入、场景文件摘要和每 tick SHA-256；验证会检测第一个不同的 checkpoint。模拟持续至规则判断结束，超出 `max_ticks` 会失败，不会把中途截断算作完整比赛。

## 验证边界

- 本轮是**确定性复跑检查**，不是可在任意 tick 恢复内部对象的存档，也不是桌面用户所有交互的自动录制器。当前记录的外部输入仅覆盖移动指令；其他规则交互以后在真实需求确认后再扩展。
- 状态指纹覆盖：机器人、建筑、飞行弹丸、命中结果、当前规则/区域/RFID 事件、规则展示状态、战斗报告及投射物统计。内部 AI 搜索队列并未直接序列化；其效果由后续可见状态差异检测。
- 跨操作系统 CI 验证行为回归，但**不保证** Windows 与 macOS 之间浮点运算生成完全相同的 SHA-256。
- trace 文件依赖原场景路径与版本；重放相同配置和相同代码，才能作精确比较。

## 等待 2026-10-15 新规则发布后再决定

1. 2027 机器人新类型、重装、无人机、机库、地图/高度与区域的实际语义。
2. 按正式规则重新审视固定阵容、AI 对角色和规则 ID 的耦合，确认哪些逻辑应留在 RuleSet 内。
3. 新赛季独立规则包、官方条文对应的差距矩阵与跨赛季回归，不覆盖旧规则实现。
