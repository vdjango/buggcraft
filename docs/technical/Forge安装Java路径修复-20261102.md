# Forge 安装处理器找不到 Java

## 报告与原因

诊断包 Buggcraft-diagnostics-20261101-121245.zip 中的启动器版本为
1.0.1-alpha.1，失败实例为 Minecraft 1.20.1 / Forge 47.4.20。

日志已记录 installertools-1.4.1.jar 下载完成。三次安装失败均在
minecraft_launcher_lib.forge.forge_processors → subprocess.run → CreateProcess
阶段抛出 FileNotFoundError: [WinError 2]。这是处理器的 Java 可执行文件无法找到，
不是已经下载的处理器 JAR 缺失；安装器在未收到明确 Java 路径时回退到系统 java。

## 当前处理

- Forge、NeoForge 在调用安装器前，先选择并验证符合游戏版本要求的 Java，
  以明确路径传入安装器。当前源码已有此修复。
- 本次补充：已配置路径失效或 Java 尚未登记时，先读取配置缓存目录下
  java/*/buggcraft-runtime.json，根据相对路径恢复已下载运行环境，并再次验证真实版本。
  仅检查本启动器的安装记录，不递归扫描磁盘，不依赖系统 PATH，不需要先联网。
- 损坏、版本不符或指向运行环境目录外的安装记录会被跳过。
- 仍找不到可执行文件时，错误中显示具体路径、Java 修复操作及继续安装说明，
  日志保留原始异常。
- 检查仍由现有安装工作线程执行，没有增加主界面的启动扫描或阻塞操作。
  已成功下载的文件由原有继续安装流程复用。

## 源码验证

2026-11-02：以下定向检查共 **27 项测试、21 项子测试通过**，不依赖外部下载服务。

测试类：InstallerJavaRegressionTests、JavaRuntimeSelectionTests、
JavaDiscoveryTests、LocalVersionSafetyTests。

覆盖了实际依赖库的 Forge 安装器及处理器函数调用；下载和进程执行用离线替身验证，
断言处理器收到已验证的 Java 完整路径。此次未执行远程资源下载和完整 Forge 游戏安装。
旧版已打包 EXE 不会因本地源码更新而改变，需要使用包含修复的构建。
