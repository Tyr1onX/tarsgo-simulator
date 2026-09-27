# RuleSet 架构

## Engine

`core.Match` 持有唯一一份比赛状态：地图、机器人、移动、碰撞、AI、战斗和经过时间。它按固定流程推进模拟，并把开始、逐帧规则更新和胜负判断交给当前 RuleSet。Engine 不判断赛季、胜利点或某个赛季的胜负条件。

## RuleSet

规则实现位于 `src/tarsgo_simulator/rules/`。`RuleSet` 是一组小型 Python 方法：提供机器人参数和时间限制，接收 Match 的 reset/update 调用，并返回比赛结果。RuleSet 读取或修改同一个 Match，不持有第二份机器人列表。

`registry.py` 是唯一的规则 ID 选择入口，显式注册 `training-v0` 和 `rmul-2026-3v3`。后者是部分、实验性规则集，不代表完整赛季支持。未知 ID 显式报错，不回退到默认规则；新增规则时显式添加一项，不扫描模块或加载插件。

## YAML 与 Python

通用 loader 校验 schema 与规则元数据（ID、状态、赛季、来源等），保留规则数据供对应 RuleSet 解释。它不假定所有规则都是 `synthetic`。`TrainingV0Rules` 自行要求 `status: synthetic` 并校验自己的参数。

YAML 保存适合核对和调整的数据参数；胜负、复活、区域计分等机制写在对应 Python RuleSet 中。不把机制编码为通用规则 DSL。

## 历史规则

每个赛季和官方版本使用独立规则 ID / 配置文件。发布新版本时新增规则包，不覆盖已核验的旧版本。`training-v0` 作为合成沙盒长期保留。新赛季流程是：建立独立规则包、对照差距文档、实现专属 RuleSet、运行新旧规则回归测试。

## 比赛事件

`Match.current_events` 只保存当前更新帧的事实。目前仅有 `robot_destroyed`：Match 对比更新前后的存活状态，在统一的 True→False 边缘产生一次事件，然后调用 RuleSet。没有 EventBus、订阅者或历史队列；重置会清空事件状态。RMUL 规则使用该事件扣除所属队伍 VP。

## 区域

Core 的 `Zone` 只表达带 ID 的矩形，边缘包含在区域内；机器人中心点由 RuleSet 查询。区域命名含义、占领状态、计分和控制延迟均由对应规则集负责。无区域的 training-v0 场景保持兼容。
