# 第三方许可证说明

## 本项目代码

本仓库自己的代码适用根目录 `LICENSE` 中的 MIT License。

## 当前第三方代码与资源

初始底座未 vendoring、复制或改写外部项目源码，也未加入第三方图片、字体或音效。

运行依赖通过 Python 包管理器单独安装：

- Pygame：运行时依赖。
- PyYAML：运行时依赖。
- pytest：开发/CI 测试依赖。
- PyInstaller：桌面打包依赖。

依赖及其传递依赖仍受各自上游许可证约束。准备向队员分发打包文件时，应基于实际锁定的依赖版本核对并附上完整的第三方许可证与 notices。

## 计划评估的上游项目

[T-DT-Algorithm-2026/rm_simulator](https://github.com/T-DT-Algorithm-2026/rm_simulator) 是后续候选评估对象；前期调研将其识别为 MIT 项目。当前没有从该仓库复制任何代码或资源。真正复用之前，需要重新核对选定 commit 的许可证、版权声明、资源许可和依赖，并记录上游 commit 与本项目的修改。
