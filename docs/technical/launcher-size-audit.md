# 启动器体积审计与减重方案

审计日期：2026-10-22。目标是减少完整启动器的下载和安装体积，保留跨平台能力；小安装器下载大运行包不能算完成减重。

实施更新：已完成系统字体替换、DataChannel 按需子集、PDF/Mesa 排除及 Python 可选依赖裁剪。完整启动器仍自带必需运行组件，不依赖玩家安装 Python，也不会在首次启动时补下载一大套 Qt/字体依赖。

## 当前减重版本

2026-10-22 的 Windows x64 成品位于 `dist/datachannel-slim/`。最终 ZIP 的字节数、SHA-256 和测试记录以本节最终复核值为准；下方“系统字体版本”及“初次审计”均为保留的历史对照。

| 项目 | 最初完整包 | 本轮最终构建 | 减少 |
| --- | ---: | ---: | ---: |
| 完整 ZIP 字节数 | 106,646,508 | 53,159,076 | 53,487,432（50.15%） |
| 完整 ZIP MiB | 101.71 | 50.70 | 51.01 |
| 解压字节数 | 267,725,323 | 142,129,549 | 125,595,774（46.91%） |
| 解压 MiB | 255.32 | 135.54 | 119.78 |
| 文件数 | 355 | 269 | 86 |

最终 ZIP SHA-256：`6758cd4951497cdb6a17d5cdd9d7bd8425f7fcc09e4b9e76f623cc60145f222a`。269 个文件的大小和 SHA-256 均与 `release.json` 一致，ZIP CRC 校验通过；确认没有字体、PyAV/FFmpeg/SRTP、PDF、Mesa、`_multiprocessing.pyd` 或 `_uuid.pyd`。逐文件清单在 `dist/datachannel-slim/size-audit/`；Python DLL 的 PE 导入记录在 `python-runtime-audit.json`，证明 EXE/扩展共有 19 项引用 `python311.dll`、11 项引用 `python3.dll`。

**最终 EXE 两种平台检查均通过：**`dist/datachannel-slim/validation.json` 绑定上述最终 ZIP 的哈希，Windows/offscreen 均生成新的 14 项通过报告。在 PATH 仅有 Windows 系统目录、清除 Python/Qt 外部插件路径的条件下，完成实际 GUI、归档/线程/TLS 和加密数据通道检查。

源码回归中：打包 32 项（1 项应用控制拦截而跳过）、GUI 63 项、游戏/下载/整合包 30 项、传输/运行时 17 项、房间/网络 39 项（1 项公网跳过）均成功；修复后的房间权限/聊天重复 13 项（1 项公网跳过）亦成功。最后的数据通道/关闭/库存 14 项通过，关闭专项共 5 项通过。通道编号防护加入后，最新 peer/关闭/新旧互通 **19 项全部通过（75.903 秒）**，记录在 `transport-release-validated.log`。

**联机压力验证及修正：**重测 peer/关闭 11 项时，2 MiB 并发直连一度触发 SCTP 重复 DataChannel OPEN 断言并超时；其余 10 项通过。单独重测一次及再重复三轮通过（74 秒），日志均保留。随后增加“同一个 PeerConnection 内不复用通道 ID”的防护，排除远端复位未完成时立即重复编号的条件；编号耗尽时让新游戏流走 SSH，已有流不重放。新增 30 个短连接（三路并发、十轮）后接 2 MiB 往返、以及编号耗尽回退两项测试均通过。此举不能证明原始偶发问题只有这一原因，正式发布前仍需长时间与公网压力验收。失败日志为 `peer-release-final.log`，防护回归为 `stream-id-regression.log`。部分故障/取消测试会产生 socket/STUN 日志。

中间构建 `296f37b4ccc0b1cf` 曾被本机应用控制以 WinError 4551 拦截（Code Integrity 3077/3033，签名级别要求）；最终重建未触发同一拦截。不修改或绕过系统策略，最终包仍未做受信任发行者签名，不能保证其他系统放行。更早构建的报告在 `previous-checks/`，不作为最终构建通过的证据。

本轮实际改动：

