# 文档索引

启动器文档按用途归类。用户入口从「使用指南」开始；技术实现和打包说明放在「技术说明」；测试结果集中在「验证记录」。

## 使用指南

- [游戏与整合包导入、内容下载与加载器兼容](guides/modpack-import-and-compatibility.md)
- [联机与节点使用](guides/relay-usage.md)
- [Windows 故障排查](guides/windows-diagnostics.md)

## 技术说明

- [BMCLAPI 下载源接入](technical/bmclapi-downloads.md)
- [微软登录实现说明](technical/microsoft-login.md)
- [账号与源站安全边界](technical/node-accounts-security.md)
- [QML 界面结构](technical/qml-interface.md)
- [Windows 打包](technical/windows-packaging.md)
- [macOS 打包与 Qt 官方工具](technical/macos-packaging.md)

## 验证记录

- [启动器验收](validation/launcher-validation.md)
- [联机验证](validation/multiplayer-validation.md)
- [节点可用性验证](validation/node-availability-validation.md)
- [联邦节点验证](validation/node-federation-validation.md)
- [P2P 传输验证](validation/peer-transport-validation.md)
- [房间访问验证](validation/room-access-validation.md)

## 计划

- [联机完善路线图](planning/multiplayer-roadmap.md)

截图资源位于 [`images/`](images/)。

## 维护约定

- 新文档放入对应分类并更新本索引，`docs` 根目录只保留导航。
- 使用指南记录操作步骤；技术说明记录实现与边界；验证记录保留执行日期、环境和结果；计划记录后续工作。
- 验证记录描述对应日期的执行结果，当前功能支持范围以使用指南为准。
- 验证记录中的 `../../../multiplayer-tests/` 链接指向同一工作区的测试产物，不属于本仓库或发布包；只下载本仓库时可能无法打开。
