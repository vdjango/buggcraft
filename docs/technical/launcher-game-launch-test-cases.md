# 启动器真实游戏启动测试用例

这些用例验证启动器调用真实 Java 和 Minecraft 进程的结果，不使用命令构造、JVM 或窗口对象替身。测试账号使用离线账号；按项目要求不测试正版/Microsoft 授权登录。

## 执行方式

真实测试是显式选择的 Windows 测试，需要准备一个完整的 Minecraft 1.21.8 目录和可运行的 Java 21：

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:BUGGCRAFT_LIVE_GAME_DIR = 'E:\code\multiplayer-tests\download-live\minecraft'
$env:BUGGCRAFT_UI_OUTPUT = 'E:\code\.test-tools\real-game-settings'
.build-venv\Scripts\python.exe -m pytest tests/test_game_launch_live.py -q -x -s
```

每个测试目录保存 `launcher.log`、`game-output.log`、Minecraft `latest.log`、启动命令、PID、窗口尺寸、退出码和截图。测试结束会确认没有遗留 Java 进程；失败时也保留日志。

## 用例

| 编号 | 操作与验证 | 状态 | 自动化方法 |
| --- | --- | --- | --- |
| GAME-01 | 首页启动离线 Minecraft，确认真实主类、窗口、GUI 资源和 `latest.log`，正常关闭后再次启动 | [x] | `test_home_real_minecraft_offline_launch_exit_and_relaunch` |
| GAME-02 | 设置语言、版本隔离、Java 和手动内存，启动后核对命令、工作目录和游戏 `options.txt` | [x] | `test_settings_language_isolation_java_and_manual_memory_reach_game` |
| GAME-03 | 设置启动器可见性、分辨率、进程优先级、调试输出和自定义 Java，启动真实窗口并核对实际值 | [x] | `test_settings_real_window_visibility_resolution_priority_debug_and_custom_java` |
| GAME-04 | 修改实例独立 Java、内存、隔离目录，确认实例覆盖全局设置并启动真实游戏 | [x] | `test_instance_independent_java_memory_isolation_reach_real_game` |
| GAME-05 | 注入 Java 目录查询失败，归档实际发生 HTTP 404、校验失败和重复下载，重试成功后用下载出的 Java 启动真实游戏 | [x] | `test_settings_download_real_java_failure_retry_install_and_launch` |
| GAME-06 | 关闭多开时第二次点击为停止；开启多开后启动 4 个真实客户端，选择并停止任一客户端，确认其他客户端继续运行 | [x] | `test_settings_multiple_games_four_real_clients_and_stop_isolation` |
| GAME-07 | 实际原版客户端下载、刷新实例、选择并启动真实游戏 | [x] | `test_download_vanilla_installs_real_client_and_launches_from_instance_list` |
| GAME-08 | 真实 JVM 参数失败后查看日志、修复并启动；异常终止 Minecraft 后保留退出码并重新启动 | [x] | `test_real_jvm_failure_and_game_abnormal_exit_keep_logs_and_allow_relaunch` |
| GAME-09 | 下载及导入可运行 MRPACK，启动后核对游戏实际加载资源包、语言和覆盖文件，原实例保留 | [x] | `test_downloaded_and_imported_runnable_pack_preserve_instances_and_load_resources` |
| GAME-10a | 实际 Fabric 元数据及依赖安装，启动真实 Minecraft，正常退出码为 0 | [x] | `test_download_real_fabric_install_and_launch`；原有基础安装实测通过；新增模组依赖分支见 GAME-11 |
| GAME-10b | 实际 Forge 安装，实例选择、游戏窗口、加载器命令和正常退出码为 0 | [x] | `test_download_real_forge_install_and_launch` |
| GAME-10c | 实际 NeoForge 安装并启动真实 Minecraft | [x] | `test_download_real_neoforge_install_and_launch`；在真实设置页选择 BMCLAPI，依赖预取校验、官方 Java 安装器及真实游戏均通过，退出码 0 |
| GAME-10d | 实际 Quilt 元数据及依赖安装，启动真实 Minecraft，正常退出码为 0 | [x] | `test_download_real_quilt_install_and_launch` |
| GAME-11 | 在新装 Fabric 实例通过内容下载功能放入有效模组和必需的嵌套依赖，再启动游戏核对 Fabric 加载日志 | [x] | `test_download_real_fabric_install_and_launch` 内的 `download_and_load_actual_mod_with_dependency`；真实 HTTP 写入的 `ui_fixture` 和 `acceptance_dependency` 均由游戏日志证实加载，两次游戏退出码均为 0 |

## 本轮证据

- 真实测试输出：`E:\code\.test-tools\real-game-settings\`
- 四客户端输出：`E:\code\.test-tools\real-game-settings\test_settings_multiple_games_four_real_clients_and_stop_isolation\`
- 功能复核的 GAME-01/04/05 输出：`E:\code\.test-tools\real-game-functional-audit\`；GAME-02/03 最终通过输出：`E:\code\.test-tools\real-game-functional-audit-fixed\`。首次复核的语言选择失败保留在前一个目录，不计作通过。
- 这 5 条方法复核 10 次真实启动与正常关闭，报告均保存实际 JVM 返回码 `0`；英语与简体中文主菜单截图已人工查看。
- 正常关闭游戏窗口时核对实际 JVM 返回码为 `0`，同时核对启动器收到的退出事件。点击启动器停止按钮时记录 `stop_requested` 和 `actual_returncode`；Windows 下实际停止返回码可能为 `15`，不将启动器停止事件中的 `0` 当作 JVM 正常退出。
- GAME-07：真实原版 1.21.8 通过本地 HTTP 下载、刷新实例列表并启动；保留实际命令、窗口、`latest.log` 和退出码。
- GAME-08：真实 JVM 非法参数失败、查看启动器保留日志、修复参数后启动；随后杀死准确 Java 子进程，核对异常退出码和再次启动。
- GAME-09：真实可运行 MRPACK 下载与导入各启动一次 Minecraft；包内覆盖文件、资源包和 `options.txt` 均由游戏日志确认加载，原有实例保留。
- GAME-10：Fabric/Quilt 的实际安装和正常启动证据在 `E:\code\.test-tools\shared-branches-20261028-loaders-live\`；Forge 修正后的通过证据在 `shared-branches-20261028-loaders-live-fixed\`。NeoForge 最终通过证据在 `shared-branches-20261028-neoforge-mirror\`，pytest 为 1 passed、12 deselected，耗时 97.76 秒。
- NeoForge 历史失败日志仍保留：`E:\code\.test-tools\shared-branches-20261028-neoforge-logs\test_download_real_neoforge_install_and_launch\neoforge-21.8.57-installer.log`；根因是安装器自身直连 Maven、未使用所选源，修复后依赖由启动器先按源策略预取并验证。另修正 BMCLAPI Maven 路径不能带 `/releases`；自动模式等待失联官方源的慢速运行中断，不计通过。最终 BMCLAPI 实测通过不能替代全部来源分支验证。
- GAME-11：`E:\code\.test-tools\shared-branches-20261028-fabric-dependency\`；pytest 为 1 passed、12 deselected，耗时 152.44 秒；保留两次实际启动、加载模组与依赖的日志、截图、正常退出码及实际下载任务证据。
- 游戏日志包含 GUI atlas 加载记录；四客户端停止用例核对所选进程退出、其他进程保持运行，最后不遗留 Java 进程。
- 日志中可能出现离线账号无法访问 Mojang/Realms 的网络提示；这不属于本轮正版登录测试，也不据此宣称正版认证通过。
