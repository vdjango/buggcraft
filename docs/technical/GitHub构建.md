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

构建前先完成单元预检与各平台的原生桥接检查；编译完成后只校验产物版本、大小和 SHA-256 并上传，失败时保留构建日志 14 天。

## 版本发布

日常推送或 PR 只运行一条 Package launcher 工作流：Ubuntu 先完成静态校验和启动器单元回归，再并行执行五个平台的原生桥接检查与打包。联机节点固定到已发布版本；Windows、Linux x86_64 与两种 macOS 直接下载对应仓库的已验证发布包并核对 SHA-256 和源码提交，Linux ARM64 暂由固定提交编译。每个平台还缓存该固定版本的运行库，后续构建无需重复编译。网络下载、完整页面和深入协议回归通过手动触发 Client and native regression，不阻塞常规发布。

修复在独立 release/* 分支完成后合入 main。同一提交的 Package launcher 预检和五平台构建通过，再运行 Release launcher build 并输入版本号。发布校验拒绝缺失、未完成、失败、取消、跳过或其他提交的结果；标签工作流直接下载该 main 构建的五平台产物，校验源码内版本与标签一致，再创建发行草稿，不重复编译启动器。

版本构建覆盖 Windows x64、Linux x86_64/ARM64、macOS Intel/Apple Silicon。全部检查通过后，在 GitHub 创建草稿并自动同步到[下载站](https://download.bugg.icu)。核对五个平台的文件、内嵌版本、大小和 SHA-256 后，在下载站后台审核发布；GitHub 草稿与下载站发布状态分别管理。

若版本已生成草稿但同步失败，重跑失败的同步任务。不要重用或移动已发布的标签；功能修复使用明确的新版本号。完整操作与失败处理见[固定发布流程](../guides/启动器发布检查清单.md)。

目前 Windows 未配置受信任代码签名，macOS 使用 ad-hoc 签名且未经 Apple 公证。CI 成功不代表系统会放行，也不替代干净设备上的安装验收。具体边界见 [Windows 打包](Windows打包指南.md)和 [macOS 打包](macOS打包指南.md)。
