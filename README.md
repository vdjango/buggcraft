<div align="center">

# Buggcraft

### Minecraft Java 版启动器与联机大厅

管理游戏实例、安装整合包和内容资源，并与好友加入同一个 Minecraft 世界。

[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-6554c0.svg)](LICENSE)
[![Windows](https://img.shields.io/badge/platform-Windows%20x64-0078D4.svg)](https://github.com/vdjango/buggcraft/releases)
[![macOS](https://img.shields.io/badge/platform-macOS%20Intel%20%7C%20Apple%20Silicon-555555.svg)](https://github.com/vdjango/buggcraft/releases)
[![GitHub release](https://img.shields.io/github/v/release/vdjango/buggcraft)](https://github.com/vdjango/buggcraft/releases/latest)
[![GitHub issues](https://img.shields.io/github/issues/vdjango/buggcraft)](https://github.com/vdjango/buggcraft/issues)

[下载](#下载与安装) · [功能](#功能) · [联机](#通过节点联机) · [开发](#开发与构建) · [项目关系](#项目关系)

</div>

---

Buggcraft 是一个开源的 Minecraft Java 版启动器。它提供游戏版本与实例管理、加载器安装、整合包导入、模组及资源下载，也集成了好友、房间和节点管理功能。联机能力由配套的 [`minecraft-tunnel-native`](https://github.com/vdjango/minecraft-tunnel-native) 原生项目提供。

## 功能

- **管理游戏实例**：安装和启动 Minecraft，管理多个游戏目录与版本，并可同时运行多个实例。
- **安装加载器**：支持 Forge、NeoForge、Fabric、Quilt 及相关 API；安装界面会处理互斥选项。
- **导入整合包**：支持常见 `.zip`、`.mrpack` 包格式。可以从下载页面选择整合包，也可以将文件拖到启动器页面；启动器会显示导入进度，并在依赖准备完成后创建游戏实例。
- **查找和安装内容**：浏览模组、资源包、光影和整合包，查看项目介绍、文件版本及 Minecraft 版本兼容信息。整合包与内容资源使用独立下载源设置。
- **记录安装任务**：下载、校验与安装在任务记录中显示进度、结果和错误详情；失败任务可以继续或重试。
- **管理好友与房间**：添加节点和好友、浏览房间、发送邀请或接受邀请。没有现成房间时，启动器会引导房主创建后再发送邀请。
- **P2P 与中继**：优先尝试玩家间直连；受 NAT 或防火墙限制时可以通过节点中继连接，并可在大厅选择中继模式。
- **导出诊断信息**：收集启动器、游戏、模组和联机网络拓扑相关日志，帮助定位游戏启动或 P2P 连接问题。

## 下载与安装

从 [GitHub Releases](https://github.com/vdjango/buggcraft/releases/latest) 下载正式发行包。Windows 提供 x64 启动器；Linux 提供 x86_64 和 ARM64 单文件程序；macOS 提供 Intel（`x86_64`）与 Apple Silicon（`arm64`）版本。macOS 包是应用 `.app` 的归档，解压后运行应用。

Windows 启动器可作为单个 `Buggcraft.exe` 分发。首次启动时，它会将应用运行时释放到用户缓存，之后复用该缓存；游戏目录默认位于启动器旁边的 `.minecraft`。正式发行包和对应的校验文件请从 Releases 下载，不要把 Windows 启动器误认为完整运行时之外的游戏文件。

源码构建和 GitHub Actions 产物请参阅[打包说明](docs/technical/Windows打包指南.md)、[macOS 打包说明](docs/technical/macOS打包指南.md)和[构建下载说明](docs/technical/GitHub构建.md)。平台构建由 [Package launcher 工作流](https://github.com/vdjango/buggcraft/actions/workflows/package.yml)执行。

## 基本使用

### 安装游戏与整合包

在“下载”页面选择 Minecraft 版本及加载器，按需安装到所选游戏目录。整合包可从目录中查找，也可以直接拖放本地文件；查看进度请前往任务记录。安装整合包时，启动器会下载清单中的必要文件，并创建可启动的游戏实例。

模组、资源包和光影可以按项目或文件浏览。启动器会显示发布者提供的游戏版本信息，兼容性提示用于辅助判断；最终应以所选文件说明和整合包要求为准。下载后可在对应实例的模组、资源包或光影目录中管理内容。

### Java 运行环境

在“设置 → Java 管理”中可以扫描、手动添加或下载 Java。下载使用免安装压缩包，默认优先清华 Adoptium 镜像，并提供 Adoptium 与 Azul 官方来源；运行环境安装到启动器目录内，无需更改系统 Java 或环境变量。

启动游戏时，启动器会检查实例和加载器的 Java 要求，优先使用已配置的兼容版本；缺少合适版本时会显示下载、校验和安装进度，准备完成后继续启动。Minecraft 26.1 起使用 Java 25；安装 Forge 的 1.12.2 及更早实例使用 Java 8。旧整合包的兼容范围也会限制自动选择，避免直接使用过高版本的 Java。

### 通过节点联机

联机节点是玩家发现房间、交换邀请并建立连接的服务。节点不会托管 Minecraft 世界或存档；房主仍在自己的电脑上运行游戏。

1. 在节点网页领取启动器接入码，并在启动器的节点管理中添加节点。启动器接入码是访问凭据，只应添加可信节点提供的代码。
2. 房主启动目标游戏，在 Minecraft 中将世界开放到局域网，然后在启动器联机大厅创建房间。
3. 房主通过好友邀请或房间邀请码邀请朋友。好友接受邀请后，选择相同或兼容的游戏实例并连接启动器提供的地址。
4. 遇到连接问题时，可在大厅选择“仅通过节点中转”；P2P 直连是否可用取决于双方的路由器、NAT 和防火墙环境。

完整操作见[联机与节点使用指南](docs/guides/联机节点使用指南.md)。发生闪退、下载失败或联机异常时，可从大厅导出诊断包。分享前请检查并移除账号接入码、房间密钥等私密信息；诊断包可能包含系统信息、本机路径和网络探测结果。

## 项目关系

| 项目 | 职责 |
| --- | --- |
| [Buggcraft](https://github.com/vdjango/buggcraft) | 桌面启动器、游戏与整合包管理、好友大厅及节点客户端 |
| [minecraft-tunnel-native](https://github.com/vdjango/minecraft-tunnel-native) | C++ 原生网络核心、P2P/中继传输、节点服务与桥接接口 |

启动器通过原生桥接接口连接联机核心。Minecraft 游戏数据的传输由 `minecraft-tunnel-native` 提供的原生运行库处理；节点管理、游戏安装和桌面界面属于 Buggcraft。玩家下载并运行启动器时，不需要另外安装 Python、CMake 或 C++ 编译器。

## 开发与构建

桌面应用使用 Python、Qt for Python（PySide6）和 QML；Minecraft 文件安装与版本管理使用 `minecraft-launcher-lib`。联机传输依赖与启动器版本绑定的 `minecraft-tunnel-native` 原生运行库。Windows 与 macOS 使用独立打包配置，构建入口位于 [`build.py`](build.py) 与 [`build_macos.sh`](build_macos.sh)。

从源码启动界面的基本步骤如下。完整运行和桥接库准备要求请先阅读[第三方桥接接入说明](docs/technical/启动器桥接集成.md)。

```powershell
git clone https://github.com/vdjango/buggcraft.git
cd buggcraft
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe src\buggcraft\main.py
```

执行测试：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
```

构建依赖和发行流程见[Windows 打包](docs/technical/Windows打包指南.md)、[macOS 打包](docs/technical/macOS打包指南.md)及 [GitHub Actions 工作流](.github/workflows/package.yml)。联机核心的单独构建方式见 [`minecraft-tunnel-native` 构建文档](https://github.com/vdjango/minecraft-tunnel-native/blob/main/docs/构建指南.md)。

## 问题反馈与贡献

使用 [GitHub Issues](https://github.com/vdjango/buggcraft/issues) 报告问题时，请说明操作步骤、游戏与加载器版本、系统版本，以及错误发生的大致时间。游戏闪退请附上诊断包中对应实例的游戏日志；联机问题请同时说明当时选择的 P2P 或中继模式。

提交诊断信息前，请检查个人用户名、目录路径及网络信息，并移除密码、访问令牌、节点接入码、房间邀请码和私钥。代码变更请附上与行为相关的测试；原生联机核心的改动应提交到 [`minecraft-tunnel-native`](https://github.com/vdjango/minecraft-tunnel-native)。

## 许可证

Buggcraft 使用 [GNU Affero General Public License v3.0 或更高版本](LICENSE) 发布。使用的第三方组件及其许可条件以仓库中的依赖清单和发行包许可文件为准。

更多项目文档见 [文档索引](docs/文档索引.md)。
