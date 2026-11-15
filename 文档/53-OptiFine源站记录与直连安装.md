# OptiFine 源站记录与直连安装

2026-11-13。复用 ContentProvider 的光影核心选择、GameOperations 的内容安装事务、ResourceClient 的下载和 DependencyFacts 的实际 JAR 检查，不新增独立安装器或 Python 运行依赖。

- ContentProvider 在 Forge 目标获取 OptiFine 清单：BUGG 启用时先查 `/v1/catalog/optifine/versions`，缺失/失败回退 BMCLAPI。按精确 Minecraft 和 BMCLAPI 声明的 Forge 构建过滤；保留所有兼容发布，沿原 choices 让用户选择。空 Forge/N/A 不推断为 Forge 支持，其他加载器不混入。
- 计划的 shaderSupport 保存 OptiFine 原始版本证据和固定上游下载地址；目录阶段不下载安装包、不伪造文件摘要。安装 worker 下载并校验归档及 OptiFine 标记，记录实际大小/SHA-1/SHA-256，再走现有内容记录、冲突检查、依赖检查及原子提交。预检查不下载核心，正式安装才物化文件。
- 文件只从 BMCLAPI 直连下载；源站是版本目录和依赖约束入口，不缓存 OptiFine 安装包。本地安装回执允许后续安装光影时复用同一核心；未知或不同核心不自动叠加。
- 取消和异常沿现有 worker/ResourceClient 传播；无 GUI I/O。文件信任来自 HTTPS 上游，本地摘要用于后续完整性，不冒称发布者校验值。

验证：源站优先、旧字段兼容、未命中回退、多个核心发布选择、精确 Forge 构建拒绝、单次下载/事务暂存复用、再次安装复用已核验核心均通过。真实 1.21.1 HD_U J1 安装包（7,322,249 字节、SHA-256 db6d2d14db0009bdea2d8f848e5cb55aac52b555e8e50506dbf7876755b79082）在 Forge 52.0.16 目标通过实际 JAR 依赖检查和安装事务。410/960 界面截图已实际查看，QML 格式化、qmllint 与组件边界检查通过；固定入口 build/bugg.exe 更新。

本次为 Forge 光影核心安装；OptiFine 独立原版配置生成不在本次实现内。未知第三方手工安装的核心仍须先核验，不能绕过已有核心冲突保护。没有运行所有版本的游戏渲染；安装测试不代表光影实际生效。源站部署和译文域名旧 CDN 缓存限制见源站第 53 号；默认 mirror.bugg.icu 的目录与直连已验证。

## 2026-11-14 光影安装修复

OptiFine 源站缓存/转发由服务端配置决定，当前安装阶段已不再强制直连。最新修复见第 54 号文档。
