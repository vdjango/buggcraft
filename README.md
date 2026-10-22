# Buggcraft

### Minecraft 启动器，也是一种更轻松的联机方式

管理游戏版本、安装所需文件，在同一个大厅里找到朋友。添加你信任的节点，创建房间并发出邀请；启动器会处理连接路径，网络允许时优先使用 P2P，无法直连时自动使用中继。

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-6554c0.svg)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20primary-343746.svg)](#联机支持范围)
[![Latest release](https://img.shields.io/github/v/release/vdjango/buggcraft?label=release)](https://github.com/vdjango/buggcraft/releases)
[![Issues](https://img.shields.io/github/issues/vdjango/buggcraft)](https://github.com/vdjango/buggcraft/issues)
[![Stars](https://img.shields.io/github/stars/vdjango/buggcraft?style=social)](https://github.com/vdjango/buggcraft)

**[版本下载](https://github.com/vdjango/buggcraft/releases)** · **[开发构建](https://github.com/vdjango/buggcraft/actions/workflows/package.yml)** · **[反馈问题](https://github.com/vdjango/buggcraft/issues)** · **[部署节点](https://github.com/vdjango/minecraft-tunnel)**

---

## 你可以用它做什么

| 游戏管理 | 连接方式 | 一起玩 |
|---|---|---|
| 管理已安装的 Minecraft 版本和游戏实例。 | 使用接入码添加节点，选择房间目录入口。 | 创建公开或邀请码房间，加入朋友的房间。 |
| 下载游戏文件和已支持的加载器。 | 能直连时优先 P2P，必要时使用加密中继。 | 保存本机好友列表，在可信联邦中查找账号。 |
| 加入前查看版本、加载器和模组信息。 | 需要时复制游戏地址，直接在游戏中连接。 | 使用房间聊天；游戏聊天同步状态会明确显示。 |

启动器不会替朋友同步完整游戏安装。玩家仍需准备兼容的 Minecraft 版本、加载器和模组。当前流程和边界见[联机说明](docs/guides/relay-usage.md)。

文档导航：[使用指南、技术说明与验证记录](docs/README.md)。

## 快速开始

最新开发包在 [GitHub Actions → Package launcher](https://github.com/vdjango/buggcraft/actions/workflows/package.yml)：打开最近一次绿色通过的构建，在页面底部 **Artifacts** 下载对应系统的 `Buggcraft-…`。Windows 请解压后保留安装程序和运行包 ZIP 在同一目录。Actions 下载需要登录 GitHub；面向用户的版本包放在 Releases。详见[构建与下载说明](docs/technical/github-builds.md)。

日常使用请从 [Releases](https://github.com/vdjango/buggcraft/releases) 下载构建包。Windows 版本使用小型启动程序，第一次运行时会将校验过的运行时下载到启动程序旁边；完整的 Qt 和 WebRTC 运行时会明显大于启动程序本身。构建或分发前请阅读 [Windows 打包说明](docs/technical/windows-packaging.md)。

游戏默认下载到启动器所在目录的 `.minecraft`。Windows 从 `Buggcraft-Setup.exe` 启动时，位于该入口旁边；直接运行解压后的 `Buggcraft.exe` 时，位于该 EXE 旁边。macOS 位于 `.app` 旁边。已有手动选择的游戏目录继续生效，可以在实例页切换。

从源码运行需要 Python 3.11 或更新版本。项目依赖包含 Qt 和 WebRTC 组件，安装需要一定时间和磁盘空间。

```powershell
git clone https://github.com/vdjango/buggcraft.git
cd buggcraft
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe src\buggcraft\main.py
```

上面是 Windows 命令。Linux 和 macOS 还需要准备对应的 Qt 环境，目前没有完成相同范围的真机验收。联机仅携带数据通道实现，不需要 PyAV、FFmpeg 或音视频编解码器。已验证的行为见[启动器验收记录](docs/validation/launcher-validation.md)。

## 联机流程

1. 在大厅使用节点运营者提供的接入码添加节点。
2. 选择游戏实例，创建房间，或选择已有房间加入。
3. 启动器检查本地游戏信息并准备连接。实际世界、玩家列表、权限和存档仍由 Minecraft 管理。

同一个房间可以混合使用 P2P 和加密中继。直连取决于双方网络和防火墙；部分 NAT 或 UDP 环境必须使用中继，没有节点能保证所有玩家都能直连。节点联邦共享发现和路由信息，不会合并带宽；房间归属节点故障时，正在进行的游戏会话也不会无缝迁移。

遇到联机问题，可退出房间后选择「仅通过节点中转」重新加入。大厅的「导出日志」会打包本次及历史联机记录、网卡与路由快照，便于两端对照；详见[联机测试与日志](docs/guides/network-tester-guide.md)。

账号密码只在节点网页中使用，用于领取临时个人接入码；启动器不会保存节点账号密码。好友列表保存在本机。请只添加你信任的节点和联邦邀请。

## 联机支持范围

启动器的 Windows 流程已有较完整的本地与节点验收记录。Linux 和 macOS 客户端仍需更多真机验证；真实公网 P2P、不同运营商 NAT、超大规模玩家和完整模组组合也不应仅凭本地测试推断。节点失效时，现有游戏会话需要重新连接。

## 项目关系

| 仓库 | 作用 |
|---|---|
| [`buggcraft`](https://github.com/vdjango/buggcraft) | 桌面启动器、大厅和连接组件 |
| [`minecraft-tunnel`](https://github.com/vdjango/minecraft-tunnel) | 自建中继节点、网页管理和联邦服务 |

节点首页提供启动器接入文档、各语言示例和完整协议参考；启动器侧流程见[联机说明](docs/guides/relay-usage.md)。

## 开发与验证

应用代码位于 `src/buggcraft`，启动器测试位于 `tests/`。安装依赖后，可在仓库根目录运行单个测试模块：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_visibility -v
```

完整测试和网络验收记录见[启动器验收记录](docs/validation/launcher-validation.md)、[联机验证记录](docs/validation/multiplayer-validation.md)和[联机路线图](docs/planning/multiplayer-roadmap.md)。单元测试、本地游戏服务端和不同公网中的真实客户端属于不同验证层级，文档会标明实际执行的范围。

联机使用从 aiortc 1.15.0 裁出的数据通道子集，保留上游 ICE、DTLS、SCTP 和证书指纹检查；来源、许可和更新方法见[子集说明](src/buggcraft/hookup/_rtc/README.md)。新旧客户端互通测试可在独立开发环境额外安装 `requirements-interop.txt` 后运行 `python -m unittest tests.test_datachannel_transport -v`。该文件里的音视频依赖只供旧客户端测试，不用于发布构建。

使用 `build.bat` 构建 Windows 运行包，macOS 使用 `bash build_macos.sh`。GitHub Actions 的「Package launcher」会分别生成 Windows x64、macOS Intel 和 Apple Silicon 产物，并执行运行包检查。[Windows 打包说明](docs/technical/windows-packaging.md)和 [macOS 打包说明](docs/technical/macos-packaging.md)记录了 Qt 裁剪、运行检查与签名边界。

## 第三方启动器桥接

独立的 [Buggcraft bridge](https://github.com/vdjango/buggcraft/actions/workflows/bridge.yml) 通过本地 JSON-RPC 2.0 管道接入联机节点，负责 P2P 与中转，无需接入方安装 Python 或集成 Python SDK。Windows、Linux 和 macOS 分别构建；下载后保留完整发行目录。接口、限制及打包验收见[桥接接入说明](docs/technical/bridge-integration.md)。

## 参与贡献

小而明确的改动更容易审查。行为变化请附测试，并同步更新使用说明或验收记录。不要提交本地游戏文件、包含接入码的日志、凭据或私有节点配置。参与前请阅读[行为准则](CODE_OF_CONDUCT.md)。

## 资源赞助

**本项目不接受资金赞助，接受服务器、云主机、带宽、流量额度、对象存储及 CDN 等云上资源赞助。** 资源用于公共节点、文件分发和兼容性验证。可先在 [Issues](https://github.com/vdjango/buggcraft/issues) 沟通资源类型与使用条件，请勿公开密码或密钥。详见[社区贡献与资源赞助](COMMUNITY_LICENSE.md)。

## 许可

源代码使用 [GNU AGPL v3](LICENSE) 发布。[社区贡献与资源赞助](COMMUNITY_LICENSE.md)说明参与方式，不增加许可限制。

---

<p align="center"><sub>为那些服务器很远、朋友仍想在同一个世界里的时刻而开源。</sub></p>
