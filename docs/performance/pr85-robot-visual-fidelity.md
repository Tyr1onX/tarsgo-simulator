# PR #85 — 机器人视觉与性能记录

本报告以 PR #84 稳定版 `123713539f25a5487537baa007d1336af53c552c` 为基线。测试场景为 RMUC 区域赛规则实验场，Pygame 2.6.1 / SDL 2.28.4，macOS，SDL dummy 显示后端，`1100×780`、60 Hz、3600 帧；忽略前 120 帧，统计 3480 帧。`render` 为基准工具测得的 `_draw` 总耗时。缓存 Surface 驻留内存按各缓存项的 pitch × height 求和，不含 Python/SDL 元数据。

| 指标 | PR #84 稳定复测记录 | 本机 main 复测 | 第一批完成 |
|---|---:|---:|---:|
| Frame interval p95 / p99 | 19 / 19 ms | 19 / 19 ms | 19 / 19 ms |
| Frame work p95 / p99 | 10 / 14 ms | 10 / 14 ms | 10 / 14 ms |
| Render p95 / p99 | 3.90 / 4.30 ms | 3.843 / 4.255 ms | 3.838 / 4.234 ms |
| 超过 33 ms 的帧 | 0 | 1 | 0 |
| 变换缓存命中率 | 99.26% | 99.253% | 99.251% |
| Surface 驻留内存 | 77,310,928 B（73.7 MiB） | 77,346,652 B（73.8 MiB） | 76,461,896 B（72.9 MiB） |

中间试制曾让所有倍率的 Infantry/Sentry 旋转都走 `rotozoom`。该版本测得 Render p99 7.058 ms、Frame work p99 15 ms，出现 6 帧超过 33 ms，最长间隔 61 ms。最终策略保留 Hero 现有行为；Infantry/Sentry 仅在缩放后最长边达到 64 px 时采用过滤旋转，全场视角沿用轻量 `rotate`，大倍率仍获得抗锯齿。第一批复测回到与基线相同的 Frame interval / Frame work 分位数，Render p99 4.234 ms，超过 33 ms 的帧为 0。

第一批性能结论只覆盖 Infantry 与 Sentry 的视觉变换。Engineer / Drone 第二批完成后会在同一机器、场景、分辨率、帧率和帧数下重测，并在此补充最终比较。

参见 [机器人视觉审计与真实 Pygame 前后证据](../pr85-robot-visual-audit.md)。
