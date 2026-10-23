# Windows 下载与打包

Windows x64 支持完整单文件 `Buggcraft.exe`，以及原有的安装器与 ZIP 分发方式。单文件内置 Python、Qt、QML 和原生联机库，不需要旁边的 ZIP 或另行下载 DLL；首次运行将内置依赖解压至当前用户缓存，再次运行复用校验过的文件。游戏与默认日志仍放在外层 EXE 旁，不能放进解压缓存目录。

安装器与 ZIP 模式首次启动时将运行包下载、校验后放进安装器旁边的 `Buggcraft-runtime\<版本号>`，随后启动真正的应用。安装器目录不可写时才回退到 `%LOCALAPPDATA%\Buggcraft\runtime`，回退原因会写入日志。相同版本只下载一次。新版本使用新的内容哈希目录，旧版本缓存保留，正在运行的文件不会被覆盖。完整包的实际大小见[体积审计](launcher-size-audit.md)，不能用小型安装器的大小代替。

完整包内包含 Python、Qt/PySide6 和 QML 运行组件、Windows C++ 运行库、原生联机库、HTTPS CA 文件及图片资源。联机由 `native` 中的 C++ 库提供 SSH、ICE/DTLS/SCTP，不打包 Python AsyncSSH/aioice/aiortc、PyAV、FFmpeg、音视频编解码器或 pylibsrtp。启动器按 PE 导入和 QML 实际导入结果排除未使用的 Qt 组件，并排除 PDF 图像插件及两份自带字体。

## 构建

完整单文件构建：

```powershell
python build.py --onefile --native-bridge-dir ../minecraft-tunnel-native/runtime --output dist/windows-onefile
```

产物是 `dist/windows-onefile/Buggcraft.exe`；`release.json` 记录大小、SHA-256 和缓存版本。固定版本 Nuitka 的构建插件会在压缩前放入完整原生安装树，并执行与目录版相同的 Qt DLL 裁剪。使用压缩归档格式和按源码/原生文件内容隔离的缓存路径，避免每次重复解压全部文件。[Nuitka 官方单文件与缓存说明](https://nuitka.net/user-documentation/use-cases.html)。升级 Nuitka 时须重新验收插件、完整依赖和启动耗时。

运行 `Buggcraft.exe --startup-check <报告.json>` 可隔离用户配置验证正常首屏并生成截图和内部启动阶段耗时；测试窗口不会抢占焦点。外部计时应从创建进程到报告生成，包含单文件解压/校验；首次空缓存与再次运行分别记录，不将内部 Python 耗时当作完整启动耗时。`--package-check` 另行验证全部页面、原生联机库及诊断导出。

Widgets 和 QML 均使用系统默认字体，保留各控件的字号与粗细。源码已移除不用的字体和重复尺寸图标；保留 Windows ICO 及用于生成 macOS 图标的 1024 像素原图。构建规则仍排除旧工作区可能残留的字体文件。体积基线与后续减重结果见 [启动器体积审计](launcher-size-audit.md)。

Windows 默认设置 `QT_QUICK_BACKEND=software`，由 Qt 自带的二维光栅场景图绘制大厅和好友页，避免为这些二维界面捆绑约 19.7 MiB 的 Mesa `opengl32sw.dll`。它不依赖 GPU，也不改变 Minecraft 游戏自身的渲染。现有 QML 未使用 ShaderEffect 或 3D 效果；以后引入这些功能必须重新评估该规则。二维软件渲染会使用 CPU，显式设置的 `QT_QUICK_BACKEND` 会被保留；选硬件后端时需要系统驱动支持，包内不提供软件 OpenGL 回退。macOS 保持原生默认渲染后端。

`build.py` 在生成运行包前检查依赖清单；若旧构建残留 Python 网络实现、PyAV、SRTP、PDF 或 Windows 软件 OpenGL 文件，会拒绝打包。升级这些裁剪规则后必须重新编译，不能直接对旧 `main.dist` 使用 `--package-only`。原生运行库使用固定的 `minecraft-tunnel-native` 提交构建，打包时传入 `--native-bridge-dir <CMake 安装目录>`，会保留 bin/lib/share、FFI 文件和许可证并生成文件哈希；不要直接传 build 目录或仅复制 DLL。旧数据通道来源记录见[兼容性参考](../../compatibility/legacy_hookup/_rtc/README.md)。

Python 运行时保留 `python311.dll` 及稳定 ABI 的 `python3.dll`，两者都有本机扩展依赖。未使用的多进程、进程池、`_uuid`、通知库及其日志依赖不再打包；UUID4 使用标准库回退，CPU 数查询改用 `os.cpu_count()`。BZIP2/LZMA、XML、SSL 和 Unicode 扩展继续保留以支持游戏安装、Java 解包及网络功能。逐项理由与实测结果见[Python DLL 审计](launcher-size-audit.md#python-dll-专项结论)。

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

检查会实际打开主窗口、大厅和好友页面，运行 ZIP DEFLATE/BZIP2/LZMA、TAR GZ/BZ2/XZ、XML、Decimal、UUID4、ctypes、线程池哈希、TLS 上下文与 CA、原生联机 ABI 初始化和方法清单，以及诊断导出的网络快照、游戏日志和模组清单。该成品自检不等同于跨 NAT 验收；真实原生传输由原生仓库专项测试覆盖。需分别设置 `QT_QPA_PLATFORM=windows` 和 `offscreen` 跑一次。发布前仍需在一台干净的 Windows 10/11 虚拟机上，从临时下载页安装并启动一次。

## 临时下载页

只读 HTTPS 下载服务独立运行在测试端口，静态目录仅开放启动程序、完整运行包、发布清单和首页；没有目录浏览，也不会接入原网站或联机服务。部署脚本位于 `minecraft-tunnel/config/remote-test/deploy_downloads.py`。正式替换下载文件时，必须同步更新发布清单，并用新清单重新构建启动程序。