- 从 aiortc 1.15.0 提取只包含数据通道所需的必要模块，保留 ICE、SCTP、DTLS、证书指纹校验，游戏流继续使用可靠有序 DataChannel，移除媒体轨道、PyAV/FFmpeg 和本机 SRTP。13 个模块约 158 KB 源码，来源、BSD 许可和逐文件哈希见[子集说明](../../src/buggcraft/hookup/_rtc/README.md)，可用仓库脚本重现。旧客户端互通依赖只放在 `requirements-interop.txt`，不进入正常构建。
- Widgets/QML 使用系统字体，排除两份 OTF；排除未使用的 PDF 图像插件，再按 PE 导入闭包去除 Qt PDF 引擎。
- Windows 在创建 QApplication 前使用 Qt Quick 二维光栅后端，排除 `opengl32sw.dll`；没有把软件 OpenGL 当成光栅后端。显式指定的渲染后端仍保留，macOS 的默认后端不变。当前不使用着色器或 3D QML；以后加入时需要重新评估。软件绘制使用 CPU，不影响 Minecraft 游戏渲染。
- 启动诊断的 CPU 数改用 `os.cpu_count()`；通知改用已有 Qt/Windows API，删除 `notify-py`、`loguru`、`plyer` 的打包链。排除没有使用的进程池、多进程和 `_uuid` 本机扩展；UUID4 使用标准库现成的纯 Python 路径。
- 删除过时的首启资源/依赖 ZIP 下载逻辑，完整资源随包提供；若资源损坏则明确提示重新安装。构建前检查会拒绝旧媒体/PDF/Mesa 残留，不能把旧目录直接重新压缩当成新构建。

### 50.70 MiB 包内还剩什么

继续检查上述 SHA-256 对应的 ZIP，按压缩后的文件内容统计（不重复计算）：

| 组成 | ZIP 内 MiB | 后续处理空间 |
| --- | ---: | --- |
| Qt、PySide6、Shiboken | 27.55 | 最大组成；当前同时使用 Widgets 和 QML/Quick，裁掉一整套需要迁移相应界面 |
| `Buggcraft.exe` | 12.84 | 包含编译后的业务代码及 Python 依赖；不能当成纯业务代码大小 |
| cryptography、OpenSSL | 5.40 | TLS、SSH 和 DTLS 仍在使用，不能直接删除加密组件 |
| `python311.dll`、`python3.dll` | 2.19 | 两者均有实际 PE 导入引用，不能直接移除 |
| 其他依赖 | 1.85 | 包含标准库扩展和 Windows 运行组件，需要逐项验证 |
| 图片、图标及其他资源 | 0.82 | 已不是主要体积来源 |

本次在独立解压副本中实测，原始 ZIP 和发布清单未改动。执行实际编译后的 `--package-check`，PATH 只保留 Windows 系统目录，清除外部 Python/Qt 路径：

- 同时移除 `qdirect2d.dll` 和 `qminimal.dll` 后，Windows 平台的 14 项检查通过，包含实际主窗口、QML 大厅/好友及加密数据通道。两者的 ZIP 内容合计 **463,324 字节，约 0.44 MiB**，是下一次构建可排除的候选；本次尚未加入正式产物，不能将其记作已减小的包体积。默认 `qwindows.dll` 和测试使用的 `qoffscreen.dll` 保留。
- 移除 `PySide6/QtOpenGL.pyd` 后，检查失败：导入 `QQuickWidget` 时出现 `ImportError: could not import module 'PySide6.QtQuick'`。该文件压缩后约 **2.23 MiB**；编译报告也显示 QtQuick/QtQuickWidgets 的隐式导入。因此，启用二维软件绘制并不代表当前 PySide6 绑定可以删除它。这与此前已成功排除的 Mesa `opengl32sw.dll` 是不同文件。
- 编译报告仍包含 `asyncssh` 67 个模块、`minecraft_launcher_lib` 26 个模块、`aioice` 7 个模块；`build.py` 对这三个包仍有 `--include-package` 强制包含。需要审查动态导入和实际游戏安装/SSH 功能，改成必要模块后重新编译，才能得到净收益；目前没有实测可减少多少 MiB。
- ICNS/TGA/TIFF/WBMP 图片插件仍在包内；是否排除要先明确用户自定义图片、在线图标等输入格式支持。不能仅凭仓库资源没有该格式便认定运行时无用。

副本实验记录位于 `dist/datachannel-slim/remaining-probe-1792660986081971000/results.json`。结论只覆盖本机 Windows 检查，不代表公网、干净虚拟机或 macOS 验收。当前 50.70 MiB 的发布包保持原哈希；后续真正减重应优先审查强制整包包含和统一 UI 依赖，而不是继续盲删 Python DLL。

