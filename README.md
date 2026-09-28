# TARS-Go RoboMaster 战术训练模拟器

面向 TARS-Go 队伍的新队员教学与战术推演项目。当前提供合成参数的步兵 2v2 训练沙盒、RMUL 2026 部分规则实验场景，以及 RMUC 2026 Regional V1.4.0 的 Base / Outpost 生命周期 Rules Lab。

## 已确定的技术路线

- Python 3 + Pygame 桌面应用。
- Windows 是第一发布平台，macOS 同步支持；两个平台分别构建。
- 游戏规则与状态放在 `src/tarsgo_simulator/core/`，Pygame 渲染与输入放在 `src/tarsgo_simulator/desktop/`。
- 赛季规则、队伍参数和教学场景使用 YAML，集中在 `configs/`。
- V0 为本地单机；当前不做 Web、手机端、局域网对战或服务端。
- 核心逻辑不依赖 Pygame，为未来平台扩展保留边界。

## 当前状态

### Current playable slice

- Training-v0 Infantry 2v2：玩家可左键选择、Shift 多选或拖框选择两台己方步兵。
- RMUL Rules Lab：双方各有 Hero、Infantry、Sentry；玩家控制己方 Hero 和 Infantry，Sentry 自动运行，对手三台由单机 AI 控制。战场使用 V1.2.0 已确认的 12 m × 8 m footprint（100 world units/m），并以二维 approximation 表示 supply/control/high-ground 语义区域。
- RMUC 2026 Regional Rules Lab：双方各有 Hero、Engineer、Infantry ×2、Sentry，以及可受伤的 Base / Outpost。当前实现 V1.4.0 的 Base / Outpost 生命周期、420 秒胜负链、Hero / Infantry Experience + Performance，以及 Engineer Energy Unit / Tech Core D1-D3：D2 首次完成解锁 team level cap 5→7，D3 首次完成解锁 7→10。Hero 使用 long-range-priority，Infantry 使用 hp-priority chassis + cooling-priority launcher。Power / Heat Limit / Cooling 会随等级计算并展示为规则参数，但 RMUC Heat / Buffer gameplay 尚未实现。Difficulty 4、Economy / Field Buff、Drone / Radar / Dart 和 projectile physics 仍未实现。
- 右键下令时，单台按指定位置移动；多台保持当前相对队形分别移动，路径会绕开障碍物。
- Training-v0 中，对手两台步兵独立追击。
- 机器人实体会互相阻挡，不能互相穿透或重叠。
- 障碍物同时阻挡移动与攻击视线；双方获得视线并进入射程后自动交战。
- RMUL 2026 rules lab 中，金币按倒计时发放；`E` — 为当前单选 Hero / Infantry 在己方补给区兑换一档允许发弹量。HUD 同时显示允许发弹量、射击热量和底盘 Buffer；热量按 10 Hz 冷却，并支持临时 `LOCK` 与当局永久 `PERM` 发射机构锁定。底盘使用官方功率上限与 60 J Buffer，以 10 Hz 结算，Buffer 耗尽后 chassis power-off 5 秒。Sentry 从 750 发开始且不能兑换增加；Training-v0 没有经济、热量或 Buffer 功能，按 `E` 无效果。
- RMUL 2026 rules lab 中，机器人在己方补给区按上限 HP 的 25%/秒回血；进入敌方补给禁区会按计时触发黄牌与累计红牌；超时同 VP 时依次比较实际累计伤害与全队剩余 HP。
- HP 归零时结束并显示胜方。
- 按 `R` 重新开始，按 `Esc` 退出。

`training-v0` 是长期保留的 synthetic sandbox，不代表官方比赛规则或 TARS-Go 实车参数。RuleSet 边界用于让不同规则并存；RMUL 2026 实验实现不会修改训练模式。参见 [规则架构](docs/rules/architecture.md)。

