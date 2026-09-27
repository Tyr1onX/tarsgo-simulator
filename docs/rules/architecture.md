# RuleSet 架构

## Engine

`core.Match` 持有唯一一份比赛状态：地图、机器人、移动、碰撞、AI、战斗和经过时间。它按固定流程推进模拟，并把开始、逐帧规则更新和胜负判断交给当前 RuleSet。Engine 不判断赛季、胜利点或某个赛季的胜负条件。

## RuleSet

规则实现位于 `src/tarsgo_simulator/rules/`。`RuleSet` 是一组小型 Python 方法：提供机器人参数和时间限制，接收 Match 的 reset/update 调用，并返回比赛结果。RuleSet 读取或修改同一个 Match，不持有第二份机器人列表。

`registry.py` 是唯一的规则 ID 选择入口。目前只注册 `training-v0`。未知 ID 显式报错，不回退到默认规则；新增规则时显式添加一项，不扫描模块或加载插件。

## YAML 与 Python

通用 loader 校验 schema 与规则元数据（ID、状态、赛季、来源等），保留规则数据供对应 RuleSet 解释。它不假定所有规则都是 `synthetic`。`TrainingV0Rules` 自行要求 `status: synthetic` 并校验自己的参数。

YAML 保存适合核对和调整的数据参数；胜负、复活、区域计分等机制写在对应 Python RuleSet 中。不把机制编码为通用规则 DSL。

## 历史规则

每个赛季和官方版本使用独立规则 ID / 配置文件。发布新版本时新增规则包，不覆盖已核验的旧版本。`training-v0` 作为合成沙盒长期保留。新赛季流程是：建立独立规则包、对照差距文档、实现专属 RuleSet、运行新旧规则回归测试。

## 比赛事件

本轮没有加入 `MatchEvent`。当前伤害由 combat 直接调用 `Robot.take_damage()`，死亡也在该对象中完成；要可靠记录 `robot_destroyed` 就需要改造伤害路径。本轮优先建立 RuleSet 边界，后续若出现回放或规则消费事实事件的实际需求，再把事件接到单一伤害/死亡入口。
