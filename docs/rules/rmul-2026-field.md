# RMUL 2026 3V3 场地二维表示

本文件记录 TARS-Go Simulator 对 **RoboMaster 2026 机甲大师高校联盟赛比赛规则手册 V1.2.0（2026-01-09）** 3V3 场地的二维表示边界。规则来源仍以官方 V1.2.0 手册为准；本文件不把社区 CAD、截图比例或旧版图纸当作官方尺寸来源。

- 官方规则源：[RMUL 2026 比赛规则手册 V1.2.0](https://bbs-web-static.robomaster.com/b7160ccc6a6c47eb98cac2e10ca375631767932801094/RoboMaster%202026%20%E6%9C%BA%E7%94%B2%E5%A4%A7%E5%B8%88%E9%AB%98%E6%A0%A1%E8%81%94%E7%9B%9F%E8%B5%9B%E6%AF%94%E8%B5%9B%E8%A7%84%E5%88%99%E6%89%8B%E5%86%8C%20V1.2.0%EF%BC%8820260109%EF%BC%89.pdf)
- Secondary cross-check：[Potential 战队 RMUL2026 地图开源图纸 V1.2.0 说明](https://bbs.robomaster.com/article/1639469?source=1)


## 证据边界

本轮重新核对 V1.2.0 §3.2、§3.2.1～§3.2.4 以及图 3-1～图 3-9。可可靠确认：

- 战场是 **12 m × 8 m** 的区域。
- 战场为中心对称布局。
- 场内包含红蓝双方启动区兼补给区、两处高地和中央控制区。
- 控制区位于战场中心。
- 启动区兼补给区铺设场地交互模块卡；规则同时提示交互卡检测可能存在死区。
- V1.1.0 修改日志明确写明“调整 3V3 对抗赛高地尺寸”，因此不能直接把 V1.0.0 开源场地图纸当作 V1.2.0 真值。

当前可访问的 V1.2.0 文本提取没有可靠保留图 3-3、图 3-6、图 3-8 中所有尺寸标注，且本轮没有从官方 PDF 图像中得到可审计的精确数值。因此下表中除战场整体尺寸、中心对称关系和控制区中心位置之外，**内部矩形 footprint 不宣称是官方精确尺寸**。

## 坐标与比例

Rules Lab 保持现有 Engine 的抽象 float world coordinates：

- **100 world units = 1 m**
- 对已经从官方手册确认的毫米尺寸，可使用 world units = official mm / 10
- 战场 12 m × 8 m 因而映射为 1200 × 800 world units
- Simulation 原点为左上角 (0, 0)，x 向右、y 向下；这是桌面二维模拟约定，不宣称与官方工程图坐标轴一致
- move_speed = 190、collision_radius = 18、A* grid = 20 的 Engine 参数不改；可近似理解为 1.90 m/s、0.18 m、0.20 m 的 Rules Lab 比例，但它们仍是 synthetic parameters，不是官方机器人速度或尺寸

## 当前二维几何

| 元素 | 官方尺寸 | 官方位置 | Simulation 坐标 (x, y, w, h) | 来源 | 状态 |
| --- | --- | --- | --- | --- | --- |
| battlefield | 12 m × 8 m | 核心战场 | (0, 0, 1200, 800) | V1.2.0 §3.2.1，图 3-3 | **official-confirmed** |
| red supply/start | 本轮未可靠读取图中精确数字 | 红方启动区兼补给区；与蓝方中心对称 | (40, 250, 200, 300) | §3.2.2，图 3-4～3-5 | **approximation / dimensions unverified** |
| blue supply/start | 本轮未可靠读取图中精确数字 | 与红方中心对称 | (960, 250, 200, 300) | §3.2.2，图 3-4～3-5 | **approximation / dimensions unverified** |
| center control | 本轮未可靠读取图中精确数字 | **战场中心** | (550, 350, 100, 100)，中心 (600, 400) | §3.2.4，图 3-7～3-8 | **center official-confirmed; footprint approximate** |
| red high ground | V1.1.0 曾调整尺寸；本轮未可靠读取 V1.2.0 图中精确数字 | 红方一侧高地 | (280, 200, 200, 400) | §3.2.3，图 3-6；V1.1.0 修改日志 | **approximation / dimensions unverified** |
| blue high ground | 同上 | 与红方中心对称 | (720, 200, 200, 400) | §3.2.3，图 3-6 | **approximation / dimensions unverified** |

这些 approximation 的目的只是让 Rules Lab 第一次在正确的 **12:8 战场尺度、中心对称关系和场地模块语义** 下运行。后续只有拿到可直接审计的 V1.2.0 图中尺寸时，才应把对应内部 footprint 从 approximation 升级为 official-confirmed。

## 高地表示

高地当前复用通用 Zone，ID 为 red-high-ground 与 blue-high-ground。

它只提供二维 footprint 和桌面显示，不产生规则效果，也**不是 obstacle**。当前没有：

- elevation / Z axis
- ramp traversal physics
- chassis pitch / slope
- elevation-aware LOS
- 高地射程、视野、伤害或速度增益

因此机器人可以在当前 2D approximation 中穿过高地 footprint。Vertical geometry / ramp traversal is not simulated yet.

## 补给区与控制区

RuleSet 不生成地图，只继续引用既有 zone ID：red-supply、blue-supply、center-control。

因此已有的 healing、weak removal、projectile exchange、R45 enemy-supply forbidden-zone、control capture 和 VP drain 逻辑不需要知道新的坐标。地图几何继续由 scenario YAML 提供。

交互模块卡的真实死区没有建模。当前仍以机器人中心点是否落在矩形 Zone 内作为离散检测近似。

## 出生点

三台机器人在各自启动/补给区内使用 synthetic placement：

- Red: (120, 310)、(120, 400)、(120, 490)
- Blue: (1080, 490)、(1080, 400)、(1080, 310)

这些点满足中心对称、位于己方供给/启动区域内部且彼此不重叠，但**不是官方固定出生坐标**。规则只给出赛前放置区域时，不应把模拟器选择的三个点冒充为赛事规定。

## Desktop Viewport

桌面层使用统一、无旋转的 Viewport：

- 固定窗口：1100 × 780
- world → screen：screen = origin + world × scale
- screen → world：world = (screen - origin) / scale
- scale 取可用 field rectangle 的宽高比例最小值，因此保持 uniform scale，不拉伸 12:8 场地
- field viewport 外的 screen point 返回 None
- 机器人、障碍、Zone、选择环与框选命中统一走同一个 transform

Viewport 只存在于 desktop/，Core 不依赖 Pygame 或 pixel；没有 zoom、pan、rotation、camera follow、minimap 或 scene graph。

## 社区图纸的证据地位

RoboMaster 社区文章《RMUL2026地图开源图纸V1.2.0》（Potential 战队，2026-02-21）说明：官方公开场地图纸仍是 V1.0.0，而 V1.2 规则修改了部分尺寸，社区模型据 V1.2.0 手册重新制作。

本项目只把这条信息作为 **secondary engineering cross-check**，用于支持“不要直接沿用 V1.0.0 CAD”这一工程判断。本轮：

- 没有把社区 STEP/CAD 坐标写成官方真值
- 没有复制社区模型
- 没有复制官方 PDF 截图、PNG、STEP、CAD 或其他赛事视觉资产
- 场地图形全部由 YAML 几何重新绘制

官方手册与现场要求始终优先于任何社区模型。