### Python DLL 专项结论

`.pyd` 也是 Windows DLL。裁剪以应用真实依赖为准，不按文件后缀批量删除，不从运行包中移除证书或加密验证。

| 文件/组件 | 处理 | 原因与验证 |
| --- | --- | --- |
| `python311.dll` | 保留，原始 5,765,912 字节 / ZIP 内 2,278,645 字节 | EXE 和 CPython 扩展需要的运行时；Nuitka 编译业务代码后仍依赖 Python C API |
| `python3.dll` | 保留，原始 67,352 字节 / ZIP 内 22,967 字节 | PySide6、Shiboken 和其他稳定 ABI 扩展的依赖；不是重复的完整解释器 |
| `_multiprocessing.pyd`、`_uuid.pyd` | 已排除 | 当前无进程池/共享内存需求；UUID4 的标准库回退在编译成品中验证 |
| `_ssl.pyd`、`_hashlib.pyd`、OpenSSL DLL | 保留 | HTTPS、哈希、证书及联机加密需要；测试 TLS 上下文、哈希、SSH、AES-GCM 和 DTLS |
| `_socket.pyd`、`select.pyd`、`_overlapped.pyd`、`_asyncio.pyd`、`_queue.pyd` | 保留 | 网络、Windows 异步 IO、线程下载及队列支持；不能为几十 KB 破坏网络功能 |
| `_ctypes.pyd`、`_cffi_backend.pyd` | 保留 | Windows API、Qt 设置及加密库调用仍有真实需求 |
| `_lzma.pyd`、`_bz2.pyd` | 保留 | 游戏/Java 安装及用户压缩包格式支持；在编译成品中验证 ZIP BZIP2/LZMA 及 TAR GZ/BZ2/XZ |
| `pyexpat.pyd`、`_elementtree.pyd`、`_decimal.pyd`、`unicodedata.pyd` | 保留 | XML 元数据、数值和 Unicode/网络域名依赖；保留功能比再省零散 KB 更重要 |

两个 Python 核心 DLL 在完整 ZIP 内合计约 **2.19 MiB**，不是当前包体积的大头。去掉它们需要迁移 Python 运行架构，不能通过改一个打包开关安全完成。Qt/PySide6 与编译进 EXE 的业务/依赖才是下一步的大头；当前方案不能承诺 10 MB。

### 验证方法与边界

最终成品需要分别在 Windows 平台插件和 offscreen 下运行 `--package-check`，PATH 仅保留 Windows 系统目录，清除 Python 环境变量。每轮覆盖 14 项：压缩与 Java 归档、XML/Decimal/UUID、线程池/哈希/TLS、SSH/AES-GCM、HTTPS CA、游戏协议资源、DTLS/64 KiB 往返、主窗口、QML 大厅与好友页。截图与 JSON 报告放在同一个构建目录。

源码回归覆盖新旧 aiortc 双向协商、指纹拒绝、2 MiB 并发直连、中转/自动回退、十轮多客户端房间、关闭取消、内容下载/整合包及打包校验。反复房间关闭发现 Windows TCP `wait_closed()` 可能无期限等待，已增加限时关闭和取消回收，并补充慢关闭/重置/取消测试。公网、干净 Windows 虚拟机及 macOS 真机尚未在本轮重测，不能用本机通过替代这些边界。

## 系统字体版本实测

2026-10-22 已完成 Windows x64 重新构建，产物在 `dist/system-fonts/`，原来的 `dist/` 基线包保留。

| 项目 | 修改前 | 系统字体版本 | 减少 |
| --- | ---: | ---: | ---: |
| 完整 ZIP 字节数 | 106,646,508 | 97,853,290 | 8,793,218 |
| 完整 ZIP MiB | 101.71 | 93.32 | 8.39 |
| 解压字节数 | 267,725,323 | 255,907,099 | 11,818,224 |
| 解压 MiB | 255.32 | 244.05 | 11.27 |
| 文件数 | 355 | 353 | 2 |
| 包内字体文件数 | 2 | 0 | 2 |

新 ZIP 的 SHA-256 为 `67a3a9226953abc747d6ee58c71b088c629bb7348130947e41782d45143279c5`。新包的资源清单在 `dist/system-fonts/size-audit/`，本页下方和随文 CSV 保留初次审计基线。图片和品牌资源继续随包提供。

