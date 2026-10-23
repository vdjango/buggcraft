# BMCLAPI 下载源接入说明

本文把项目内的下载源选择与用户提供的 BMCLAPI API 文档 `0.0.0` 对照，供维护和排查使用。原始参考文件位于工作区外层的 `docs/apiDoc_ BMCLAPI - 0.0.0.pdf`；官方在线文档见 [bmclapidoc.bangbang93.com](https://bmclapidoc.bangbang93.com/)。接口以 Mojang、Forge 和各加载器源站的官方元数据格式为基础；BMCLAPI 主要提供兼容路径或版本查询接口。

## Minecraft 文件路径

`settings.general.mirrors` 是下载源设置。对应实现位于 `src/buggcraft/core/downloads.py` 的 `MinecraftDownloader.urls()`。

| 用途 | 官方地址/主机 | BMCLAPI 地址规则 | 当前接入 |
|---|---|---|---|
| 游戏版本清单 | `launchermeta.mojang.com/mc/game/version_manifest_v2.json` | `bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` | 已接入；读取 `versions` 后按版本 ID 安装 |
| 版本 JSON、资源索引、Java 元数据 | Mojang 元数据主机返回的 URL | 保留路径并替换为 `https://bmclapi2.bangbang93.com` | 已接入；路径规则覆盖 `launchermeta`、`piston-meta`、`launcher`、`piston-data` |
| 游戏客户端与服务端文件 | 版本 JSON 内的下载 URL | 由元数据主机路径映射；不自行拼接版本文件名 | 客户端安装已接入；此页不代表服务端安装器已实现 |
| Assets 对象 | `resources.download.minecraft.net/<前两位>/<sha1>` | `https://bmclapi2.bangbang93.com/assets/<前两位>/<sha1>` | 已接入；按 SHA-1 和长度校验 |
| Minecraft / Forge / Fabric 等 Maven 文件 | `libraries.minecraft.net` 及加载器 Maven 源 | `https://bmclapi2.bangbang93.com/maven/<原始路径>` | 已接入 Minecraft 库和所支持加载器安装下载 |

安装器从清单取得版本 JSON，再依照该 JSON 下载客户端、适用平台的库、日志配置和 Assets。下载文件先写临时文件；上游提供 SHA-1 时进行哈希校验，上游提供文件长度时核对长度，否则使用响应的 `Content-Length`，校验后才替换目标。版本 JSON 和完整性收据在必需文件成功后发布。失败会重试并留下可读错误，取消不会把部分文件记为已完成。具有长度及哈希的文件在同一任务重试时支持 HTTP Range 续传；范围不符时重下，校验后才发布。

## 加载器查询与安装

实现位于 `src/buggcraft/core/loaders.py`。`minecraft-launcher-lib` 的下载函数在安装期间临时路由到设置源，结束后恢复原函数。

| 加载器 | 版本查询 | 安装器/依赖来源 | 说明 |
|---|---|---|---|
| Forge | 官方 Maven 元数据，或 BMCLAPI `/forge/minecraft/<minecraft-version>` JSON | Forge Maven `/maven` 路径 | BMCLAPI API 的版本列表格式不是 Maven XML，代码按来源分别解析 |
| Fabric | `meta.fabricmc.net/v2/versions/loader/<minecraft-version>`；镜像为 `/fabric-meta/v2/...` | Fabric Maven 及可镜像的 Minecraft 文件 | 实际安装由 `minecraft-launcher-lib` 执行 |
| Quilt | `meta.quiltmc.org/v3/versions/loader/<minecraft-version>`；镜像为 `/quilt-meta/v3/...` | Quilt Maven 及可镜像的 Minecraft 文件 | 随附 `0.0.0` 文档提示 Quilt 上游 API 曾有问题；镜像可用性需按实际网络复测 |
| NeoForge | 官方 Maven 元数据，或 BMCLAPI `/maven/net/neoforged/neoforge/maven-metadata.xml` | NeoForge Installer Maven 路径 | 安装器以 Java 子进程运行并检查退出码及生成的版本 JSON |
| OptiFine | 文档列有 `/optifine/<minecraft-version>/<type>/<patch>` 重定向下载接口 | 未接入 | 启动器控件明确禁用并说明需要官方交互式安装器；不可视为已支持 |

显式选择“官方”时，加载器版本查询与 Maven 文件只用官方源。显式选择“BMCLAPI”时，加载器查询/安装器使用对应 BMCLAPI 路径；基础 Minecraft 下载先尝试 BMCLAPI，再以官方 URL 兜底。选择“自动”时优先官方，失败后尝试 BMCLAPI。当前没有自动测速或最低延迟节点选择。

## 来源显示与验证边界

BMCLAPI 文档要求在下载界面或其他可见区域标明来源。启动器的通用设置页提供“官方 / BMCLAPI / 自动”下载源选择，并解释自动回退规则。下载任务记录文件名、主机和尝试次数，应用日志记录最终命中主机及实际大小。资源和整合包文件在非“官方”模式下优先使用 MCIM，映射和失败回退详见[整合包与资源下载](../guides/modpack-import-and-compatibility.md)。

`multiplayer-tests/test_loaders.py` 对镜像路由和失败回退做离线模拟；`multiplayer-tests/test_downloads.py` 使用本地 HTTP 服务验证 SHA-1、长度、重试、损坏响应和安装发布。测试不能证明 BMCLAPI 当前在线、区域速度、配额或所有加载器安装器的实时兼容性。Forge/Fabric/Quilt/NeoForge 的真实联网版本查询与安装尚未在当前受限环境完成，应在允许外网的 Windows/macOS/Linux 网络中分别验收。

## 维护规则

- 新增来源映射前，先确认它是否保留上游目录结构；若 API 返回独立 JSON 格式，应单独解析，不要当 Maven 元数据处理。
- 下载使用上游提供的 SHA-1 和文件长度；没有上游哈希时不能把 HTTP 成功当作完整性证明。
- 源站超时或镜像返回错误时，任务必须显示失败原因，保留已验证文件并允许重试。
- 更新 API 路径前同时检查随附 PDF 与官方在线文档，并为查询、优先级和失败回退增加测试。
