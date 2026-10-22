# Windows 下载与打包

Windows x64 发布分成小型启动程序和完整运行包。`Buggcraft-Setup.exe` 约 363 KB；首次启动时下载约 106.5 MB 的运行包，将文件校验后放进安装器旁边的 `Buggcraft-runtime\<版本号>`，随后启动真正的应用。安装器目录不可写时才回退到 `%LOCALAPPDATA%\Buggcraft\runtime`，回退原因会写入日志。相同版本只下载一次。新版本使用新的内容哈希目录，旧版本缓存保留，正在运行的文件不会被覆盖。

完整包内包含 Python、Qt/PySide6 和 QML 运行组件、Windows C++ 运行库、WebRTC/FFmpeg 组件、HTTPS CA 文件及应用资源。启动器按 PE 导入和 QML 实际导入结果排除了未使用的 Qt 组件。当前完整 ZIP 约 106.5 MB，解压后约 267 MB；Qt GUI 和 WebRTC 的完整依赖无法压到 10 MB，10 MB 以下适合的是首次下载用的小型启动程序。

## 构建

Qt 官方的 [`pyside6-deploy`](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html) 同样基于 Nuitka，支持排除未使用的 QML 插件。当前构建保留既有 Nuitka 流程，使用 Qt 官方 `qmlimportscanner` 计算 QML 依赖，再跟踪 PE 导入裁剪未引用的 Qt DLL；不会排除界面必需的 QtCore、QtGui、QtQuick 等库。Windows `windeployqt` 主要处理 Qt 原生依赖，不能单独打包 Python 和 WebRTC。macOS 流程见 [macOS 打包说明](macos-packaging.md)。

构建机需 Windows x64、Python 3.11 x64，以及 Visual Studio 2022 C++ Build Tools。`build.bat` 会在 `.build-venv` 建独立环境、安装固定版本的打包工具并执行 `pip check`。完整依赖较多，首次构建需要下载 Python 包和 Qt 组件。

离线构建：

```bat
build.bat
```

离线构建会同时生成完整 ZIP 和小型启动程序；将 ZIP 放在启动程序旁即可离线安装。配置 HTTPS 下载地址后再为联网用户构建：

```bat
build.bat --runtime-url https://下载域名/{version}/Buggcraft-runtime-windows-x64.zip --certificate-pin 下载域名:443=证书SHA256指纹
```

正式发布必须配置受信任的 Authenticode 代码签名证书：

```powershell
$env:BUGGCRAFT_SIGN_PASSWORD = '证书密码'
python build.py --sign-certificate .\publisher.pfx --timestamp-url https://时间戳服务 --require-signature
```

构建会签名运行包里的 PE 文件和 `Buggcraft-Setup.exe`，再执行签名验证；没有证书或验证失败时，`--require-signature` 会终止构建，发布脚本也会拒绝未签名版本。`BUGGCRAFT_SIGN_PASSWORD` 不要写入仓库或发布包。

也支持 Windows 证书存储区中的代码签名证书，包括由硬件令牌提供私钥的证书。使用 `certmgr.msc` 查询证书 SHA-1 指纹，在能够使用私钥的签名机运行：

```powershell
python build.py --sign-thumbprint <40位证书SHA1指纹> --timestamp-url https://时间戳服务 --require-signature
```

如果证书在本机计算机而非当前用户的 `My` 存储区，附加 `--sign-machine-store`。签名后会校验每个签名，并记录签名文件与发布清单的 SHA-256；发布脚本会核对实际文件没有被重新打包或替换。不要把 PFX 密码、私钥或云签名凭据放到下载服务器上。当前没有可用的受信任代码签名证书，因此正式签名仍未完成。

临时下载服务允许用 `BUGGCRAFT_ALLOW_UNSIGNED_TEST_RELEASE=1` 明确发布未签名测试包；下载页必须说明签名状态。这只用于现有独立测试端口，正式发布不能使用此例外。

运行包地址、证书指纹、压缩包哈希及每个文件的哈希都编入该版本的启动程序。下载地址只接受 HTTPS。临时服务器使用自签名证书，因此启动程序固定校验证书指纹；正式发布前应换成域名和受信任的 TLS 证书，再重新构建启动程序。现在生成的 Windows 程序尚未做 Authenticode 签名，Windows 可能显示发布者未知提示。

## 验证

`tests/test_windows_packaging.py` 使用真实 .NET Framework 编译器构建启动程序，测试离线安装、版本缓存、缓存损坏修复、压缩包和单文件哈希、目录穿越拒绝、签名要求及 ZIP 可重复构建。

SmartScreen 信誉提示与 Smart App Control 强制拦截是两种情况。签名证书能提供发布者身份，但新证书/新文件仍可能收到 SmartScreen 信誉警告；签名不能保证提示立即消失。没有可用签名证书时不能把包标成已签名，也不应要求用户关闭系统防护。`build.py --require-signature` 和发布脚本会拒绝未签名版本。

完整运行包的隔离检查可从不含 Python 的 PATH 调用：

```powershell
$env:PYTHONPATH = ''
$env:PYTHONHOME = ''
$env:PATH = "$env:WINDIR\System32"
& .\dist\main.dist\Buggcraft.exe --package-check .\package-check.json
```

检查会实际打开主窗口、大厅和好友页面，运行 SSH 签名、AES-GCM、TLS CA、WebRTC DTLS 证书及 64 KiB 本地数据通道传输。发布前仍需在一台干净的 Windows 10/11 虚拟机上，从临时下载页安装并启动一次。

## 临时下载页

只读 HTTPS 下载服务独立运行在测试端口，静态目录仅开放启动程序、完整运行包、发布清单和首页；没有目录浏览，也不会接入原网站或联机服务。部署脚本位于 `minecraft-tunnel/config/remote-test/deploy_downloads.py`。正式替换下载文件时，必须同步更新发布清单，并用新清单重新构建启动程序。