验证结果：系统字体与双平台构建规则的 2 项测试、现有 macOS 打包逻辑的 2 项测试通过；源码界面在禁止注册自带字体时仍可运行，实际 Windows 截图中中文正常。新包在 PATH 仅有 Windows 系统目录、清空 Python 环境变量的条件下通过 `--package-check`，覆盖主窗口、QML 大厅、好友页、SSH/AES-GCM、证书和 64 KiB 本地 WebRTC 往返。已核对包内无 OTF/TTF/WOFF 字体，发布文件哈希检查通过。macOS 本轮未进行真机重新构建。

## 初次审计基线（历史）

本节及后面的资源拆解是裁剪前的审计和方案记录，便于核对收益来源；其中“可移除/需验证”等表述代表初次审计时的状态。当前已实施项和 Python DLL 结论以上方新版本记录为准。

本次逐项统计了现有 Windows x64 成品 ZIP 的 355 个文件，以及源码 `resources/` 的 94 个文件，并检查了字体加载、图片引用、联机实现和构建参数。数值属于这份本地产物，不代表重新构建或其他平台的尺寸。

| 项目 | 实测值 |
| --- | ---: |
| 完整包 | `dist/Buggcraft-runtime-windows-x64.zip` |
| ZIP 实际下载大小 | 106,646,508 字节，即 **101.71 MiB / 106.65 MB** |
| 解压文件大小合计 | 267,725,323 字节，即 **255.32 MiB / 267.73 MB** |
| ZIP 文件内容压缩后合计 | 106,594,734 字节 |
| ZIP 目录及文件头开销 | 51,774 字节 |
| SHA-256 | `fbaa080ffe139cdff9792acb76b591445edce67b0c33f4b59ddf272af428521d` |

以下统一使用 MiB（1 MiB = 1,048,576 字节）。「包内占用」为文件在现有 ZIP 中的压缩后大小，才能用于估算下载减重；各行不重复计数。文档、源码、虚拟环境、编译缓存和 `dist/qt-unused` 不在这个 ZIP 内，删除它们不能减少用户下载量。

## 体积清单

| 组成 | 文件数 | 包内占用 MiB | 解压大小 MiB | 解决方法与限制 |
| --- | ---: | ---: | ---: | --- |
| PyAV / FFmpeg / SRTP：`av/`、`av.libs/`、`pylibsrtp/` | 81 | **31.51** | **80.48** | 改为只处理 WebRTC DataChannel 的实现，摆脱音视频依赖；需重新对接联机后端，扣除新库大小后才是实际收益 |
| Qt / PySide6 / Shiboken | 154 | **30.14** | **78.44** | 先排除 PDF 图像插件；要大幅消除这一项，需要迁移 UI，保留当前 Python 界面无法整项删除 |
| `Buggcraft.exe` | 1 | **14.02** | **39.25** | Nuitka 编译产物，混合业务代码和已编译 Python 依赖；继续按导入图裁剪，或迁移原生业务代码，不能把整项都归为解释器 |
| 两份字体 | 2 | **8.38** | **11.26** | 正文字体使用系统字体；装饰字体按实际固定文案做子集，或统一替换为系统字体 |
| 软件 OpenGL：`opengl32sw.dll` | 1 | **7.31** | **19.68** | 验证 Qt Quick 软件渲染、无显卡/旧显卡/远程桌面后再决定是否可去掉；不能仅因开发机能运行便删除 |
| `cryptography`、OpenSSL DLL | 3 | **5.40** | **15.11** | 联机与登录安全功能需要；迁移时评估统一 TLS/加密依赖，不能直接删库 |
| `python311.dll`、`python3.dll` | 2 | **2.19** | **5.56** | 这只是可单独识别的 Python DLL，不含 EXE 内编译代码；彻底取消它们需要移除 Python 运行依赖 |
| 其他依赖和系统运行库 | 33 | **1.88** | **4.45** | 逐项检查，避免删掉证书、系统运行库和隐式导入依赖 |
| 图片和图标 | 56 | **0.79** | **1.00** | 保留设计资源；可做 PNG 无损优化，收益很小 |
| QML 文本资源 | 22 | **0.03** | **0.08** | 文本本身体积很小；大头在上面的 Qt 引擎和插件 |

