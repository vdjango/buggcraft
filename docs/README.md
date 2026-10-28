# 文档索引

启动器文档按用途归类：使用指南说明操作步骤，技术说明介绍实现与维护方式。

## 使用指南

- [启动器发布验收清单](guides/launcher-release-checklist.md)
- [游戏与整合包导入、内容下载与加载器兼容](guides/modpack-import-and-compatibility.md)
- [联机与节点使用](guides/relay-usage.md)
- [联机测试、网络快照与日志导出](guides/network-tester-guide.md)
- [Windows 故障排查](guides/windows-diagnostics.md)
- [游戏日志搜索、分类与高亮](guides/game-log-console.md)

## 技术说明

- [启动器功能覆盖核对清单（按操作顺序）](technical/launcher-function-coverage-checklist.md)
- [房间准备、玩家进度与管理：功能方案及验收清单](technical/room-preparation-workflow.md)
- [BMCLAPI 下载源接入](technical/bmclapi-downloads.md)
- [CurseForge 多源与资源服务](technical/content-gateway.md)
- [资源翻译平台规划与开放接口草案](technical/resource-translation-platform.md)
- [第三方启动器桥接接入](technical/bridge-integration.md)
- [微软登录实现说明](technical/microsoft-login.md)
- [账号与源站安全边界](technical/node-accounts-security.md)
- [启动器版本发布与自动更新](technical/launcher-updates.md)
- [QML 界面结构](technical/qml-interface.md)
- [Windows 打包](technical/windows-packaging.md)
- [macOS 打包与 Qt 官方工具](technical/macos-packaging.md)

截图资源位于 [`images/`](images/)。

## 维护约定

- 新文档放入对应分类并更新本索引，`docs` 根目录只保留导航。
- 使用指南记录稳定的操作步骤；技术说明记录实现边界和维护方式。
- 构建日志、临时测试结果、网络抓包和个人环境记录保留在本地，不进入仓库或发布包。