`rmul-2026-3v3` 目前处于 **partial / experimental** 状态：rules lab 使用 Hero + Infantry + 自动 Sentry 的 3V3 阵容结构，用于试验 VP、中央控制区、战亡扣分、自动复活、弱化 / 无敌、补给回血、R45 定时黄/红牌、金币、允许发弹量、射击热量、发射机构热锁、底盘功率上限、60 J Buffer、10 Hz 功率结算、5 秒 chassis power-off 和胜负闭环。射击仍是 synthetic direct-damage：每个合法攻击意图映射为 1 发允许发弹量和 1 次热量增加，但不会模拟实体弹丸、命中检测或官方武器伤害。底盘 `Pr` 也明确是 synthetic Rules Lab approximation：有 movement intent 时使用各机器人官方 `Pl+5 W`，stationary 时为 0；它不是实车电机、轮系、电流/电压或超级电容仿真。移动速度、射程、攻击间隔与伤害仍为实验抽象。地图已升级为 **V1.2.0 official-field 2D geometry approximation**：12 m × 8 m 战场 footprint 与中心对称/场地模块语义来自官方手册；当前 supply/control/high-ground 的内部矩形 footprint 仍明确标记为 approximation，因为本轮无法可靠读取 V1.2.0 图中全部尺寸数字。spawn positions 仍为 synthetic，elevation / ramps 与交互卡 dead zones 未模拟。当前 AI 不会为 Hero / Infantry 购买弹量，也不会主动做热量或功率管理；42 mm 屏蔽特殊情况和主观裁判判罚仍未实现。回血和兑换按本方区域中心点检测补给区，攻击伤害统计采用模拟器实际 HP 损失。启动实验场景：

```bash
python run_game.py --scenario configs/scenarios/rmul-2026-rules-lab.yaml
```

完整规则边界见 [RMUL 2026 摘要](docs/rules/rmul-2026-3v3.md)、[场地二维表示](docs/rules/rmul-2026-field.md) 和 [差距分析](docs/rules/rmul-2026-gap.md)。

`rmuc-2026-region-v1.4.0` 同样处于 **partial / experimental** 状态。当前 Experience 覆盖 Hero / Infantry 的 deterministic committed-shot、actual-damage 和 known-killer 路径；完整 Lv1～Lv10 Performance 表已录入。Engineer 可以在 synthetic resource zone 获取 Energy Unit，在 synthetic assembly zone 启动 Tech Core D1-D3，并通过显式 Rules Lab success confirmation 完成装配；D2/D3 首次完成分别把 team level cap 解锁至 7 / 10。装配机械位姿、Difficulty 4、周期金币、Defense Buff、Base +2000 / virtual shield、Unknown-source Experience redistribution 和动态 Heat / Buffer gameplay 均未实现。当前 2800 × 1500 Rules Lab 的 start/resource/assembly/rebuild rectangles 与 Base/Outpost 坐标都不是官方完整场地复刻。射击仍是 direct-damage approximation：17 mm 为 20 damage、42 mm 为 200 damage，没有装甲模块命中或实体弹丸。RMUC Rules Lab 中单选 Engineer 可用 `G` pickup Energy Unit，`1/2/3` start D1/D2/D3，`Enter` confirm abstracted assembly success。启动场景：

```bash
python run_game.py --scenario configs/scenarios/rmuc-2026-region-rules-lab.yaml
```

参见 [RMUC 2026 Regional V1.4.0 摘要](docs/rules/rmuc-2026-v1.4.0.md) 和 [RMUC 差距分析](docs/rules/rmuc-2026-gap.md)。

## 本地运行

需要 Python 3.11 或更新版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_game.py
```

Windows PowerShell 激活虚拟环境的命令为：

```powershell
.venv\Scripts\Activate.ps1
```

## 仓库结构

- `src/tarsgo_simulator/core/`：与窗口、输入和 Pygame 无关的模拟逻辑。
- `src/tarsgo_simulator/desktop/`：桌面入口、输入和 Pygame 渲染。
- `configs/rules/`：赛季与比赛规则 YAML。
- `configs/teams/`：队伍机器人参数 YAML。
- `configs/scenarios/`：教学场景 YAML。
- `docs/upstream-audit.md`：固定上游 commit 的代码审计和迁移建议。
- `docs/simulator-references.md`：华南虎公开仿真资料的基准、许可与工程参考边界。
- `tests/`：轻量测试入口。
- `.github/workflows/`：自动测试，以及 Windows/macOS 桌面构建。

## CI 产物

每次向 `main` 推送或提交面向 `main` 的 PR 时，GitHub Actions 会运行测试并分别尝试构建 Windows `.exe` 与 macOS `.app`。构建文件作为 workflow artifact 提供下载。当前构建流程未配置代码签名或 macOS 公证。

## 上游代码

上游 [T-DT-Algorithm-2026/rm_simulator](https://github.com/T-DT-Algorithm-2026/rm_simulator) 已按固定 commit 完成代码审计。本切片重新实现核心逻辑，没有复制上游代码或资源。
