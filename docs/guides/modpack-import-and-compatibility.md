# 游戏与整合包导入、内容下载和加载器兼容

## 已有游戏目录导入

在「实例 → 版本列表」右侧标题栏点击「导入游戏」，选择已有的 `.minecraft` 游戏目录，即可添加到启动器并扫描已安装版本。该入口与首次启动提示中的「导入游戏」使用同一流程，之后也能随时打开；左侧「添加游戏文件夹」入口继续可用。目录直接登记使用，游戏文件无需复制。

## 整合包导入入口

可从「实例 → 版本列表」右侧的实例列表标题栏点击「导入整合包」；「游戏下载」页和安装新游戏窗口也保留入口。导入会在所选 Minecraft 游戏目录下创建一个新的独立实例，不会覆盖当前实例。
选择 ZIP 后检查预览中的 Minecraft、加载器、清单版本、下载条目和建议内存，填写新实例名称后开始导入。
进度、取消、日志和失败重试统一放在「下载记录」。已完成的导入禁止直接重新安装，避免覆盖存档；需要另一个副本时用新名称再次导入。

当前支持 **CurseForge manifestVersion 1**：ZIP 根目录含 `manifest.json`，配置和内置模组来自清单指定的 `overrides` 目录。
不把普通游戏目录压缩包、HMCL/MMC 专有包或 Modrinth `.mrpack` 当成 CurseForge 包处理。

## 模组、资源包、光影和整合包下载

「游戏下载」页的「模组」「资源包」「光影包」标签会打开 Modrinth 搜索窗口。搜索和版本查询在后台执行，不阻塞启动器界面；当前实例的 Minecraft 版本用于筛选，加载器条件只用于模组和整合包。选中项目后再选具体版本，任务进入「下载记录」，校验 SHA-1/SHA-512 与文件长度后安装到实例的 `mods`、`resourcepacks` 和 `shaderpacks` 目录。资源包与光影不按 Forge/Fabric 过滤。

模组的传递依赖不会自动解析，已安装的旧版模组也不会自动替换；请按项目说明补齐依赖并自行移除冲突版本。光影文件会放入 `shaderpacks`，启动游戏还需要兼容的 Iris、Oculus 等渲染模组。

「整合包」类型也可以从同一搜索窗口下载，不要求先选 Minecraft 实例。它会把 Modrinth `.mrpack` 文件保存到配置目录的 `downloads/modpacks` 子目录，并显示在下载记录中。当前整合包导入器只解析 CurseForge manifestVersion 1，因此 `.mrpack` 目前只能下载保存，不能通过此导入入口安装；启动器不会把下载文件误标成已安装的游戏实例。
加载器支持 Forge、NeoForge、Fabric、Quilt；同一清单有多个加载器时直接拒绝，即使其中一个标记为非 primary。

## CurseForge 下载授权

