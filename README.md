# TARS-Go RoboMaster 战术训练模拟器

面向 TARS-Go 队伍的新队员教学与战术推演项目。当前版本提供一局单机步兵 2v2 教学对战；官方比赛规则和实车参数仍在独立核验中。

## 已确定的技术路线

- Python 3 + Pygame 桌面应用。
- Windows 是第一发布平台，macOS 同步支持；两个平台分别构建。
- 游戏规则与状态放在 `src/tarsgo_simulator/core/`，Pygame 渲染与输入放在 `src/tarsgo_simulator/desktop/`。
- 赛季规则、队伍参数和教学场景使用 YAML，集中在 `configs/`。
- V0 为本地单机；当前不做 Web、手机端、局域网对战或服务端。
- 核心逻辑不依赖 Pygame，为未来平台扩展保留边界。

## 当前状态

### Current playable slice

- Infantry 2v2：玩家可点击切换并分别控制两台己方步兵。
- 敌方两台步兵独立追击；左键选择机器人、右键移动，路径会绕开障碍物。
- 机器人实体会互相阻挡，不能互相穿透或重叠。
- 障碍物同时阻挡移动与攻击视线；双方获得视线并进入射程后自动交战。
- HP 归零时结束并显示胜方。
- 按 `R` 重新开始，按 `Esc` 退出。

`configs/rules/training-v0.yaml` 是内部合成训练参数，不代表官方比赛规则或 TARS-Go 实车参数。`configs/rules/2026-rmul-3v3.yaml` 继续作为待核实的官方规则占位文件。

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
- `tests/`：轻量测试入口。
- `.github/workflows/`：自动测试，以及 Windows/macOS 桌面构建。

## CI 产物

每次向 `main` 推送或提交面向 `main` 的 PR 时，GitHub Actions 会运行测试并分别尝试构建 Windows `.exe` 与 macOS `.app`。构建文件作为 workflow artifact 提供下载。当前构建流程未配置代码签名或 macOS 公证。

## 上游代码

上游 [T-DT-Algorithm-2026/rm_simulator](https://github.com/T-DT-Algorithm-2026/rm_simulator) 已按固定 commit 完成代码审计。本切片重新实现核心逻辑，没有复制上游代码或资源。
