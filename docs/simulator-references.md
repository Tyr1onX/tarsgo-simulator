# RoboMaster 仿真平台参考资料

本页记录可供工程实践参考的华南理工大学华南虎公开资料。SCUTRobotLab GitHub 组织已验证其关联域名为 `scutbot.cn`；这些资料适合作为战队训练模拟器的实践参考，**不能代替 RMUL 2026 官方规则手册或答疑**。

## 资料基准

| 资料 | 固定版本 | 公开内容 / 许可证 | 对本项目的参考价值 |
|---|---|---|---|
| [RM2021_simulation](https://github.com/scutrobotlab/RM2021_simulation/tree/06fb7d42d06f1a9e772f6db095bfb1f5c5b32c57) | `06fb7d42d06f1a9e772f6db095bfb1f5c5b32c57` | README 指向开发总结 Wiki 和两个发布版可执行程序；仓库本身不是完整源码。仓库许可证为 Apache-2.0。 | 早期队内训练和线上赛组织的实际需求、操作手册、部署流程。 |
| [RM2022_SimulatorX 技术报告](https://github.com/scutrobotlab/RM2022_SimulatorX/tree/f6268f96fe3b59528d93339aad0be6ed403835cd) | `f6268f96fe3b59528d93339aad0be6ed403835cd` | 技术报告及静态资料；该仓库不是 SimulatorX 应用源码。仓库许可证为 Apache-2.0。 | 2022 版本的重构、迭代和赛事使用背景。报告记载一个赛季有多轮发布，并用于大规模线上模拟赛。 |
| [SimulatorX（RMUC 2023）](https://github.com/scutrobotlab/SimulatorX/tree/7c453c2e775c16ddfc06269f47f502b35bb0005e) | `7c453c2e775c16ddfc06269f47f502b35bb0005e` | Unity / C# 平台源码与技术说明；README 标注 GPL-3.0，支持 Windows/Linux 客户端/服务端和 Android 客户端。 | 可检查更完整的平台架构、同步、记录和统计实现。比如 [`EntityManager.cs`](https://github.com/scutrobotlab/SimulatorX/blob/7c453c2e775c16ddfc06269f47f502b35bb0005e/Assets/Scripts/Gameplay/EntityManager.cs) 记录队伍总伤害；[`Dispatcher.cs`](https://github.com/scutrobotlab/SimulatorX/blob/7c453c2e775c16ddfc06269f47f502b35bb0005e/Assets/Scripts/Infrastructure/Dispatcher.cs) 集中分发并排队处理 Action。前者可作为未来研究规则伤害平局判定的参考；它对应旧版 RMUC，不能直接当作 RMUL 2026 机制。 |

## 对当前切片的影响

- SimulatorX 使用的 Dispatcher / Store / Action / Mirror 体系服务于多人、客户端/服务端同步、事件传播和回放。其 README 也记录了单链事件传播、调试可见性、性能和客户端预测方面的代价。当前 TARS-Go V0 是单机桌面程序，因此保持 Match 中的小型当前帧 `robot_destroyed` 事实列表；不移植 Dispatcher、网络同步或回放体系。
- SimulatorX 的全队伤害记录展示了较大规则模式如何累积伤害统计，但本轮仍不增加该统计。RMUL rules lab 在 VP 平局时暂判 DRAW，并在规则文档明确不等于正式完整判定。
- 华南虎资料用来理解真实训练、赛事组织和长期迭代问题。所有 RMUL 2026 数值与胜负条款仍以官方 V1.2.0 手册和后续可读取的官方答疑为准。

本项目本轮只研究并引用上述资料，没有复制代码、图片、模型或其他资源；因此没有新增第三方代码依赖，也不需要将其列入 `THIRD_PARTY_NOTICES.md`。若以后决定复用 SimulatorX 源码，必须先单独评估 GPL-3.0 对当前 MIT 项目的许可影响，并履行相应版权、许可证和修改声明要求。