未内置的文件通过 [CurseForge 官方 API](https://docs.curseforge.com/rest-api/) 批量解析精确的 `projectID` / `fileID`，按服务返回的文件大小与 SHA-1 校验。
支持模组、资源包和光影包，分别放入 `mods`、`resourcepacks`、`shaderpacks`；清单中包括非 required 的条目也一并安装，保持作者导出的完整集合。

导入窗口可输入 API 密钥，也可在启动启动器前设置环境变量 `BUGGCRAFT_CURSEFORGE_API_KEY`。
密钥不写入设置、下载历史、实例元数据或 URL；下载时只通过请求头发送，跨出官方 CDN 的重定向会移除该头。
本次启动期间重试复用内存中的密钥，重启启动器后需重新输入或通过环境变量提供。

[CurseForge 官方下载鉴权说明](https://blog.curseforge.com/introducing-api-key-authentication-for-curseforge-file-downloads/) 指定 API/CDN 使用 `x-api-key`。
密钥缺失、无效、文件被删除、作者未开放自动分发或缺少校验数据时，明确失败并保留日志，不使用猜测 CDN 地址，也不把缺失模组的实例标成成功。
遇到作者限制分发的文件，需从作者或官方客户端获取完整包；当前没有自动跳过文件或等待手工补齐的流程。

## 实例、缓存与失败处理

- 最终目录：当前 Minecraft 根目录下 `versions/<新实例名称>/`。包内的 mods、config、资源等都在这里，始终使用独立游戏目录，即使全局设置关闭隔离。
- 游戏本体、资源和加载器依赖复用根目录下的共享安装。整合包实例继承已安装的正确加载器版本，并保留原游戏 JAR 和本机库路径。
- 下载缓存：`.buggcraft-downloads/modpacks/<ZIP的SHA256>/files/`。重试重新校验并复用完整文件，损坏文件重新下载。
- 全部下载、解压和加载器安装成功后，再发布最终实例目录。取消或失败时清理临时实例，不改动已有实例的 mods/config/存档；已下载缓存与共享游戏安装保留。
- 不覆盖同名实例。拒绝路径穿越、绝对路径、Windows 特殊文件名、符号链接、加密条目及大小写重复路径。最多 50000 个 ZIP 条目，展开后最多 8 GiB。
- `buggcraft-modpack.json` 保存来源名称、清单版本、Minecraft、加载器、ZIP 哈希和建议内存，方便追溯；建议内存仅展示，不自动覆盖用户的内存设置。

## 互斥结果（按提供的截图实现）

「允许」表示不被当前加载器互斥规则阻止，不代表任意版本都能一起运行。

| 已选加载器 | Forge | NeoForge | OptiFine | Fabric | Fabric API | Quilt | QSL/QFAPI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Forge | 当前选择 | 互斥 | 允许，须核对具体版本 | 互斥 | 互斥 | 互斥 | 互斥 |
| NeoForge | 互斥 | 当前选择 | 互斥 | 互斥 | 互斥 | 互斥 | 互斥 |
| Fabric | 互斥 | 互斥 | 互斥 | 当前选择 | 允许 | 互斥 | 互斥 |
| Quilt | 互斥 | 互斥 | 互斥 | 互斥 | 允许，须核对具体版本 | 当前选择 | 允许 |

选择加载器版本后，不兼容卡片立即禁用，并显示「与 Forge 不兼容」等具体原因。
选中加载器的卡片可点击更换版本；点击「移除 Forge」等按钮后恢复其他加载器选择。
仅浏览列表或取消返回不会改变已经选定的版本。切换 Minecraft 版本时清空所有选择，旧异步列表响应失效。

Fabric API 和 QSL/QFAPI 是模组；可以在内容下载窗口中搜索并下载，或随 CurseForge 整合包清单导入。安装向导的组件卡片只负责展示互斥状态，不直接提供这些 API 的安装按钮。
OptiFine 保留需官方安装器的提示，当前向导不自动安装。Forge 与 OptiFine 的实际可用性应逐版本核对，本矩阵不自动授权或保证该组合。
规则实现位于 `src/buggcraft/core/loader_rules.py`，清单导入与安装向导共用。

## 提供的 ZIP 检查结果与验证边界

`终焉决斗NW公测版-0.9.1-客户端.zip`：

| 项目 | 读取结果 |
| --- | --- |
| 格式 | CurseForge，manifestVersion 1 |
| Minecraft | 1.20.1 |
| 加载器 | Forge 47.4.0 |
| 清单包版本 | **0.9.0**，与 ZIP 文件名中的 0.9.1 不同，按清单安装，不擅自改写 |
| 下载条目 | 244 |
| ZIP 条目 | 4481 |
| 展开大小 | 671428312 字节，约 640.3 MiB，另需模组与游戏依赖下载空间 |
| 建议内存 | 8192 MiB |
| 名称 | 清单名称已有乱码/替换字符；新实例名称默认采用 ZIP 文件名，可编辑 |

已用该实际 ZIP 验证结构解析与界面预览。自动化测试使用真实本地 HTTP 传输验证校验/缓存复用、失败重试与最终实例发布，并覆盖取消清理、已有实例保护、危险 ZIP、互斥清单、API 返回校验、下载密钥重定向和全局关闭隔离时的导入实例行为。
未提供有效 CurseForge API 密钥，因此未声称完成此包 244 个在线条目的全量下载，也未进行该整合包的实际进游戏验证。

运行相关回归：

```powershell
python -m unittest tests.test_modpack_import tests.test_modpack_settings tests.test_loader_selection tests.test_download_worker tests.test_download_transport tests.test_loader_catalogue tests.test_content_download tests.test_content_dialog
```