Qt 与联机音视频依赖合计 **61.65 MiB，约占下载包 60.6%**。完整逐文件数据见 [成品文件清单](launcher-package-inventory.csv)，包含每个文件的分类、压缩前和压缩后字节数。

### 字体：资源里最值得处理的部分

| 文件 | 包内 MiB | 原始 MiB | 方法 |
| --- | ---: | ---: | --- |
| `resources/fonts/SourceHanSansCN-Normal.otf` | 6.87 | 7.96 | 正文改用系统中文字体与回退链；统一修改 Widgets、QML 和字体加载入口 |
| `resources/fonts/ChuangKeTieJinGangTi-2.otf` | 1.51 | 3.30 | 保留装饰字效果时，针对固定按钮/标题文案生成字体子集；或者换系统字体 |

`src/buggcraft/main.py` 中的 `load_custom_font()`、`ui/dialog/MultiplayerDialog.py` 和多个 Widgets/QML 文件都有字体加载或字体名引用。实现时应先集中字体选择，再修改引用和打包排除规则，不能只把两个文件删掉。

正文会显示用户名、聊天、版本、模组等任意内容，不适合只保留界面文案中的汉字。若需要保留自定义字体，可对子集以外的内容回退到系统字体；装饰字体只用于固定文字时，才适合严格按实际字符裁剪。应检查中文、生僻字、emoji、不同系统及不同 DPI 下的布局。

示例：使用 FontTools 的 `pyftsubset`，把已收集的装饰文字写入 UTF-8 文本 `fixed-ui.txt`，执行 `pyftsubset ChuangKeTieJinGangTi-2.otf --text-file=fixed-ui.txt --output-file=decorative-subset.otf`。实际子集大小需要生成后再测，并核对字体使用授权。

两份字体全部使用系统字体时，现有包可移除的旧内容约 **8.38 MiB**；保留装饰字体子集时，需减去新字体大小。代价是各平台字体外观及文字宽度会有差异。

### 图片：逐张检查后的结果

发布包内包含 **55 张 PNG 和 1 个 ICO**。源码中另外 14 份不同尺寸的 `resources/icons/*/app.png` 已被 `build.py` 排除，不应再次记作待节省体积。

| 文件/集合 | 尺寸 | 原始大小 | 当前包内占用 |
| --- | --- | ---: | ---: |
| `images/minecraft_bg.png` | 926 × 560 | 369,488 字节 | 369,347 字节 |
| `images/multiplayer_bg.png` | 684 × 475 | 273,482 字节 | 273,567 字节 |
| `images/user/MINECRAFT.png` | 396 × 112 | 30,910 字节 | 30,753 字节 |
| `icons/app.ico` | 多尺寸图标 | 276,710 字节 | 63,183 字节 |
| 其他 PNG | 详见资源清单 | 已逐张检查 | 全部图片/图标合计仍不足 0.8 MiB |

对全部发布 PNG 做了内存重编码试验，没有覆盖原文件：

| 方法 | 55 张 PNG/转换图片的文件字节合计 | 相对原 PNG 文件的节省 |
| --- | ---: | ---: |
| 原图 | 767,548 | — |
| Pillow `PNG optimize=True` | 710,954 | 56,594 字节，约 **55.3 KiB** |
| Pillow 无损 WebP，`method=6` | 549,606 | 217,942 字节，约 **212.8 KiB** |

这是图片文件本身的合计，重新放入 ZIP 后的收益仍需重测，不能直接当作 ZIP 减重结果。转换格式还要验证 Qt 图片插件与 QML 解码，若因此额外引入插件，可能抵消收益。

检查到的完全相同文件：

- `images/Install/InstallNewGame.png`、`settings/About1.png`、`settings/About3.png`。
- `images/login/start-logging.png`、`images/user/logo_minecraft.png`。
- `images/user/external_tab_btn.png`、`images/user/external_tab_btn_active.png`。

合并这些重复资源最多移除约 **20.6 KiB 原始内容**，还需同步修改引用。像素按钮、渐变条可以以后用原生绘制或九宫格实现，但收益不值得优先重画。两张背景图及现有品牌图可以保留并在迁移 UI 时复用。

完整 [资源清单](launcher-resource-inventory.csv) 包含 94 个文件的尺寸、原始字节数、是否实际打包、包内字节数、源码与包内资源是否一致、相同内容的其他路径。本次 80 个已打包资源均与源码一致。

