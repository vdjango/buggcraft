# GitHub 构建与下载

## 下载最新开发包

打开 [Package launcher](https://github.com/vdjango/buggcraft/actions/workflows/package.yml)，选择最近一次绿色通过的运行，在页面底部 **Artifacts** 下载对应系统的 `Buggcraft-…` 文件。下载 Actions 产物需要登录 GitHub；开发包保留 30 天。

| 系统 | 产物名称包含 | 使用方式 |
|---|---|---|
| Windows 10/11 x64 | `windows-x64` | 解压 Actions 下载的文件，保留 `Buggcraft-Setup.exe` 与运行包 ZIP 在同一目录，再运行安装程序。 |
| Linux x86_64 | `linux-x86_64` | 下载 `Buggcraft` 并赋予可执行权限后运行。 |
| Linux ARM64 | `linux-arm64` | 下载 `Buggcraft-linux-arm64` 并赋予可执行权限后运行。 |
| macOS Intel | `macos-x86_64` | 解压产物，再解压其中的应用 ZIP。 |
| macOS Apple Silicon | `macos-arm64` | 解压产物，再解压其中的应用 ZIP。 |

分支构建的 Windows 安装程序使用同目录 ZIP，不内置会变动的“最新运行包”地址。程序会校验完整包和文件哈希，将运行环境安装在程序旁边。`build-diagnostics-…` 是排查构建失败的日志，不是应用下载。

## 手动构建

在上述 Actions 页面点击 **Run workflow**，选择分支并运行。推送到 `main` 的应用、资源、打包依赖或构建配置变更也会触发构建。Windows x64、macOS Intel 和 Apple Silicon 分别使用对应系统的 GitHub 托管构建机。

编译后先执行隔离运行检查，实际加载界面和通信依赖，再校验压缩包大小及 SHA-256。只有检查通过才上传应用产物；失败时保留构建日志 14 天。

## 版本发布

维护者确认版本号和提交后，推送形如 `v1.2.3` 的新标签。CI 构建并检查全部三个平台，通过后在 [Releases](https://github.com/vdjango/buggcraft/releases) 创建一个**草稿**，附上应用包、平台独立的清单与 SHA-256、对应提交的源码快照和许可证。

标签构建的 Windows 安装程序内置该标签下的运行包地址，公开 Release 后可单独下载安装程序并联网安装。不得将安装程序与其他版本的运行包混用；草稿阶段的下载地址尚未向普通用户开放，可先用同目录 ZIP 验收。

发布者检查安装、签名状态和说明后，在 GitHub 点击 **Publish release**。公开仓库的 Release 下载无需登录 GitHub。不要重用或移动已发布的标签；修复后使用新版本号，避免已下载的安装程序对应到不同文件。

目前 Windows 未配置受信任代码签名，macOS 使用 ad-hoc 签名且未经 Apple 公证。CI 成功不代表系统会放行，也不替代干净设备上的安装验收。具体边界见 [Windows 打包](windows-packaging.md)和 [macOS 打包](macos-packaging.md)。
