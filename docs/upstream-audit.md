# 上游模拟器代码审计

### 上游基准

- 仓库：[T-DT-Algorithm-2026/rm_simulator](https://github.com/T-DT-Algorithm-2026/rm_simulator)
- 固定审计版本：[`a95c2060ebd461cda3614fe45c0e28735b6f26f4`](https://github.com/T-DT-Algorithm-2026/rm_simulator/tree/a95c2060ebd461cda3614fe45c0e28735b6f26f4)
- 许可证：MIT，版权行是 `Copyright (c) 2026 RoboMaster Simulator`；后续若移植代码，须保留上游版权和许可证，并在 `THIRD_PARTY_NOTICES.md` 标记来源及该 commit。
- 本轮直接审阅了入口、状态、机器人、地图、战斗、寻路、配置、渲染/输入、网络、测试、构建及资源引用；没有复制上游代码或资源。

### 实际架构

**单机运行链：**

`main.py::main → Game.__init__ → GameMap(map_path) → GameState(game_map) → _init_robots() → Game.run()`

`Game` 初始化 Pygame 窗口、时钟、`CombatSystem` 和同文件中的 `GameRenderer`。地图优先读取 `assets/map.png`；没有图片时由 `GameMap` 生成默认地形。配置在导入 `constants.py` 时读取 `config.yaml`，然后形成模块级常量和统计表。`GameState._init_robots()` 不读取队伍阵容配置，而是直接为红蓝双方各创建 Hero、Infantry、Sentry 各一台。

每帧依次处理事件、更新和绘制。左键选择/框选，右键把屏幕坐标转换为世界坐标并调用 `Robot.set_move_target()`。机器人启动自己的后台线程，调用 JPS 规划路径；`Robot.update()` 按路径移动并查询地图碰撞。更新阶段先运行 `GameState.update()`，再由 `CombatSystem.update()` 自动选择目标并处理射击，最后更新哨兵 AI。当前 `process_shot()` 是命中判定后直接扣 HP；虽定义了 `Bullet` 和子弹列表，但实际射击不创建或更新子弹。渲染在更新之后执行。代码入口：[main.py](https://github.com/T-DT-Algorithm-2026/rm_simulator/blob/a95c2060ebd461cda3614fe45c0e28735b6f26f4/main.py#L308)、[game_state.py](https://github.com/T-DT-Algorithm-2026/rm_simulator/blob/a95c2060ebd461cda3614fe45c0e28735b6f26f4/game_state.py#L77)、[robot.py](https://github.com/T-DT-Algorithm-2026/rm_simulator/blob/a95c2060ebd461cda3614fe45c0e28735b6f26f4/robot.py#L320)、[combat.py](https://github.com/T-DT-Algorithm-2026/rm_simulator/blob/a95c2060ebd461cda3614fe45c0e28735b6f26f4/combat.py#L102)。

**配置和硬编码边界：**

- `RobotType` 在 Python 中固定为 Hero / Infantry / Sentry；机器人 ID、Infantry 变体、弹种、射速上限、能否爬高，以及移动/热量/受伤等规则逻辑也在 Python 中。
- `config.yaml` 实际承载比赛时长、场地尺寸、直径、部分 HP/热量/冷却/速度/射击间隔/命中率、出生点、子弹数值、目标优先级、经济、胜利点、复活、地形和 UI 参数。尽管 YAML 写有弹种、射速上限、能否爬高等字段，`constants.py` 对这些字段仍使用 Python 硬编码值。
- 配置导入时通过宽松默认值回退；文件缺失时静默得到空配置，没有结构校验。阵容固定在 `GameState` 中。比赛计时、经济、控制区、回血/复活和胜负结算也集中在 `GameState`；虽声明了 PREP/COUNTDOWN，当前开始操作会直接从准备阶段进入战斗。
- `game_map.py` 用 Pillow/NumPy 读取并解释地图像素，也提供地形、碰撞和视线查询；`render_to_surface()` 在地图模块中局部导入 Pygame。默认地图的区域和墙体由 Python 生成。字体从 `fonts/SourceHanSansCN-Regular.otf` 加载，并和地图、配置一起纳入打包。
- `main_online.py` 又包含一份渲染器和 UI，并接入 `network.py`；`server.py` 再实现一套无窗口的比赛更新循环。服务端从每个客户端的接收线程直接处理会改变比赛状态的消息，而主循环也在更新状态，因此不应作为单机核心直接移植。

### 复用矩阵

| 上游模块 | 结论 | 原因 |
|---|---|---|
| `constants.py`、`config.yaml` | 小改 | 数值参数可作为 YAML 设计参考；类型、部分属性及规则公式仍硬编码，配置读取也需从导入时全局加载改成显式、可校验的简单加载。 |
| `game_state.py` | 重写 | 固定 3v3 阵容，并把时间、经济、控制区、复活、胜负和序列化集中在同一状态类；本项目只保留所需比赛状态和胜负逻辑。 |
| `robot.py` | 小改 | HP、移动、冷却等逻辑不直接导入 Pygame；但依赖全局配置，并由每个机器人管理寻路线程，需拆掉这类耦合。 |
| `game_map.py` | 小改 | 地形/碰撞/视线查询有参考价值；图像加载与默认场地布局需适配，`render_to_surface()` 应留在 desktop 层。 |
| `combat.py` | 小改 | 目标选择、射程、冷却和直接扣血可作参考；战斗逻辑依赖上游 Robot/GameState，Bullet 路径未实际使用。 |
| `pathfinding.py` | 重写 | 生产路径是 Robot 线程中的 JPS；另有未接入生产的 `PathfindingManager`/A* 路径。JPS 失败回退生成的直线路径不验证障碍；应采用单一、同步、可测试的寻路实现。 |
| `main.py` | 重写 | Pygame 启动、输入、更新和同文件渲染器混在一起；仅把操作方式作为参考，桌面层按新 core 接口实现。 |
| `main_online.py`、`network.py`、`server.py` | 暂不采用 | 包含重复 UI/比赛循环、线程网络及同步问题；与 V0 单机目标无关。 |
| `test_game.py` | 重写 | 自定义测试运行器覆盖若干逻辑点，但用例依赖固定阵容，寻路管理器测试也没有验证其生产接线；新测试应围绕无 Pygame 的 core 接口。 |
| `assets/map.png`、字体 | 暂不采用 | 地图以颜色编码地形，字体供 Pygame 加载；本轮没有审计这些二进制资源的独立授权和来源，首个切片用简单程序化地图。 |
| `build.py`、`rm_simulator.spec`、`build_windows.bat`、上游 Actions | 暂不采用 | 上游构建面向 Windows/Linux 的单机、联机和服务端包，没有 macOS 目标；本仓库已有独立的 Windows/macOS 构建流程。 |

### 需要解决的核心耦合

- **阵容和规则在 Python 中固定。** `RobotType` 固定三类机器人，`GameState` 固定每队三台；参数 YAML 化并没有让阵容可配置。新实现应由队伍/场景 YAML 提供实例，Python 直接实现规则，不引入通用规则 DSL。
- **核心和桌面尚未彻底分层。** `main.py` 承担窗口、输入、渲染和主循环；`game_map.py` 也有 Pygame 绘制方法。迁移时 core 只保留状态、地图查询、移动和战斗，窗口事件与绘制只放在 desktop。
- **寻路有两套运行路径和一段空兼容调用。** Robot 自己创建线程并调用 JPS；`PathfindingManager` 只在测试里实例化，模块提供的全局 getter 没有生产调用；`Robot.update_pathfinding()` 是空方法，却在每台机器人每次更新时调用。迁移应保留一条实现路径，不保留这些空壳。
- **测试没有覆盖端到端操作链。** 上游测试测试了机器人、地图、战斗和路径算法，但没有覆盖“桌面输入下达移动命令到移动，再到 HP 变化和结束比赛”的完整闭环。新 slice 应把规则测试放在无 Pygame 的 core。
- **射击表现和数据模型不一致。** 射击当前是命中概率通过后直接扣血；子弹速度参数和 Bullet 类没有进入实际战斗链。第一批迁移应明确定义一个可确定测试的攻击路径，不先引入未运行的弹丸模型。

### 第一批迁移范围

**唯一推荐：做一局单机“步兵 1v1”教学切片。** 它保留了启动、读取数据、双方阵容、选择、移动、攻击、HP 变化和结束一局的完整反馈链，同时绕开上游固定 3v3、哨兵 AI、复杂经济/复活规则及多人网络。

在本仓库现有占位配置上补足最小字段：`configs/rules/2026-rmul-3v3.yaml` 放切片所需的比赛时长、步兵 HP/速度、攻击范围/间隔/伤害和胜负条件；`configs/teams/tarsgo.yaml` 与 `configs/teams/opponent-balanced.yaml` 各声明一名 Infantry；`configs/scenarios/first-steps.yaml` 声明小型矩形地图及双方出生点。YAML 只存参数和阵容数据，交战规则由 Python 明确实现。

下一批具体实现位置：

- 在 `src/tarsgo_simulator/core/` 增加简单配置读取、地图、机器人、寻路、战斗和比赛状态模块；core 不导入 Pygame。参考 `constants.py/config.yaml` 的可调数值、`game_map.py` 的通行查询、`robot.py` 的 HP/移动状态、`combat.py` 的射程/冷却/扣血概念；不搬线程/JPS 双路径，采用单一同步 A*。
- 在现有 `src/tarsgo_simulator/desktop/app.py` 实现窗口启动、左键选机器人、右键下达移动命令和地图/状态绘制；操作链以 `main.py` 为行为参考，不复制其 UI。
- 新增 `tests/test_match.py`：覆盖 YAML 加载、寻路绕障、移动、攻击扣血、HP 耗尽后比赛结束；这些测试不初始化 Pygame。
- 使用程序化地图和一个步兵类型；不迁移 3v3 固定阵容、Countdown、经济/胜利点、复活、控制/补给区、42mm 特例、哨兵 AI、网络与上游二进制资源。

本轮只记录上游来源，没有移植代码；因此当前无需修改 `THIRD_PARTY_NOTICES.md`。