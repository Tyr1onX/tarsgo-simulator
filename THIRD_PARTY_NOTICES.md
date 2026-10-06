# 第三方许可证说明

## 本项目代码

本仓库自己的代码适用根目录 `LICENSE` 中的 MIT License。

## 当前依赖

依赖版本范围见 `pyproject.toml` 与 `requirements-dev.txt`。下表记录上游声明的许可证；它不是最终打包文件的完整许可证清单。

| 依赖 | 用途 | 上游许可证 |
| --- | --- | --- |
| Pygame | 运行时 | GNU LGPL v2.1；上游说明见 [pygame README](https://github.com/pygame/pygame#license) 与其 `docs/LGPL.txt` |
| PyYAML | 运行时 | MIT；见 [PyYAML 项目](https://github.com/yaml/pyyaml#license) |
| pytest | 开发与 CI 测试 | MIT；见 [pytest 项目](https://github.com/pytest-dev/pytest#license) |
| PyInstaller | 开发与桌面打包 | GPL v2 with exception；少数文件另受 Apache-2.0 约束。其例外允许分发由它构建的应用，但仍须遵守被打包依赖的许可证；见 [PyInstaller 许可证说明](https://pyinstaller.org/en/latest/license.html) |

初始底座没有 vendoring、复制或改写外部项目源码，也没有加入第三方图片、字体或音效。当前 CI 只提供构建骨架。准备分发 `.exe` 或 `.app` 时，须根据实际解析并打入应用的依赖版本生成完整 notices，并确认 Pygame 所带 SDL 组件等传递依赖的许可证要求。

## RMUC 美术资源

`assets/rmuc/` 第一批场地地板、Base 与 Outpost 图像是本项目在 2026-10-06
使用内置图像生成工具、依据项目自拟提示词创作的原创表现层资源。未使用
官方图片、队伍机器人照片、网络素材或其他第三方素材；来源和提示摘要见
[`assets/rmuc/README.md`](assets/rmuc/README.md)。这些项目资源按根目录
`LICENSE` 中的 MIT License 分发。

## 计划评估的上游项目

[T-DT-Algorithm-2026/rm_simulator](https://github.com/T-DT-Algorithm-2026/rm_simulator) 是后续候选评估对象；前期调研将其识别为 MIT 项目。当前没有从该仓库复制任何代码或资源。真正复用之前，需要重新核对选定 commit 的许可证、版权声明、资源许可和依赖，并记录上游 commit 与本项目的修改。
