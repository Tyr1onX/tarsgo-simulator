# TARS-Go RoboMaster 战术训练模拟器

面向 TARS-Go 队伍的新队员教学与战术推演项目。当前仓库处于 **V0 底座阶段**：先建立可维护的桌面端工程结构、配置约定和跨平台构建流程，暂不实现完整比赛机制。

## 已确定的技术路线

- Python 3 + Pygame 桌面应用。
- Windows 是第一发布平台，macOS 同步支持；两个平台分别构建。
- 游戏规则与状态放在 `src/tarsgo_simulator/core/`，Pygame 渲染与输入放在 `src/tarsgo_simulator/desktop/`。
- 赛季规则、队伍参数和教学场景使用 YAML，集中在 `configs/`。
- V0 为本地单机；当前不做 Web、手机端、局域网对战或服务端。
- 核心逻辑不依赖 Pygame，为未来平台扩展保留边界。

## 当前状态

仓库只提供启动窗口、目录边界、占位配置和 CI 构建骨架。配置中的规则、机器人和场景数据都是未验证的空白草稿，不代表官方规则或 TARS-Go 实车参数。

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
- `tests/`：轻量测试入口。
- `.github/workflows/`：自动测试，以及 Windows/macOS 桌面构建。

## CI 产物

每次向 `main` 推送或提交面向 `main` 的 PR 时，GitHub Actions 会运行测试并分别尝试构建 Windows `.exe` 与 macOS `.app`。构建文件作为 workflow artifact 提供下载。当前构建流程未配置代码签名或 macOS 公证。

## 后续复用评估

首个可运行底座稳定后，再评估是否复用 MIT 项目 [T-DT-Algorithm-2026/rm_simulator](https://github.com/T-DT-Algorithm-2026/rm_simulator)。当前仓库没有复制该项目代码或资源。评估时先记录上游具体 commit、模块边界与许可证要求，再决定是否移植和如何保留署名。