### 联机：为什么带入了大套音视频库

`requirements.txt` 固定了 `aiortc` 和 `av`，`build.py` 显式包含完整 `aiortc`、`aioice` 和 `av` 包。`av.libs/` 单独占压缩后约 **28.58 MiB**，其中包括 AV1 等编解码库。

但 `src/buggcraft/hookup/peer.py` 的 SDP 校验只接受 `m=application`，游戏流量走可靠、有序的 DataChannel，没有使用音视频轨道。因此当前功能可以研究改为不含媒体支持的数据通道实现。

具体方案是用 [libdatachannel](https://github.com/paullouisageneau/libdatachannel) 替换 aiortc 数据通道层。[官方构建说明](https://github.com/paullouisageneau/libdatachannel/blob/master/BUILDING.md) 提供 `NO_MEDIA` 选项，可以关闭媒体支持；它支持 Windows、macOS、Linux。使用 Python 时需要绑定层或原生扩展；迁移原生程序时可直接对接原生接口。

必要工作：

1. 保留现有信令、SDP/ICE、可靠有序传输和应用层帧格式，接入新数据通道回调。
2. 实现并验证流控、半关闭、取消、重连和大数据传输。
3. 保留 DTLS、SSH 加密中继与节点信任校验，验证新旧客户端互通、NAT 穿透及中继回退。
4. 确认不再导入原栈后，删除对应依赖和 Nuitka 强制包含项，再重新构建、测量。

**31.51 MiB 是旧媒体依赖的可替换范围，不是保证能省下的净值**，还要计入新的 SCTP/ICE/DTLS 库及绑定。不能直接删 `av.libs`：aiortc 的导入和运行链依赖 PyAV；即便业务只用数据通道，也需要先改依赖实现。

### Qt：可先验证的小项与需要迁移的大项

- PDF 图像插件：`PySide6/qt-plugins/imageformats/qpdf.dll` 加 `qt6pdf.dll`，压缩后合计 **2.59 MiB**、解压 **5.13 MiB**。未查到应用使用 PDF 的路径；构建报告显示 PDF 引擎被 `qpdf.dll` 引入。可先排除此图像插件，再按现有 PE 依赖裁剪流程移除无人引用的 PDF 引擎，重新检查动态图片加载、QML 和打包检查。它已包含在 Qt 30.14 MiB 中，不能额外重复相加。
- 软件 OpenGL：`opengl32sw.dll` 的 **7.31 MiB** 是条件性收益。必须先在 Qt Quick 软件渲染、无 GPU/远程桌面等环境验证，仍需它的机器上不能删。
- 当前已启用 LTO、QML 依赖扫描、未使用 Qt DLL 裁剪、Qt 翻译排除和构建图标排除。隔离目录中的 Qt WebEngine 等文件不在成品内，不能再次计入减重。
- 同时保留 Widgets 和 Qt Quick 是现架构成本的一部分。统一界面框架有迁移成本；是否能省某个 DLL 取决于最终依赖图，不能只取消一个强制导入就宣称整套引擎已移除。

## HMCL 为什么只有十来 MiB

以 [HMCL 3.16.4 官方发布](https://github.com/HMCL-dev/HMCL/releases/tag/v3.16.4) 为例，GitHub API 的文件字节数是：

| 文件 | 大小 |
| --- | ---: |
| EXE | 10,907,431 字节，10.40 MiB |
| JAR | 10,453,287 字节，9.97 MiB |

它是 Java/JavaFX 启动器。这种下载大小不包含完整 Java 运行时；[构建逻辑](https://github.com/HMCL-dev/HMCL/blob/main/HMCL/build.gradle.kts) 将原生启动部分与 JAR 拼接生成 EXE，并非把全部代码编译为独立原生程序。[JavaFX 依赖修补代码](https://github.com/HMCL-dev/HMCL/blob/main/HMCL/src/main/java/org/jackhuang/hmcl/util/SelfDependencyPatcher.java) 会检测 JavaFX，缺少时下载依赖。

因此它的小文件是实际的小应用分发物，但运行所需依赖有一部分位于包外。与本项目自带 Python、Qt、音视频栈的完整 ZIP 比较时，需要把首次运行新增的运行依赖一起统计。游戏本身使用的 Java 和启动器 Java 可能版本不同，也不能默认总能共用。

## 两条实施路线

### 保留现有程序，先做真实减重

| 优先级 | 工作 | 可移除的旧包内容 | 验收 |
| --- | --- | --- | --- |
| P0 | 集中字体设置，正文使用系统字体、装饰字体子集化/替换 | 最多 8.38 MiB，子集字体需扣回 | 中文及动态文本、各 DPI、Widgets 与 QML 一致 |
| P0 | 精确排除 PDF 图像插件，重算 DLL 依赖 | 约 2.59 MiB | 图片加载、QML 界面、`--package-check` |
| P1 | 使用无媒体数据通道库替换 aiortc/PyAV | 31.51 MiB 旧依赖，需扣回新组件 | 新旧客户端互通、真实联机与中继回退 |
| P2 | 条件性裁剪软件 OpenGL | 最多 7.31 MiB，未验证不能算入承诺 | 无 GPU、旧驱动、远程桌面、Qt Quick 软件渲染 |
| P3 | 图片无损优化与重复引用合并 | 数十至数百 KiB 级 | 像素外观、透明度、全部界面资源加载 |

仅按现有条目扣除两份字体和 PDF，理论下载大小从 101.71 MiB 降至约 **90.73 MiB**；保留字体子集等新资源时应加回。这个数值是库存减法，尚未实现、重新构建或运行验证。现有 Python + Qt 架构下，小修裁剪不能保证达到 HMCL 那种十来 MiB。

### 要真正小且跨平台：迁移成原生程序

建议先用 **Rust + Slint 的原生后端 + 无媒体数据通道组件** 做可测量的技术样机，再决定完整迁移。[Slint 官方桌面支持](https://docs.slint.dev/latest/docs/slint/guide/platforms/desktop/general/) 覆盖 Windows、macOS、Linux。应选择不依赖 Qt 的后端、限制启用的渲染器和编解码器，并在确定方案前核对组件授权。

这里的迁移是重写业务与界面运行部分，不是在外面加壳，也不继续捆绑 Python 后端。最终体积以带齐必要运行组件的构建产物实测为准，不承诺仅换语言就能得到固定的 10 MiB。

可复用资源和工作范围：

| 部分 | 迁移方法 |
| --- | --- |
| 背景、像素按钮、品牌图、图标 | 直接复用 PNG/ICO；新平台按需转换图标格式，保留透明度和像素风格 |
| 布局、Widgets、QML | 用新 UI 重写，按页面对照验证；现有 QML 不能直接当作 Slint 界面运行 |
| 字体 | 默认系统字体；少量固定装饰文字保留子集 |
| 下载、校验、解压、版本解析、Java 检测、游戏启动 | 移植现有 Python 逻辑，保留配置和数据目录兼容；重测中断恢复及整合包/加载器 |
| 微软登录和令牌保存 | 移植登录流程及存储，验证刷新、失效和重新登录 |
| 聊天、房间、P2P 和 SSH 中继 | 复用协议及服务端，重写客户端实现，保持加密和信任边界 |
| 打包、更新、签名 | 每平台单独构建、测量与验收；目前仓库只配置 Windows/macOS 发布，还需补 Linux 流程 |

第一阶段样机应包含真实页面图片、中文输入/显示、HTTPS 下载与启动游戏、加密数据通道和中继所需组件。先测完整包与首次启动新增依赖，避免只测一个空窗口得到误导性的大小。若把十来 MiB 作为目标，应在样机阶段验证是否能达到，再安排全面移植。

## 清单复现与验证边界

仓库根目录执行下面的命令即可重新生成两份 CSV；工具只使用 Python 3.11+ 标准库，不改动成品和资源：

```powershell
py -3 scripts/audit_launcher_size.py --output-dir docs/technical
```

默认不带参数时输出到 `dist/size-audit/`，避免更新文档快照。也可通过 `--archive` 指定另一份 ZIP，通过 `--resources` 指定资源目录。当前分类规则针对 Windows 成品，不能直接当作 macOS/Linux 的完整依赖分类规则。

初次审计完成了文件统计、PNG 重编码试验、重复资源检查和代码依赖调查。系统字体、PDF、Windows 光栅渲染/软件 OpenGL 排除、联机数据通道子集及 Python 可选依赖裁剪现已实施；本页后半段保留原始库存和方案对照，原生 UI/业务迁移未实施。
