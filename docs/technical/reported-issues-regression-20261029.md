# 已报告问题的持续回归

本轮修复在 `release/alpha2-integration` 隔离工作区进行，原生节点在 `release/alpha2-bridge`。暂不发布，不覆盖另一个窗口尚未提交的域名接入修改。域名接入合并后还需运行接入、房间和诊断组合回归。

测试入口统一为 `tests/` 中的 pytest/unittest 用例。UI 用例发送真实 Qt 鼠标、键盘和输入法事件，检查实际文件、任务状态和进程；本地 HTTP 和 C++ 节点提供可重复的网络环境。仅截图、模拟成功回调、打印日志不构成功能通过。

## 当前收尾清单

以下托管结果对应代码提交 `c20a454766dccc050c22022728c60afe0d20eebb`，记录于 2026-10-29。文档提交不代表新的代码构建结果。

- [x] 导出模式、后台打包、真实进度、取消、完成后手动关闭及重复导入改名/取消回归。
- [x] 并发下载、同文件缓存锁、Java 复用、空目录房间安装、更新下载凭证回归。
- [x] 房主显示、房主/房客提交诊断及真实节点日志授权、撤回、聊天和转让 UI 回归。
- [x] 本地完整 pytest：867 通过、18 环境跳过；新增发布门禁和诊断竞态用例另外通过。
- [x] 真实整合包导出/导入后启动 Minecraft、四游戏本地联机实测；范围和证据见下表。
- [x] Linux 托管客户端及原生回归通过，包括真实 P2P 故障、房间协议和诊断附件流控：[运行 40833898601](https://github.com/vdjango/buggcraft/actions/runs/40833898601)。
- [x] 重新核对中文 UI 截图：`E:\code\.test-tools\alpha2-ui-evidence`。另补跑真实节点房间 UI 1 项通过，记录 `real-native-room.xml`。
- [ ] Windows 托管客户端及原生回归：同一运行中仍在构建生产 C++ 运行时，尚无最终结论。
- [ ] 五平台启动器打包：[运行 40833898523](https://github.com/vdjango/buggcraft/actions/runs/40833898523)，尚在进行，不能标记完成。
- [ ] 另一窗口的域名接入修改完成后，合并并执行接入、房间、好友和诊断组合回归；本轮保持隔离，不合并、不发布。

## 用例与修复的对应关系

| 编号 | 问题和验收 | 持久化测试入口 |
| --- | --- | --- |
| REG-01 | 导出模式、真实字节进度、取消、出错清理；完成弹窗等待用户关闭；事件循环继续响应 | `test_instance_modpack_entry.py`、`test_modpack_import.py` |
| REG-02 | 重复导入自动提出新名称，用户可修改或取消；新名称仍占用时阻止；慢文件检查不冻结窗口，旧结果不覆盖新选择 | `test_download_ui.py::DownloadChecklistUiTests::test_duplicate_import_renames_without_overwriting_existing_instance`、`test_download_ui.py::DownloadChecklistUiTests::test_duplicate_import_cancel_and_occupied_replacement_start_no_task`、`test_modpack_drop.py` |
| REG-03 | 游戏核心、libraries、assets 同池下载；加载器安装与模组下载重叠；1–64 路并发设置有效 | `test_download_transport.py`、`test_download_concurrency.py`、`test_modpack_import.py`、`test_modrinth_import.py` |
| REG-04 | 两个任务同时安装到同一个文件，只写一次；Windows 普通/扩展路径共用锁，取消等待不破坏占用者 | `test_download_locks.py`、`test_download_transport.py::DownloadTransportTests::test_parallel_tasks_share_one_verified_target_without_part_file_races` |
| REG-05 | 没有根目录、实例或版本时，房间安装创建目录并保存位置 | `test_room_launch_flow.py::RoomLaunchFlowTests::test_room_install_creates_and_saves_default_root_on_first_use`、`test_room_mod_installation.py` |
| REG-06 | 已校验 Java 复用；损坏/缺失/不适配的 Java 不复用；并发安装共享目标 | `test_java_downloads.py`、`test_java_runtime_selection.py` |
| REG-07 | 延迟点击更新时重新取得七牛下载凭证；下载校验、失败保留原文件及重试 | `test_update_client.py`、`test_launcher_updates.py` |
| REG-08 | 房主和房客均看到房主标识；兼容只有 manager_id/provider_id 的快照；转让后标识正确 | `test_room_lobby_ui.py`、`test_room_lobby_live_ui.py` |
| REG-09 | 房主和房客均可提交诊断；匿名/未确认不能提交；上传未完成时重复点击不弹新窗口、不生成第二条反馈；真实认证失败后可修复重试，管理员能下载相同附件 | `test_room_lobby_ui.py`、`test_diagnostics_ui.py` |
| REG-10 | 请求安装日志需玩家授权；拒绝、撤回、转让和退出清空授权；界面不能读其他成员私有日志 | `test_room_lobby_live_ui.py`、原生 `test_room_lobby.py` |
| REG-11 | 优先设置的下载源；P2P 未连接禁止文件兜底；资源包和光影不阻止必需模组准备 | `test_room_mod_installation.py`、原生 `test_resource_metadata.py` |
| REG-12 | P2P 空闲不误切中转；单向 UDP 故障只影响对应玩家；信令中断保留已建立游戏通道；重连和 STUN 备用 | 原生 `test_peer_heartbeat.py`、`test_peer_reconnect.py`、`test_peer_signaling_attempt.py`、`test_peer_stun_fallback.py`、`test_ipv4_p2p.py`、`test_route_selection.py` |
| REG-13 | 原生诊断上传支持流控；大附件慢磁盘时其他控制请求继续；截断清理和大小限制 | 原生 `compatibility/tests/test_feedback_native.py` |
| REG-14 | 精简/常规包经真实 UI 导出、导入，再由实际 Java 启动 Minecraft 并加载资源 | `test_game_launch_live.py::RealMinecraftUiTests::test_buggpack_export_both_modes_import_and_launch_real_game` |
| REG-15 | 四个实际 Minecraft 窗口进入准备房间、移动/方块/聊天同步、死亡重生、转让管理后游戏不断线、退出重进 | `test_four_game_multiplayer_live.py::test_four_real_minecraft_clients_move_build_chat_respawn_and_reconnect` |
| REG-16 | 桥正常/异常退出和启动途中取消后回收子进程与全部管道，再启动仍可用；诊断与房间 UI 连续运行不遗留关闭后的事件循环 | `test_native_bridge_runtime.py::test_cancelling_bridge_start_reaps_the_child_and_allows_restart`、`test_native_bridge_runtime.py::test_real_cpp_bridge_methods_errors_shutdown_and_restart`、`test_diagnostics_ui.py`、`test_room_lobby_live_ui.py` |
| REG-17 | 好友悬浮按钮重新布局后立即卸载页面，不执行已销毁对象的延迟回调；房间控件先完成可见/可用布局，再点击和断言 | `test_friend_entry_ui.py::FriendEntryUiTests::test_queued_floating_button_layout_is_safe_after_page_unload`、`test_room_lobby_ui.py` |

## 自动运行

`.github/workflows/package.yml` 持续运行客户端页面、房间、日志、导出和缓存锁回归，每个模块使用独立进程，避免 Qt 对象生命周期串扰。

`.github/workflows/client-regression.yml` 在主分支/修复分支推送、PR 或手动触发时，分别在 Windows 和 Linux 构建生产 C++ 节点与桥，运行上述真实 HTTP、诊断上传、房间点击、下载与 P2P 用例。保存 JUnit、截图和构建日志；这些测试依赖只装在测试环境，不打入启动器发行包。

原生仓库 `.github/workflows/core.yml` 自动运行 P2P 和房间协议回归；`scripts/check_compatibility.py` 默认包括诊断上传用例。它是测试套件的加载器，实际测试仍由 unittest 用例执行。

`test_regression_wiring.py` 同时检查文档引用的类/方法确实存在、这些功能仍被 CI 调用、三个工作流固定相同的原生提交，避免后续重构漏掉测试入口。

发布流程还要求同一条主分支提交的五平台打包及 Windows/Linux 客户端和原生回归全部通过；用例覆盖缺失、失败、取消、跳过、旧提交和最新重试，不能用旧的成功结果替代。打包与回归的路径过滤必须相同，避免只触发其中一个。

本地运行客户端的常规入口：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_QUICK_BACKEND = 'software'
$env:BUGGCRAFT_NATIVE_SOURCE = '<原生节点仓库绝对路径>'
$env:BUGGCRAFT_NATIVE_CORE = '<完整安装目录>/bin/buggcraft-core.exe'
$env:BUGGCRAFT_BRIDGE_EXECUTABLE = '<完整安装目录>/bin/buggcraft-bridge.exe'
$env:BUGGCRAFT_BRIDGE_LIBRARY = '<完整安装目录>/bin/buggcraft_bridge.dll'
$env:BUGGCRAFT_BRIDGE_PACKAGE = '<完整安装目录>'
python -m pytest -q tests --junitxml=build/regression.xml
```

先在原生仓库执行 `cmake --install build --config Release --prefix runtime`，或使用 `scripts/build_bridge.py` 的完整安装产物。动态库和配套 `share/buggcraft-native/python/buggcraft_bridge.py` 必须来自同一个安装目录，不能只指定编译目录中单独的 DLL。Linux 使用对应的无 `.exe` 二进制与 `lib/libbuggcraft_bridge.so`。

Windows 可见回放把 `QT_QPA_PLATFORM` 改成 `windows`，仍由相同的 pytest 用例操作控件。网络测试使用本地服务器，不会将公网下载超时冒充功能失败，也不会把本地文件校验或 UI 错误当成网络慢而跳过。

实际 Minecraft、四游戏及公网测试保留独立环境门控：缺少游戏、Java、账号或节点时会明确跳过，不能把跳过计为通过。它们不因跑通常规回归就自动宣称验收成功。

四个真实游戏窗口的重复执行入口仍是 pytest（需要桌面、完整游戏和 Node.js 观察客户端）：

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:BUGGCRAFT_FOUR_GAME_LIVE = '1'
$env:BUGGCRAFT_FOUR_GAME_NODE = 'local'
$env:BUGGCRAFT_TEST_WORKSPACE = 'E:\code'
$env:BUGGCRAFT_LAUNCHER_SDK = '<本次启动器仓库>/src/buggcraft'
$env:BUGGCRAFT_LIVE_GAME_DIR = '<完整 Minecraft 1.21.8 目录>'
$env:BUGGCRAFT_LIVE_JAVA = '<Java 21>/bin/java.exe'
python -m pytest -q -s tests/test_four_game_multiplayer_live.py
```

它启动本次构建的 C++ 节点，检查四人准备、开放世界、实际移动/方块/聊天同步、死亡重生、房主转让和重入，并保留游戏窗口截图。这里使用回环网络；跨运营商公网联机需要另跑远程模式。

## 本轮实测记录

| 范围 | 实测结果 | 证据 |
| --- | --- | --- |
| 导出 UI、打包取消/进度、下载、Windows 缓存路径锁 | 57 passed、19 subtests passed | `E:\code\.test-tools\alpha2-export-lock-final.log/xml` |
| 原生 C++ 单元与 ABI | CTest 3/3 通过 | `alpha2-native-bridge/build/Testing/Temporary/LastTest.log` |
| 原生协议兼容及真实诊断附件上传 | 45 项通过 | `E:\code\.test-tools\alpha2-compatibility-verified.log` |
| 大附件实际暂停/恢复、控制通道响应及附件一致性 | 5 项通过 | `E:\code\.test-tools\alpha2-feedback-paused-verified.log` |
| 慢文件检查、新旧选择竞态、重名取消与拒绝占用名称 | 4 项通过 | `E:\code\.test-tools\alpha2-inspection-negative-verified.log/xml` |
| P2P 空闲、单向 UDP 故障恢复和信令短断，进程与共享库两模式 | 6 项通过 | `E:\code\.test-tools\alpha2-heartbeat-verified.log` |
| 真实 Minecraft 两模式导出/导入/启动 | 1 项通过，使用 Java 21 | `E:\code\.test-tools\alpha2-real-game-java21.log` |
| 首轮完整回归中的并发失败 | 保留失败记录；扩展路径锁修复后专项通过，完整回归重新执行 | `E:\code\.test-tools\alpha2-full-traced.log/xml` |
| 客户端完整 pytest，严格处理未回收资源警告 | 单次命令 885 条：867 通过、18 环境跳过，393 子断言通过；1252.79 秒，无失败 | `E:\code\.test-tools\alpha2-full-lifecycle-final.log/xml` |
| 安装目录中的真实 C++ DLL/独立进程、错误恢复和重启 | 2 项通过；最初缺失绑定文件的环境错误复测通过 | `E:\code\.test-tools\alpha2-runtime-verified.log/xml` |
| 原生完整 unittest discover | 164 条：147 通过、17 环境跳过，772.798 秒；无失败 | `E:\code\.test-tools\alpha2-native-full-installed.log` |
| 四个真实 Minecraft 1.21.8 窗口、本地生产 C++ 节点和桥 | pytest 1 项通过，158.99 秒；四人准备、移动/拆放/聊天同步、三房客重生、转让、重入均通过 | `E:\code\.test-tools\alpha2-four-games-local.log/xml`；原生 `validation-artifacts/vanilla-20261029-131106/report.json` 及四张游戏窗口截图 |
| 桥、诊断、房间与好友 UI 组合，严格资源警告复测 | 27 项、55 子断言通过；启动取消、真实管道 EOF、房间操作及好友销毁检查，不忽略资源警告 | `E:\code\.test-tools\alpha2-focused-final.log/xml` |
| 按 CI 独立模块入口复测桥和真实节点 UI | 46 项通过；各模块独立进程，以严格资源警告运行；另外路由/传输/发布门禁组合 31 项、64 子断言通过 | `E:\code\.test-tools\alpha2-isolated-regression/`、`alpha2-routing-final.xml` |
| 下载、Java、更新和好友 UI 组合复测 | 167 项、97 子断言通过 | `E:\code\.test-tools\alpha2-download-ci-fixed.log/xml` |
| 发布门禁及测试入口一致性 | 15 项、72 子断言通过；当前共收集 888 条，较完整运行时增加 3 条发布流程检查 | `E:\code\.test-tools\alpha2-release-wiring-final.xml` |
| 真实诊断上传、重复点击及发布检查的最终定向回归 | 21 项、72 子断言通过，严格处理未回收资源警告；重复点击时保持实际上传任务未完成，再释放并验证真实节点只收到一份附件 | `E:\code\.test-tools\alpha2-final-targeted.log/xml` |

前期分段续跑与修复后的核对记录仍保留；最终又以单次完整 pytest 命令执行通过上述 885 条用例。保留两次失败：单独编译目录缺少 FFI 绑定、诊断测试夹具误引入节点包；改用完整安装产物，并将节点夹具归回原生仓库后均已通过。后半段曾出现 Windows 子进程清理警告，追加组合运行可重复；补齐桥管道 EOF 等待、启动取消回收和测试夹具关闭后严格复测，保留原始日志 `alpha2-ci-group-local.log`、`alpha2-ci-group-cleanup.log`。好友按钮旧延迟回调可稳定触发销毁后 QML 错误，新回归在旧实现上失败、修复后通过。原生首次完整运行还保留一次高负载下添加节点超时的失败记录；重新运行完整套件后通过，没有跳过或放宽该断言。四游戏实测只验收本机节点，不代替跨运营商公网测试；其他窗口未合并的域名接入不属于这轮验收。

完整运行中的 18 个跳过分别为 14 条需显式配置实际游戏目录的 Minecraft 用例、1 条四游戏可见验收、1 条 Linux ELF 裁剪、2 条隔离 Windows 桌面外壳操作。实际游戏两模式导出/导入/启动和四游戏已按表中独立入口启用运行通过；不据此把其余跳过的真实环境分支自动打勾。

托管 CI 与本机结果单独记录。`c7826c3` 的 Linux 两种架构打包通过；macOS 两种架构暴露成员列表刚切换尚未渲染的点击竞态，现保留原断言并等待目标控件可见且可用。Windows 下载组合失败；本机对应组合也复现好友销毁后的延迟回调错误，修复后本机组合通过，托管具体断言待新运行的 JUnit 标注进一步核对。新托管运行尚未完成前，不将跨平台构建标记为通过。整个修复分支不触发下载站发布。
