# macOS 打包

在 macOS 构建机安装 Python 3.11 和 Xcode Command Line Tools，运行：

```bash
bash build_macos.sh
```

脚本创建独立构建环境，安装固定版本依赖，通过 Nuitka 的 PySide6 插件生成 `.app`。Intel 和 Apple Silicon 必须分别使用对应架构的 Python 构建，不能在 Windows 上交叉生成 macOS 可执行文件。GitHub Actions 的「Package launcher」分别使用 `macos-15-intel` 和 `macos-15` 执行这两种构建。

产物位于 `dist/Buggcraft-macos-x86_64.zip` 或 `dist/Buggcraft-macos-arm64.zip`。压缩前验证 `.app` 的代码签名结构，再使用系统 `ditto` 打包，保留 Qt framework 的符号链接和可执行权限。`release.json` 记录平台、入口、大小和 SHA-256。

当前构建使用 Nuitka 的 ad-hoc 签名，没有发行者 Developer ID 签名，也没有 Apple 公证；这不能等同于可直接发布的已公证安装包。CI 会执行打包后的 `--package-check`，检查主窗口、QML 大厅、好友页和本地 WebRTC 数据传输；用户设备上的 Finder 启动、Gatekeeper 和游戏启动仍需真机验收。日志写入 `~/Library/Logs/Buggcraft`，避免修改 `.app`。

## Qt 官方工具与体积

[Qt 官方 `pyside6-deploy`](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html) 也是 Nuitka 的封装，支持 Windows 和 macOS，并可排除未用到的 QML 插件。项目保留现有 Nuitka 构建入口以复用下载引导程序、哈希清单和运行检查；Qt 的 `qmlimportscanner` 根据 `resources/qml` 的实际导入计算需要保留的模块，其他 QML 插件和翻译按规则排除。

Qt 的 C++ 应用部署工具 `macdeployqt` 可以收集 `.app` 的 Qt 依赖，但不会替代 Python、PySide6 和 WebRTC 的打包，因此这里使用面向 Qt for Python 的部署方式。精简只排除未使用的组件，QtCore、QtGui、QtWidgets、QtQuick、QML 及其实际依赖仍需随包提供。
