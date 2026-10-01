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
- RMUC 2026 Regional Rules Lab：双方各有 Hero、Engineer、Infantry ×2、Sentry，以及可受伤的 Base / Outpost。当前实现 V1.4.0 的 Base / Outpost 生命周期、420 秒胜负链、Hero / Infantry Experience + Performance、Engineer Energy Unit / Tech Core D1-D4、收入侧 Economy、17/42 mm 允许发弹量兑换、Shooting Heat，以及 chassis Buffer / power-off gameplay。Hero/Infantry 初始 allowance 为 0，Sentry 初始 300；本地兑换使用己方 synthetic supply/base/outpost buff zone，远程兑换要求连续 6 秒脱战且购买后 6 秒生效。17mm/42mm 每次 committed shot 分别 +10/+100 Heat，Heat 以 10 Hz 冷却；Hero/Infantry 动态读取当前 Performance 的 Heat Limit/Cooling，automatic Sentry 固定 260/30。所有地面机器人拥有基础 60 J Buffer，底盘功率同样以 10 Hz 结算：Hero/Infantry 动态读取当前 Performance 的 chassis power limit，Engineer 固定 120 W，automatic Sentry 固定 100 W；Rules Lab path intent 使用 synthetic `Pr=Pl+5 W`，Buffer 耗尽后只禁用 chassis movement 5 秒并保留 path。Tech Core D3 first 已提供全队 25% Defense，D4 first 将其提升为 50%，并为 Base 结算 +2000 当前 HP、溢出部分转为 RuleSet-private Virtual Shield；Base 受伤顺序为 Outpost invincibility → Defense → Shield → HP。静态场地 Defense 点也已接入：己方 Base/梯形高地 50%，两个中央高地点分别占领且为 Hero/Infantry/Sentry 提供 25%，合法 Outpost 点提供 25%；Occupy 离点失效遵循 2 秒延迟，Robot 最终 Defense 与 Tech Core 同类效果取最大值。Terrain Crossing 规则级增益也已接入：Road 3s 顺序触发、Elevated 5s、Launch Ramp 10s、Tunnel 3s；Launch/Elevated 为 25%/30s，Road 为 25%/5s 且 15s 内不可再次获得，Tunnel 为 50%/10s 并提供独立 Cooling×2/120s；Launch/Elevated/Road 活跃期间再获得同组 Buff 会升级到 50% 并保留较长 duration。每种 Terrain 首次获得给 Hero/Infantry +300 XP。己方 Fortress 也已接入：己方 Outpost 首次被击毁后永久启用，Infantry/Sentry 中同一时间仅一台己方机器人占领，沿用 2 秒 Occupy release；占领者获得 50% Defense，并按 `w=floor((Base max_hp-Base hp)/40)`、cap75 获得动态 Cooling 增量。Fortress `base+w` 与 Tunnel `base×2` 比较最终 Cooling 取最大而不相加。Fortress reserved 17mm allowance 也已接入：首次合法己方 Fortress 占领按 `N=min(500,100+2*floor(Δ/15))` 初始化独立 reserve，合法 occupant 射击优先消耗 reserve，耗尽后才消耗自身 allowance；离点后 reserve 保留但不可使用，2 秒 release 内仍可使用，反复进出不免费 refill，Base HP 变化只按 N 的差额增补或 clamp。该 reserve 不花金币、不占 purchased_17mm cap，并在 HUD 中与自身 allowance 分离显示为 `17:x FR:y`。敌方 Fortress 链也已接入：elapsed≥180 且目标 Outpost 曾被击毁后，Infantry/Sentry 可各自独立占领对方 Fortress；沿用 2 秒 Occupy release，Occupy 失效或死亡后累计时间保留 3 秒并暂停，单机器人累计 20 秒即复用既有 `base_armor_deployed` 展开目标 Base Protective Armor。V1.4.0 occupant 获得 100% Vulnerability，伤害按 `1-Defense+Vulnerability` half-up 结算；Armor 展开后所有该 Fortress occupant 的 Vulnerability 立即归零。Radar Vulnerability、真实 Base armor geometry、远程回血、立即复活、Drone air support、Energy 等其余 modifier 与 42mm shielding/overfire 仍未实现。
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

