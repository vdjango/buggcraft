# GitHub 构建与下载

## 下载最新开发包

打开 [Package launcher](https://github.com/vdjango/buggcraft/actions/workflows/package.yml)，选择最近一次绿色通过的运行，在页面底部 **Artifacts** 下载对应系统的 `Buggcraft-…` 文件。下载 Actions 产物需要登录 GitHub；开发包保留 30 天。

| 系统 | 产物名称包含 | 使用方式 |
|---|---|---|
| Windows 10/11 x64 | `windows-x64` | 解压 Actions 产物，运行独立文件 `Buggcraft.exe`。 |
| Linux x86_64 | `linux-x86_64` | 下载 `Buggcraft` 并赋予可执行权限后运行。 |
| Linux ARM64 | `linux-arm64` | 下载 `Buggcraft-linux-arm64` 并赋予可执行权限后运行。 |
| macOS Intel | `macos-x86_64` | 解压产物，再解压其中的应用 ZIP。 |
| macOS Apple Silicon | `macos-arm64` | 解压产物，再解压其中的应用 ZIP。 |

Windows 和 Linux 使用独立可执行文件，macOS 使用包含应用的 ZIP。`build-diagnostics-…` 是排查构建失败的日志，不是应用下载。

## 手动构建

在上述 Actions 页面点击 **Run workflow**，选择分支并运行。推送到 `main` 的应用、资源、打包依赖或构建配置变更也会触发构建。Windows x64、macOS Intel 和 Apple Silicon 分别使用对应系统的 GitHub 托管构建机。

编译后先执行隔离运行检查，实际加载界面和通信依赖，再校验压缩包大小及 SHA-256。只有检查通过才上传应用产物；失败时保留构建日志 14 天。

## 版本发布

修复先在独立 `release/*` 分支完成，通过五平台 `Package launcher` 和 Windows/Linux 的 `Client and native regression`，再合入 main。main 的同一提交再次通过这两套工作流后，运行 `Release launcher build`，手动输入已经确定的版本号。发布校验会拒绝缺失、未完成、失败、取消、跳过或其他提交的结果；不要直接推送标签绕过验证。

版本构建覆盖 Windows x64、Linux x86_64/ARM64、macOS Intel/Apple Silicon。全部检查通过后，在 GitHub 创建草稿并自动同步到[下载站](https://download.bugg.icu)。核对五个平台的文件、内嵌版本、大小和 SHA-256 后，在下载站后台审核发布；GitHub 草稿与下载站发布状态分别管理。

若版本已生成草稿但同步失败，重跑失败的同步任务。不要重用或移动已发布的标签；功能修复使用明确的新版本号。完整操作与失败处理见[固定发布流程](../guides/启动器发布检查清单.md)。

目前 Windows 未配置受信任代码签名，macOS 使用 ad-hoc 签名且未经 Apple 公证。CI 成功不代表系统会放行，也不替代干净设备上的安装验收。具体边界见 [Windows 打包](Windows打包指南.md)和 [macOS 打包](macOS打包指南.md)。
