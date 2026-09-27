# TARS-Go RoboMaster 战术训练模拟器

面向 TARS-Go 队伍的新队员教学与战术推演项目。当前提供合成参数的步兵 2v2 训练沙盒，以及具有 Hero、Infantry、Sentry 阵容结构的 RMUL 2026 部分规则实验场景。

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
- RMUL Rules Lab：双方各有 Hero、Infantry、Sentry；玩家控制己方 Hero 和 Infantry，Sentry 自动运行，对手三台由单机 AI 控制。
- 右键下令时，单台按指定位置移动；多台保持当前相对队形分别移动，路径会绕开障碍物。
- Training-v0 中，对手两台步兵独立追击。
- 机器人实体会互相阻挡，不能互相穿透或重叠。
- 障碍物同时阻挡移动与攻击视线；双方获得视线并进入射程后自动交战。
- RMUL 2026 rules lab 中，机器人在己方补给区按上限 HP 的 25%/秒回血；进入敌方补给禁区会按计时触发黄牌与累计红牌；超时同 VP 时依次比较实际累计伤害与全队剩余 HP。
- HP 归零时结束并显示胜方。
- 按 `R` 重新开始，按 `Esc` 退出。

`training-v0` 是长期保留的 synthetic sandbox，不代表官方比赛规则或 TARS-Go 实车参数。RuleSet 边界用于让不同规则并存；RMUL 2026 实验实现不会修改训练模式。参见 [规则架构](docs/rules/architecture.md)。

`rmul-2026-3v3` 目前处于 **partial / experimental** 状态：rules lab 使用 Hero + Infantry + 自动 Sentry 的 3V3 阵容结构，用于试验 VP、中央控制区、战亡扣分、自动复活、弱化 / 无敌、补给回血、敌方补给禁区 R45 定时黄/红牌、计时和胜负闭环。部分 HP 值采用手册参数，其余移动、射程、攻击间隔和直接伤害仍为实验抽象；补给区与地图为合成布局，不代表完整比赛规则或官方场地图。经济、弹药、热量 / 缓冲能量、弹丸和主观裁判判罚尚未实现；攻击仍是合成的直接扣 HP。回血按本方区域中心点检测，攻击伤害统计采用模拟器实际 HP 损失。启动实验场景：

```bash
python run_game.py --scenario configs/scenarios/rmul-2026-rules-lab.yaml
```

完整规则边界见 [RMUL 2026 摘要](docs/rules/rmul-2026-3v3.md) 和 [差距分析](docs/rules/rmul-2026-gap.md)。

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
