Bugg v2.0.3 测试版。当前版本仍在测试阶段，后续发布默认进入开发版更新渠道。

- 修复 macOS 原始 ZIP 缺少应用外层的问题，解压得到完整的 Bugg.app；Apple Silicon 和 Intel 分别提供对应包。
- 官网、下载站直接分发 GitHub 发布的原生 ZIP，取消下载站对原生安装包的二次压缩。Windows、macOS、Linux 共用原发布、校验和更新流程。
- macOS 自动更新兼容完整 .app ZIP 与旧目录格式；保留游戏、存档和设置。旧 Mac 2.0.2 请先从官网手动下载本次完整应用包。
- 修复蓝牙音箱首次取消静音、悬浮面板背景隔离，并接入联机用户名对应的启动统计。统计与反馈后台属于统一服务，官网、下载站、源站仍独立部署。

macOS 需要 14 或更新系统。本包有 ad-hoc 签名，无 Apple Developer 签名或公证。Linux 需要 Ubuntu 24.04 或兼容环境及图形桌面。平台构建与启动检查不等于所有实体电脑、游戏和整合包已经验证。

旧版 Windows 跨代更新如出现 Qt platform plugin 错误，请从 https://bugg.icu/download/ 手动下载并解压新包，保留原有游戏和 .buggcraft 数据。
