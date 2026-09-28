# RMUL 2026 3V3 与当前 Engine / rules lab 的差距

对照基准为仓库当前实现，以及 [RMUL 2026 规则摘要](rmul-2026-3v3.md)所标注的官方 V1.2.0 手册。`rmul-2026-3v3` 目前是部分、实验性规则集；rules lab 具有 Hero + Infantry + Sentry 的 3V3 阵容结构。地图已采用 V1.2.0 可确认的 12 m × 8 m 基本 footprint，并提供 supply/control/high-ground 的 top-down 语义区域；无法从本轮审计可靠读取的内部尺寸仍保留为明确 approximation。大部分战斗参数仍是实验配置。

## 已有通用能力

- `Match` 管理多机器人、队伍、地图、经过时间和结果生命周期；training-v0 当前是每队两台步兵的 2v2。
- Scenario 显式列出玩家直控机器人 ID；其余机器人使用同一套最近敌人寻路 AI。RMUL rules lab 直控 Hero 和 Infantry，Sentry 自动运行。
- 机器人可以寻路移动；地图有障碍、实体间动态阻挡和战斗视线判断。
- 支持多选、框选、队形移动和敌方 AI。
- 机器人有 HP、攻击距离、冷却和直接伤害；同一更新帧的攻击意图先收集再统一结算。
- YAML 已能配置场景、队伍和合成训练参数；目前不是裁判系统精度的仿真。

## 已落地的通用能力

- `Zone` 矩形和中心点区域查询；队伍 YAML 可配置区域，通用 loader 校验 ID、矩形和地图边界。具体占领、优先权、计分频率和失效延迟由 RuleSet 实现。
- 每帧 `robot_destroyed` 事实事件；Match 在统一死亡边缘产生一次，规则集可读取同帧的多个事件。
- RMUL 2026 实验规则集读取 YAML 中的 VP、控制区、比赛时长、复活、虚弱 / 无敌、补给区映射等规则参数；支持 VP / 控制区 / 战亡扣分 / 自动复活生命周期。

## 仍需新增的通用能力候选

- RMUL 的复活、弱化和无敌当前由该 RuleSet 的私有逐机器人状态维护；只有第二套规则集确实需要相同语义时，再考虑抽取通用生命周期能力。
- 允许发弹量、射击热量和 chassis buffer 都由 RMUL RuleSet 按机器人维护；合法 committed shot 同时扣减允许发弹量并增加热量，移动阶段则通过最薄的 `prepare_movement()` / `can_move()` 边界接入 Buffer 与 chassis-off。赛季专属状态不预先抽象成通用武器或能源系统。
- 地图现为二维静态障碍 + 语义 Zone；RMUL high-ground footprint 已能显示但不产生高度规则。跨越高度、斜坡、隧道净空和交互卡 dead-zone 检测没有通用表示。只有在具体场景需要后，再决定采用离散区域/通行标签还是其他最小表达。

## 尚未实现的 2026 专属规则

- 机器人战斗参数与实际设备行为的完整一致性；除 Hero、Sentry 和所选 Infantry 的 HP 外，移动、攻击距离、攻击间隔与直接伤害仍是 synthetic lab abstraction。
- 已实现合成布局下己方补给区按机器人上限 HP 25%/秒回血、R45 敌方补给禁区计时，以及确定性黄牌扣血 / 累计红牌；判罚 HP 损失与攻击 HP 损失统一记入对方攻击伤害。定时金币、落后 VP 差奖励和 Hero/Infantry 兑换价格已实现；英雄死亡后的 42 mm 屏蔽条件仍未实现。
- 战亡时射击热量归零和 Buffer 恢复 60 J 已实现，并由同一个 `robot_destroyed` 事实路径清除普通热锁与 chassis-off；永久热锁仍保留。异常离线或被罚下时的复活例外仍未实现。
- 60 J Buffer、10 Hz 功率结算和耗尽后 5 秒 chassis power-off 已实现，但当前 `Pr` 是基于 movement intent 的 synthetic Rules Lab demand（moving=`Pl+5 W`、stationary=0），不是实车底盘功率测量或动力学。物理弹丸、17 mm / 42 mm 命中与官方伤害机制，以及哨兵的其他规则外自动运行细节仍未实现。允许发弹量、基础兑换经济、10 Hz 射击热量冷却、临时/永久发射机构热锁已实现。
- VP 超时平局时按总攻击伤害、全队剩余 HP 顺序比较已实现；R45 的自动计时判罚已实现。严重损伤触发的主观红牌、其他违例、双方黄牌、操作界面遮挡、哨兵断电、离线例外和裁判判负仍未实现。攻击伤害以模拟器记录的实际 HP 损失近似。
- 官方场地的 12 m × 8 m 基本 footprint、中心对称关系、中央控制位置以及 supply/control/high-ground top-down 语义已落地。仍缺：V1.2.0 内部模块的可审计精确尺寸、真实高度/坡道、elevation-aware LOS、交互卡 dead zones、场地施工公差对应的实体几何，以及实际机器人 footprint。

Hero / Infantry 的 AI 购买策略、热量战术与功率管理策略尚未实现；它们不会主动停车回能或规划 burst movement，只受 RuleSet 的移动 gate 约束。它们会保持规则配置的 0 初始允许发弹量，不能攻击。Sentry 从 750 开始且不能兑换。本实现按每次 `Match.update` 的 VP 差变化检查 70/140 两个阈值；若一帧跨越两个阈值，两笔奖励给该帧末 VP 较低队伍。官方手册 V1.2.0 未细分帧内跨越顺序，动态答疑面板也未能逐条复核。

以上规则细节应留在 RMUL 2026 的 RuleSet/YAML 包中；对区域检测、机器人状态、资源值的抽象，仅在需要时留在 Engine。当前 `training-v0` 仍保留为原有合成训练沙盒，RMUL rules lab 不改变它的规则或参数。