`rmuc-2026-region-v1.4.0` 同样处于 **partial / experimental** 状态。当前 Experience 覆盖 Hero / Infantry 的 deterministic committed-shot、actual-damage 和 known-killer 路径；完整 Lv1～Lv10 Performance 表已录入。Engineer 可以在 synthetic resource zone 获取最多 2 个 rules-level Energy Unit credits，在 synthetic assembly zone 启动 Tech Core D1-D4。D4 使用 own/opponent 两个逻辑 Core slot、Step 1～6、Step 2/3/5/6 的 5 秒同步窗、45 秒总窗和跨队 15 秒 priority buffer。RMUC income economy 已实现 400+评级修正初始金币、官方 timed grants、Tech Core 周期收入与 D4 takeover penalty；周期收入采用 Rules Lab 的 battle-stage global 10 秒边界约定。允许发弹量已接入同一 wallet：`E` 为己方 synthetic supply/base/outpost buff point 的本地兑换，`F` 为脱战后的远程兑换；remote purchase 即时扣金币/占 team cap，6 秒后 allowance 才生效。每个 committed shot 消耗 1 allowance，并按 17mm +10 / 42mm +100 增加 Heat，再结算 shot Experience；allowance=0 或 Heat lock 时不会 commit synthetic attack。Heat 使用 10 Hz 冷却，Hero/Infantry 直接读取当前 Performance Heat Limit/Cooling，automatic Sentry 固定 260/30。chassis Buffer 同样按 10 Hz 结算，基础上限 60 J；当前 Rules Lab 用 path intent 代表 synthetic movement demand：`Pr=当前Pl+5 W`，静止或底盘断电时 `Pr=0`。Hero/Infantry 的 Pl 动态来自当前 Performance，Engineer/Sentry 分别固定 120/100 W；Buffer 耗尽触发 5 秒 movement-only power-off，path 保留、launcher 不因此禁用，断电期间 Buffer 继续按同一公式恢复。Sentry 初始 300 发，并在 elapsed 60/120/180/240/300/360 累积可领取的 100 发 supply allowance。D3 first 现在给予全队当前地面机器人、Outpost、Base 25% Defense；D4 first 升级为 50%（不叠成 75%），并让 Base 当前 HP +2000、超出 5000 的部分进入 RuleSet-private Virtual Shield。Defense 使用显式 half-up 整数结算；Base damage 先 Defense、再 Shield、最后 HP，Shield-only hit 不产生 HP-loss event，因此当前不计 damage XP / attack-damage score。静态场地 Defense Buff Points 已实现：己方 Base 与梯形高地为 50%，两个 Central 点独立占领并为 Hero/Infantry/Sentry 提供 25%，Outpost 点按前哨存活/前 300 秒敌方占领条件提供 25%；离点 Occupy 状态有 2 秒失效延迟，Robot effective Defense 与 Tech Core Defense 取 max 而不相加。Terrain Crossing 已使用 synthetic RFID rectangles + RMUC-private sequence state 实现：Road lower→upper 3s、Elevated lower→upper 5s、Launch first→second 10s、Tunnel end→middle→other end 3s；中途检测其它 modeled RFID 会中断。Terrain Defense 与 Tech Core/static Defense 继续取 max；Tunnel Cooling×2 直接乘入现有 effective cooling，不改变 Heat Limit。首次四类 Terrain 各 +300 XP，死亡清 active Terrain Buff 但保留本局首次获得历史。己方 Fortress Buff 已实现：own Outpost 首次被击毁后永久启用，仅 Infantry/Sentry 可作为单一己方 owner，离点 2 秒后释放；owner 获得 50% Defense 与随己方 Base 当前 HP 实时变化的 Cooling `+w`（`w=floor(Δ/40)`、cap75）。Tunnel×2 与 Fortress +w 比较完整 Cooling 结果取 max；Virtual Shield 不计入 Δ。Fortress reserved 17mm allowance 已与自身 allowance 分离实现：首次合法占领按当前 Base HP loss 初始化 N，后续不因重新进点 refill；Base 继续掉血只补新增 capacity，D4 heal 等导致 N 下降时 clamp reserve；合法 occupant committed shot 优先 reserve，reserve=0 后 fallback own allowance。HUD 分离显示 `17:x FR:y`，coins 与 purchased cap 不受影响。敌方 Fortress occupation / V1.4.0 100% Vulnerability / 20s Base armor trigger 已实现：180s 后且目标 Outpost 曾被击毁才开放，多台 Infantry/Sentry 独立累计；离点 2 秒内仍 Occupy 并继续计时，Occupy 失效或死亡后 3 秒 retention 暂停保存，回点续算。单机器人满 20 秒即复用现有 `base_armor_deployed`；Armor 已展开时 Fortress Vulnerability 为 0，且不会修改 Base HP/max HP/Virtual Shield/Outpost invincibility。Radar Vulnerability、真实 Base armor geometry、远程回血、立即复活、空中支援、Assembly invincibility、Energy Mechanism、Attack Buff、真实 terrain physics、真实底盘电机/电气模型、muzzle velocity 与 42mm shielding/overfire 仍未实现。真实 Core pose/motion、overload/obstruction、临时激活战亡 Engineer 同样继续留在 gap。当前 2800 × 1500 Rules Lab 的 start/resource/assembly/rebuild/exchange rectangles 与 Base/Outpost 坐标都不是官方完整场地复刻。射击仍是 direct-damage approximation：17 mm 为 20 damage、42 mm 为 200 damage，没有装甲模块命中或实体弹丸；底盘 `Pr` 也只是稳定演示 Buffer 的 synthetic stress approximation，不是实测功率。RMUC Rules Lab 中单选 Engineer 可用 `G` pickup credit，`1/2/3/4` start/request D1-D4，`Enter` confirm D1-D3，`Q/W` confirm 当前 D4 step 的 own/opponent Core。桌面 UI 默认采用简化视图：地图上的机器人只显示短标签（如 `H L1`、`E`、`I1 L1`、`S`）与 HP bar，projectile / Heat / Buffer / power / Energy Unit / Fortress reserve / status 等详细状态移到右侧 Selected Unit 面板；Terrain RFID 等内部规则 trigger 默认隐藏，按 `D` 可切换 Debug Geometry 并恢复全部 zone 原始 ID 和地图 status。顶部 HUD 只保留双方 Base / Outpost / Coins 与比赛时间，Tech Core、收入、重建机会和累计伤害放在右侧第二层信息区。 PR #41 进一步加入 desktop-only 战斗表现：RMUC 机器人按 Hero / Engineer / Infantry / Sentry 使用不同的程序化俯视几何轮廓，移动方向驱动平滑底盘朝向，Hero/Infantry/Sentry 的炮管会朝近期视觉攻击目标转动；合法 committed shot 后播放 17mm/42mm 区分明显的 muzzle flash、短 tracer 与仅由实际 HP-loss event 驱动的 impact。HP bar 使用短暂 recent-damage ghost，选中单位使用脉冲环/四角 bracket，右键移动显示短暂目标标记，选中玩家单位可看到淡色 path。所有 orientation、visual projectile、impact、ghost HP 和 marker 都只存在于 `desktop/` 渲染层，不参与命中、伤害、碰撞、允许发弹量、Heat、Experience 或任何规则结算。 PR #42 进一步统一 RMUC battlefield/HUD：战场使用低对比 tactical grid、中央线和轻量阵营 tint；Base/Outpost 使用不同的程序化俯视结构，Base 直接从现有 `structure_statuses` 的 `SH:<value>` 绘制 Virtual Shield；Buff Zone 使用统一的低透明视觉语言，并仅在选中兵种相关或选中单位位于区域内时增强。顶部 HUD 改为左右阵营卡 + 中央时间；右侧 Selected Unit 以 HEALTH/WEAPON/CHASSIS/STATUS 分组并使用 progress bar 与状态 badge，Controls 按选中兵种上下文化，TEAM SYSTEMS 保持低视觉优先级。所有这些变化仍只存在于 desktop rendering 层。

RMUC Rules Lab 基础操作：

```text
LMB        Select
Shift/LMB  Multi-select
Drag       Box select
RMB        Move

E          Local ammo
F          Remote ammo
G          Energy Unit
1-4        Tech Core
Enter      Confirm
Q / W      D4 Core
D          Debug view
R          Restart
Esc        Quit
```

启动场景：

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
