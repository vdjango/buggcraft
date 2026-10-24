# Windows 打包

Windows x64 发布为完整单文件 `Buggcraft.exe`，包含 Python、Qt Quick/QML 和 C++ 联机库。首次运行将依赖解压到 `%LOCALAPPDATA%\Buggcraft\<内容哈希>`，相同版本复用缓存，更新版本使用新目录，不覆盖仍在运行的文件。游戏目录与日志保存在启动器外部。

主窗口出现后在后台清理已登记的旧解压缓存：保留当前版本、最近使用的上一版本、24 小时内使用过的版本和仍在运行的版本。运行状态使用操作系统文件锁判断，关闭或崩溃后自动释放。未登记的历史目录不自动删除；游戏、设置及下载缓存不在清理范围内。

## 本地构建

构建机需要 64 位 Windows、Python 3.11、Visual Studio C++ Build Tools 与 CMake。原生实现位于同级 `minecraft-tunnel-native`：

```powershell
python scripts/build_bridge.py --native-source ../minecraft-tunnel-native --output dist/native-runtime
python build.py --onefile --native-bridge-dir dist/native-runtime --output dist/windows-onefile
```

产物 `dist/windows-onefile/Buggcraft.exe` 为单文件下载；同目录 `release.json` 是内部构建清单，不需要分发。构建使用 Nuitka 的 PySide6 插件和 Qt 官方 `qmlimportscanner` 识别实际 QML 依赖，Windows 再按 PE 导入裁剪未引用的 Qt DLL。原生运行库会完整放入单文件，包括桥接 DLL、子进程、依赖和许可证。

Nuitka 的单文件压缩与缓存行为见[官方说明](https://nuitka.net/user-documentation/use-cases.html)。Windows GUI 以 `QT_QUICK_BACKEND=software` 绘制启动器二维界面，未打包仅供旧方案使用的软件 OpenGL DLL；此设置不影响 Minecraft 的渲染。

## 发布验证

CI 对打包后的可执行文件清除 Python/Qt 环境变量，再执行 `--package-check` 检查应用窗口、QML 页面、原生库和诊断导出。`scripts/stage_release.py` 校验单文件大小与 SHA-256，只将 EXE 和校验文件放进应用下载目录；编译日志、临时清单和个人测试记录不会随包分发。GitHub Actions 另在 Linux x86_64 构建单文件，在 macOS 分架构构建原生 `.app` ZIP。

Windows 文件目前没有受信任的 Authenticode 签名。正式发布如配置证书，可以使用 `--sign-certificate` 或证书存储区指纹，并开启 `--require-signature`；证书密码通过环境变量 `BUGGCRAFT_SIGN_PASSWORD` 提供，不要保存在仓库或发布文件中。

构建工具及依赖定义见 `requirements-build.txt`、`build.py` 和 `.github/workflows/package.yml`。macOS 的 `.app` 结构、签名和分发说明见 [macOS 打包](macos-packaging.md)。
