# Buggcraft 客户端 UI 测试矩阵

这份文档是客户端回归入口。每新增一个页面或控件，都要补充一个手工测试用例和一个自动化 UI 用例。

2026-10-29 的已报告问题、持久化用例和 CI 入口见 [持续回归清单](reported-issues-regression-20261029.md)。包含导出/重复导入、界面响应、共享缓存、Java、更新源、房主与诊断、真实 P2P 故障恢复；执行结果与环境门控分别记录。

按功能和操作顺序核对用例是否覆盖完整时，使用 [启动器功能覆盖核对清单](launcher-function-coverage-checklist.md)。清单沿用“页面 → 功能 → 操作”的分层结构，只有该条全部分支执行通过才打勾。首页逐项的操作、预期和自动化方法见 [首页测试用例](launcher-home-test-cases.md)，编号 HOME-01 至 HOME-48；下载页见 [下载页面测试用例](launcher-download-test-cases.md)，编号 DOWNLOAD-01 至 DOWNLOAD-58。

- **手工测试用例**：测试工程师按步骤验证真实环境、异常提示、声音、网络和游戏进程。
- **自动化 UI 测试**：加载真实 Buggcraft 窗口和控件，默认在 Qt offscreen 平台渲染，通过定向 Qt 事件操作页面，保存功能断言、截图和操作日志，不占用桌面鼠标。

只使用 `[x]` 完成、`[ ]` 未完成。缺少任一分支的执行证据就保持空框。按用户要求，本轮不执行正版登录，不将已有的正版测试代码和历史通过记录计入本轮完成项。

## 自动化入口

客户端自动化的正式入口是 pytest 测试用例。下面统一执行首页、下载页、导航、设置关联、实例管理、启动器自动更新、整合包导入、联机大厅、好友页签及首次教学；排除 2 条正版登录用例。下载页专项现有 34 条 UI 方法，并分别覆盖四类内容和多种异常条件；共用分支和加载器选源另有专项入口：

```powershell
# 日常功能回归：离屏渲染，不显示桌面窗口、不移动系统鼠标
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QUICK_BACKEND = "software"
$env:BUGGCRAFT_UI_OUTPUT = "E:\code\.test-tools\client-ui-pytest"
.build-venv\Scripts\python.exe -m pytest -q tests\test_qt_input.py tests\test_client_ui_acceptance.py tests\test_home_ui.py tests\test_download_ui.py tests\test_settings_ui.py tests\test_settings_checklist_ui.py tests\test_shared_branches_ui.py tests\test_loader_source_ui.py tests\test_onboarding.py tests\test_coverage_gaps_ui.py tests\test_startup_errors_ui.py -k "not online"
```

仅在需要观看回放时显式启用 Windows 窗口；点击仍由 Qt 定向事件完成，但显示窗口和原生弹窗可能影响桌面焦点：

```powershell
$env:QT_QPA_PLATFORM = "windows"
$env:BUGGCRAFT_UI_PAUSE_MS = "350"
$env:BUGGCRAFT_UI_OUTPUT = "E:\code\.test-tools\client-ui-pytest-visible"
.build-venv\Scripts\python.exe -m pytest -s -q tests\test_client_ui_acceptance.py tests\test_home_ui.py tests\test_download_ui.py tests\test_settings_ui.py tests\test_settings_checklist_ui.py tests\test_shared_branches_ui.py tests\test_loader_source_ui.py tests\test_onboarding.py -k "not online"
```

也可以单独触发某一组测试：

```powershell
.build-venv\Scripts\python.exe -m pytest -q tests\test_client_ui_acceptance.py::ClientUiHomeTests tests\test_home_ui.py -k "not online"
.build-venv\Scripts\python.exe -m pytest -q tests\test_client_ui_acceptance.py::ClientUiNavigationTests
.build-venv\Scripts\python.exe -m pytest -q tests\test_settings_ui.py::ClientUiSettingsTests
.build-venv\Scripts\python.exe -m pytest -q tests\test_settings_checklist_ui.py
.build-venv\Scripts\python.exe -m pytest -q tests\test_client_ui_acceptance.py::ClientUiInstanceTests
.build-venv\Scripts\python.exe -m pytest -q tests\test_client_ui_acceptance.py::ClientUiUpdateTests
.build-venv\Scripts\python.exe -m pytest -q tests\test_client_ui_acceptance.py::ClientUiDownloadTests
.build-venv\Scripts\python.exe -m pytest -q tests\test_download_ui.py
.build-venv\Scripts\python.exe -m pytest -q tests\test_client_ui_acceptance.py::ClientUiMultiplayerTests
.build-venv\Scripts\python.exe -m pytest -q tests\test_shared_branches_ui.py tests\test_loader_source_ui.py
# 以下用例还需要相邻原生仓库、已构建的 C++ 桥及节点测试依赖
.build-venv\Scripts\python.exe -m pytest -q tests\test_diagnostics_ui.py
```

测试输出按用例写入 `BUGGCRAFT_UI_OUTPUT/<用例名>/`：

- `client-ui-result.json`：断言、操作清单、截图清单和通过状态。
- `actions.jsonl`：鼠标点击、键盘、文本输入和拖动的顺序记录。
- `screenshots/*.png`：每个关键页面的实际渲染结果。
- 更新用例另存 `update-requests.json`：更新检查、取票据、CDN 和源站请求的顺序、通道参数和 User-Agent。
- 下载页专项另存 `catalogue-requests.json` 和 `http-requests.json`：实际搜索/版本请求参数及本机文件传输请求。

测试使用真实页面和真实 Qt 输入链路；游戏目录使用临时文件，内容目录、整合包和联机服务使用本地夹具。目录扫描、下载器、任务页、导入器、控制器和 QML 页面仍走生产路径。历史正版 UI 用例在微软响应处提供设备码及登录结果，本轮排除。首页扩展模块保留生产启动线程和会话管理，通过实际 Python 子进程验证正常退出、异常退出和四进程隔离；真实 Java/Minecraft 启动另由 `tests/test_game_launch_live.py` 在 Windows 选择性执行并保存完整日志。每次测试都会产生可检查的文件、截图和操作日志。

日常测试保留完整 Qt/QML 控件、事件命中与业务处理链，在离屏窗口中验证功能。客户端 UI 自动化统一由 pytest 用例触发，不再保留独立回放脚本。实际游戏启动、多开、网络重连和音频设备输出仍在矩阵中单独列为真实环境用例。

### 不占用桌面的 Qt 输入

`tests/_qml_test_support.py` 使用 `QApplication.sendEvent` 定向投递 `QMouseEvent`，替换公共点击、悬停和拖动助手及各页面原有的 `QTest.mouse*` 调用。键盘继续使用 Qt Test，中文及表情通过输入法提交事件进入真实编辑框；诊断输入不再借用剪贴板。没有直接调用控制器或发射 `clicked` 信号来代替点击，因此禁用控件、遮挡、弹层外点击和拖动仍由 Qt 处理。

`tests/test_qt_input.py` 用真实 QML 控件核对点击一次、禁用不触发、遮挡控件不误触、滑块双向拖动、滚轮和中文输入，并禁止调用 `QCursor.setPos`、`QTest.mouseMove/mouseClick/mousePress/mouseRelease`。每份 `client-ui-result.json` 记录实际 `qt_platform` 和 `mouse_input`。offscreen 模式仍生成截图并验证下载字节、配置落盘、进程状态、诊断 ZIP 与节点回执，沿用原有功能断言。

离屏测试不能代替 Windows 窗口管理、原生标题栏拖动、Explorer 和真实游戏窗口验收。`test_windows_shell_live.py` 只有同时设置 `QT_QPA_PLATFORM=windows` 与 `BUGGCRAFT_DESKTOP_TESTS=1` 才执行；应在独立测试桌面运行。真实游戏用例仍按各自的显式环境开关执行，不放入上面的日常命令。

2026-10-28 输入层回归：Qt 输入 3 项加诊断功能 6 项，共 9 passed，68.10 秒；证据为 `E:\code\.test-tools\pytest-qt-input-diagnostics-20261028.txt` 和 `qt-input-diagnostics-20261028/`。另一次导出与大厅布局冒烟为 59 passed、8 个子测试通过，38.59 秒，日志 `pytest-qt-input-smoke-20261028.txt`。完整页面及关联回归为 141 passed、97 个子测试通过、2 skipped、2 deselected，621.46 秒，退出码 0；桌面专用测试未启用，正版登录按要求排除。

完整页面的 80 份报告全部通过，记录 2023 项功能断言、2872 次操作、171 张截图，均为 offscreen 与 QApplication.sendEvent。产物复核 `E:\code\.test-tools\audit-qt-input-functional-20261028.py` 检查这 80 份报告、6 份诊断报告、两个实际 ZIP 的文件字节与哈希及两节点附件回执，结果见 `qt-input-functional-audit-20261028.json`。首次尝试将交互间隔设为 0 时，实例删除弹窗取消用例失败，保留 `pytest-qt-input-functional-20261028.txt`；正式复跑恢复原有 120 毫秒交互间隔，使用独立日志和输出目录。

## 用例编写和勾选规则

每条用例都记录五件事：前置数据、可见操作、功能结果、异常预期、证据文件。可见操作必须通过鼠标、键盘、文本输入或拖动完成；直接调用控制器只允许准备隔离夹具数据，不能用来代替用户点击。导航用例核对目标页面；设置、下载、安装、启动用例必须核对消费设置后的实际结果，包括文件内容/哈希、网络请求、磁盘持久化、进程、窗口和游戏日志。仅控件选中、截图、函数被调用不能证明相应完整功能通过。

例如 `UI-CLIENT-003` 的步骤是：打开首页联机大厅 → 展开节点下拉并按 Esc → 点击好友 → 搜索好友并切换在线筛选 → 依次打开好友申请、联机邀请、加入申请 → 检查每个页签的操作按钮。预期是大厅、好友窗口和四个页签都能显示，申请/邀请按钮可见且可操作；证据是 `multiplayer-hall.png`、`multiplayer-friends.png`、三个页签截图和 `actions.jsonl`。新功能沿用同样格式，先增加 `[ ]`，全部分支实测通过后才改为 `[x]`。

控件覆盖至少要逐类检查：页面导航、窗口按钮、主按钮、次按钮、禁用按钮、输入框、搜索框、密码/代码输入、下拉框、弹出菜单、复选框、开关、单选项、滑块、列表行、分页/滚动、确认/取消/Esc 弹窗、文件选择、拖放区域、进度/失败/重试/取消按钮。每类都要有正常路径和一个异常或边界路径。

## 已完成项的功能复核（2026-10-27）

本轮重点复核首页、下载和设置已有勾选的测试代码、夹具边界及执行产物，修正以下证据不足的写法并加强断言：

- 选源测试原来替换了 `MinecraftDownloader.urls`，只能证明设置传递与文件传输，无法证明选源真的改变请求。设置专项现保留生产路由及排序，只将网络传输接到本地服务器；核对官方/BMCLAPI 的首个请求、官方失败后自动回退、官方模式禁止回退，以及四类内容的下载主机。
- 整合包原来可能复用前一次下载的归档。现在每个源都清除隔离测试目录中的归档并重新下载、校验文件及核对导入结果，不能以下载游戏元数据代替整合包归档传输。
- Java 大版本原来只检查控件选中。现在逐个点击查询并核对目录函数收到的大版本和下载源；真正的归档下载、解压、版本探测和游戏启动由 GAME-05 验证。厂商公网目录可用性仍不据夹具打勾。
- 真实游戏正常关闭增加实际 `Popen.returncode == 0` 断言并留存，不只读取启动器退出事件。主动停止保留实际返回码，分别记录，不把 Windows 停止返回码 `15` 表述为正常关闭 `0`。
- 真实游戏复跑暴露语言下拉框一次选错，发生于游戏启动前。设置和真实游戏统一使用同一输入辅助方法：鼠标移出弹层后发送键盘操作，提交前核对实际 `highlightedIndex`，失败留截图；仍由真实 UI 事件提交，不直接写入目标值。首次失败记录保留，修正后复跑单独留存。
- 加载器专用下载源、实际浏览器/文件管理器打开、真实游戏启动失败恢复等缺少完整证据的分支保留空框。接口分发、导航和持久化测试保留各自有限的验证范围，不作为整条功能完成证据。

设置与真实结果的逐项对应见 [设置测试的功能结果核对](launcher-settings-test-cases.md#功能结果核对)。公网认证、真实联机传输、音频设备输出和公共源测速不属于上述本地文件与进程结果的证明范围。

## A. 启动、导航和窗口

- [x] 启动器主窗口可见、尺寸有效、QML 无加载错误。
- [x] 开始、下载、设置、实例之间可以用鼠标切换。
- [x] 版本下拉框可以打开，支持键盘上下、Esc 关闭。
- [x] 实例入口可以打开并返回首页。
- [x] 最小化、关闭和侧栏折叠。
- [x] 首次启动教学完成标记在重启后保持，等待首次启动延迟任务后教学仍关闭（HOME-45）。
- [x] 资源缺失、Qt 初始化失败时显示可理解的恢复说明并持久记录日志（HOME-48）；应用创建前的 Windows 原生错误分发单独核对。

## B. 首页、登录和启动游戏

- [x] 离线用户名输入和确认。
- [x] 未登录时点击启动按钮给出“请先设置角色”提示，不提交启动任务。
- [ ] 正版登录 UI：本轮按用户要求不执行；历史夹具测试记录保留在执行记录中。
- [x] 切换账号后清除当前角色，重新输入离线账号后提交新的用户名和 UUID。
- [x] 点击启动游戏时，离线用户名、UUID、离线令牌和当前版本实际到达子进程（HOME-46）；正版分支按要求排除。
- [x] 选择有效版本后的启动表单和版本路径检查；实际 Java/Minecraft 进程见 [真实启动测试用例](launcher-game-launch-test-cases.md)。
- [x] 启动成功后会话卡片、停止按钮和退出状态完整恢复。
- [x] Java 缺失/不兼容、版本 JSON 缺失/损坏、启动参数无法解析时显示具体原因、修复/日志入口，修复后可重新启动（HOME-47）。
- [x] “允许多开”关闭时阻止第二个进程。
- [x] “允许多开”打开时启动四个实例，并且停止菜单只影响选中的会话。

### 首页操作专项用例

以下条目对应 `tests/test_client_ui_acceptance.py::ClientUiHomeTests` 的 4 条自动化方法及新增启动边界测试；本轮排除正版方法。前置条件：完成首次教学；临时游戏目录至少有两个已安装版本；联机响应使用隔离数据。下表也可作为手工操作步骤；完整首页 HOME-01 至 HOME-48 步骤及边界见 [首页测试用例](launcher-home-test-cases.md)。

| 编号 | 点击步骤 | 自动化断言 | 自动化方法（省略 `test_`） / 关键截图 |
|---|---|---|---|
| [x] UI-HOME-001 头部版本切换 | 首页 → 版本 → 点击另一已安装版本 | 弹层关闭；设置、启动版本、首页按钮副标题同步变化 | `home_version_sidebar_and_page_navigation` / `home-version-selected.png` |
| [x] UI-HOME-002 侧栏收起/展开 | 点击头部侧栏按钮 → 再点一次 | 收起时登录选项隐藏；展开后恢复；两次均通过按钮操作 | 同上 / `home-sidebar-collapsed.png` |
| [x] UI-HOME-003 下载/设置/实例切换 | 首页 → 下载 → 设置 → 实例 → 首页 | 每次显示目标页面；返回后仍选中原版本 | 同上 / `home-navigation-0.png` 至 `home-navigation-3.png` |
| [x] UI-HOME-004 实例选择同步 | 实例 → 点击另一实例行 → 首页 | 首页启动版本、头部选择和按钮副标题均切到该实例 | 同上 / `home-instance-switched.png` |
| [x] UI-HOME-005 离线登录与切换账号 | 离线登录 → 输入空格并确认 → 未登录点击启动 → 输入有效名字并确认 → 切换账号 → 输入另一个名字 | 空名字报错；未登录不启动；名字去除首尾空格后显示；切换后清空角色并可重新登录 | `home_offline_login_validation_and_launch_options` / `home-offline-validation.png`、`home-offline-authenticated.png` |
| [ ] UI-HOME-006 正版登录 UI | 正版登录 → 登录按钮 → 复制设备码 → 取消 → 再次登录 → 提供成功认证响应 | 本轮按用户要求不执行 | `home_online_device_login_cancel_and_success`；本轮命令排除 |
| [x] UI-HOME-007 离线游戏启动入口 | 用离线账号点击“启动游戏” | 用户名、UUID、离线令牌及所选版本到达实际子进程；正版分支按要求排除，另见 UI-HOME-006 | `test_coverage_gaps_ui.py::test_offline_identity_and_version_reach_actual_child_command`；证据 `offline-child-arguments.json` |
| [x] UI-HOME-008 大厅/首页好友入口 | 首页联机 → 关闭大厅 → 社交数据已就绪时点首页好友 → Esc | 大厅真实窗口可见；好友入口直达真实好友窗口；关闭好友后主窗口仍可见 | `home_lobby_and_direct_friends_entry` / `home-opened-lobby.png`、`home-opened-friends.png` |

这些勾选只代表上表中的客户端 UI 和参数传递。离线 Minecraft 的真实 Java 命令、窗口、`latest.log`、退出码和四客户端会话已由[真实启动测试用例](launcher-game-launch-test-cases.md)单独验证；微软公网认证按要求未测试，真实节点连接仍未验证，不能由夹具响应推断通过。

首页扩展模块 `tests/test_home_ui.py::HomeChecklistUiTests` 本轮执行 11 条：角色/目录/实例重开恢复、空目录安装后刷新、版本键盘与外部关闭、无节点引导和节点切换、两个实例独立设置隔离、运行中删除保护及目录确认、离线空输入与回车、连续导航及输入保留、好友筛选/页签/未读与空状态、进程退出/崩溃日志/重试、四进程会话停止隔离。另有 1 条正版失败重试方法保留代码但排除执行。该模块的所有步骤、边界和对应清单编号均见首页测试用例文档。

## C. 设置页面

- [x] 下载并发数：可见下拉保存 1/2/4/8/16/32/64；UI 安装游戏测得 1/4 路实际 HTTP 下载，导入补测 1–64 路、房间同步补测 1/2/4 路；默认值、非法值、单文件分段和新任务读取均有断言。见 SETTINGS-06b、D33。
- [x] Minecraft 语言下拉框：整体高亮、打开、选择、回车确认、Esc 取消。
- [x] 自动翻译开关及翻译来源下拉框。
- [x] 联机快捷操作：关闭、首页提示、自动创建或加入。
- [x] 好友/联机提示音开关控制三类通知的系统声音调用，静音保留未读，重复轮询不重播（SETTINGS-10）。
- [ ] 真实扬声器发声（SETTINGS-10a）。
- [x] 启动器透明度滑块拖动和边界值。
- [x] 设置侧栏：通用、Java、关于页面切换。
- [x] 更新通道、检查更新、发现新版本弹窗、失败状态、重试和官网下载回退。
- [x] 游戏及内容下载源各选项、Esc 取消、写盘已验证；缓存迁移功能未接入，保留未完成项。
- [x] 游戏隔离目录、窗口大小、启动器可见性、优先级和调试选项已通过 UI 保存，并由真实游戏验证行为。
- [x] 已列出及自定义 Java 选择、取消、无效文件、真实 Java 版本检测、去重和内存滑块上下限已验证；Java 条目打开目录仍保留未完成项。
- [x] 设置写盘后用新配置对象读取已验证；真实启动测试覆盖设置对命令、窗口和目录的传递。

### 设置关联专项用例

以下 3 条位于 `tests/test_settings_ui.py::ClientUiSettingsTests`，是设置页的基础 UI/模型回归；实际传输和游戏效果由 `tests/test_settings_checklist_ui.py` 与 `tests/test_game_launch_live.py` 分别验证。滚动通过带时间戳的 Qt 滚轮事件完成；开关、下拉、滑块和实例入口均发送鼠标或键盘事件。每条用例保存操作日志、截图和结果 JSON。

| 编号 / 自动化方法（省略 `test_`） | 操作及断言 | 边界与限制 |
|---|---|---|
| [x] UI-SETTINGS-001 / `general_download_sources_multi_open_and_saved_controls` | 多开开关开/关并返回首页；游戏和内容下载源逐项选择；Esc 取消不改变已保存选项；透明度用左右键到 35% 和 100%；新配置对象读回设置 | 本行只验证设置模型和页面关联；真实游戏/内容传输见 `test_settings_checklist_ui.py`，四客户端见真实启动用例 |
| [x] UI-SETTINGS-002 / `global_and_instance_memory_java_and_launch_preferences` | 共享/独立目录解析、已登记 Java 选择、手动内存上下限、可见性/窗口/优先级/调试保存；实例继承时禁用、启用覆盖、停用恢复全局、再启用恢复原值 | 本行只验证设置模型及继承；实际命令、进程、窗口和日志见真实启动用例 |
| [x] UI-SETTINGS-003 / `custom_java_cancel_invalid_file_and_real_runtime_registration` | 自定义 Java 取消、无效文件弹窗、检测本机真实 `java` 版本、重复选择不重复登记；Java 管理点击目录和移除，当前配置回退 | 文件选择器和外部目录打开使用替身；版本检测调用实际可执行文件；真实 Java 启动见真实启动用例；无 Java 时明确跳过 |

这批测试发现并修复了内存和透明度滑块保存后重建控件、丢失键盘焦点的问题；左右键连续操作会断言控件和焦点持续保留。用例已接入打包工作流的 pytest 页面检查，失败时阻止后续打包。

### 自动更新专项用例

以下 7 条均对应 `tests/test_client_ui_acceptance.py::ClientUiUpdateTests` 中的独立 pytest 用例。前置条件：隔离的 Windows 打包版控制器、临时配置和已安装启动器文件；`tests/launcher_update_ui_fixtures.py` 在本机 HTTP 服务上提供清单、票据和包响应。鼠标点击走真实 QML 页面，更新检查、流式下载、源站回退和 SHA-256 校验走生产代码。最终安装交接和浏览器打开被记录，避免替换运行测试的程序。

手工执行时，在隔离测试安装中使用可控更新服务设置表中的响应，再按“操作”列点击。检查页面和文件结果，保留对应截图、操作日志和网络记录。自动化证据位于 `BUGGCRAFT_UI_OUTPUT/test_<下表方法名>/`，每条均生成 `client-ui-result.json`、`actions.jsonl`、`update-requests.json` 和截图。

| 编号 / 自动化方法（省略 `test_`） | 前置响应 | 操作 | 页面及异常预期 | 关键截图 |
|---|---|---|---|---|
| [x] UI-UPDATE-001 / `update_check_failure_and_channel_retry` | 检查接口先返回 503，重试后返回当前已是最新版本 | 设置 → 更新通道选开发版 → 失败弹窗“重试” → 再点“检查更新” | 先显示失败，再显示最新版本；开发版设置保存；首次和重试均带 `channel=beta` | `update-check-failed.png`、`update-settings-latest.png` |
| [x] UI-UPDATE-002 / `update_reminder_and_manual_check_reopens_offer` | 有可用新版本 | 检查更新 → “稍后提醒” → 再次手动检查 → 右上角关闭 | 当前/新版本正确；提醒写盘并可重新读取；手动检查仍弹出新版本；关闭不会下载 | `update-offer.png`、`update-manual-offer.png` |
| [x] UI-UPDATE-003 / `update_ticket_progress_background_and_verified_install` | 票据有效，包下载在中间暂停 | “立即更新” → 检查进度 → 按 Esc → “后台下载” → 恢复传输 | 进度介于 0 和 100%；下载期间关闭和重复检查禁用，Esc 不关闭；后台下载保留主窗口；完整校验后才交给安装器 | `update-downloading.png`、`update-verified-handoff.png` |
| [x] UI-UPDATE-004 / `update_download_failure_retry_gets_new_ticket` | CDN 与源站先同时 503，重试时恢复 | “立即更新” → 错误弹窗“重试” | 失败原因和重试按钮可见；失败保留旧程序并清理临时包；重试重新取票据，使用新 CDN 地址并校验成功 | `update-download-failed.png` |
| [x] UI-UPDATE-005 / `update_cdn_failure_falls_back_to_same_origin` | CDN 503，源站正常 | “立即更新” → 等待完成 | 先尝试 CDN，再自动从同源稳定地址获取；校验后交给安装器；不弹下载错误 | `update-cdn-fallback-verified.png` |
| [x] UI-UPDATE-006 / `update_hash_failure_download_page_and_close` | CDN、源站均返回等长损坏包 | “立即更新” → “官网下载” → 再检查并更新 → “关闭” | 显示 SHA-256 错误；两次失败都保留旧程序、清理临时包、不退出启动器；官网下载打开官方页面；错误关闭后设置页可用 | `update-hash-failed.png` |
| [x] UI-UPDATE-007 / `update_without_ticket_downloads_same_origin` | 旧清单只有同源包地址，无票据字段 | 检查更新 → “立即更新” | 兼容直接下载；不请求票据；保留 `Buggcraft-Launcher` User-Agent；校验成功后才交给安装器 | `update-legacy-url-verified.png` |

这些用例验证 UI 和客户端协议行为。公网 TLS、七牛真实鉴权及安装脚本替换和重启需要另外实测，不能凭本地夹具标成通过。

## D. 版本、实例和文件管理

- [x] 已安装版本列表、当前版本同步到首页版本选择器。
- [x] 游戏版本搜索、筛选、版本安装页面。
- [x] Fabric/Forge/NeoForge/Quilt 组件选择和组件版本列表；版本替换、移除、互斥、换游戏版本及 API 重新选择。
- [x] 实例目录切换和真实目录重新扫描，空目录不会保留原目录列表。
- [x] 实例设置入口打开对应版本设置。
- [x] 打开实例目录及 Java 目录：生产按钮打开真实 Explorer 窗口，通过 Shell COM 核对窗口所在的准确路径；`test_instance_and_java_folder_buttons_open_exact_explorer_directory`。
- [x] 删除实例：确认、取消、实际文件删除和列表移除；删空后清除当前版本。
- [x] 导入 mrpack：选择文件、校验、目标目录、安装任务和完成结果。
- [x] 损坏压缩包、缺少清单、重复实例的错误提示及恢复后重试。
- [ ] 实例移除后首页显示“选择游戏”；版本选择器的所有删除边界仍待补齐。

## E. 下载、模组、资源包、光影和整合包

- [x] 下载分类：游戏、模组、资源包、光影、整合包。
- [x] 每个分类的搜索框、回车搜索、项目列表和项目详情。
- [x] 模组、资源包、光影、整合包版本选择、下载确认和生产下载任务完成。
- [x] 整合包导入表单、文件选择、实例名称输入和返回。
- [x] 搜索清空、筛选下拉框、分页和鼠标滚轮追加加载；四类内容分别执行。
- [ ] 项目版本列表和下载按钮已回归；加载器筛选的独立界面操作仍需核对。
- [x] 模组、资源包、光影真实文件下载完成，校验字节、目标实例目录及历史路径。
- [x] 整合包安装到独立实例并生成覆盖文件；实例列表、头部与首页即时刷新，原实例保留。
- [x] 下载任务进度、完成、失败、取消、重试、排队/并行、去重、历史持久化与重开恢复。
- [x] 首个候选源失败后显示尝试来源与错误，回退到另一 HTTP 源并校验文件；本项使用可控本机源，不证明公网镜像健康。

### 下载页面专项用例

[下载页面测试用例](launcher-download-test-cases.md) 为清单 55 项分别给出操作步骤、预期和证据映射。`tests/test_download_ui.py` 的 29 条方法使用真实主窗口、QML、鼠标/键盘/滚轮/拖放及生产下载和安装任务；检查真实字节、哈希校验、目录、安装元数据、列表刷新、错误与恢复。远端目录与翻译响应使用隔离夹具；文件通过本机 HTTP 实际传输。磁盘满和权限不足只在目标文件写入处注入对应系统异常。记录恢复使用持久化文件重建真实窗口，未完成记录是模拟上次异常终止的测试数据。

本轮发现并修复三处功能错误：失败搜索的重试使用旧关键词；点击任务日志时行模型刷新导致 QML 上下文失效；版本文件首屏失败后“重试加载”没有重新发请求。对应方法分别在四类内容、运行中/失败/历史恢复等场景回归，失败会阻断打包流程。

本轮范围包含原版测试归档安装、四加载器/API 的界面选择、自动/Modrinth/CurseForge 三种来源选择、四类详情与文件搜索、文件真实下载、MRPACK/CurseForge ZIP 导入、下载型整合包的两阶段失败续装、导入取消续装、任务与文件错误恢复。实际 Minecraft 运行、真实加载器/API 联合安装、游戏内启用资源包/光影、公网源可用性和测速仍未由这些夹具证明，对应完整链路不提前勾选。

## F. 联机大厅和好友

- [x] 开头步骤与后续联机房间使用同一套引导卡片层级，设置、标题、重点词和操作按钮均有明确视觉区分。
- [x] 联机房间的 QML 目标短暂不可见时保留可点击、可回车的继续提示，目标重新挂载后恢复高亮。
- [x] 首次教学设置语言、翻译、快捷联机和提示音。
- [x] 教学期间只允许操作当前高亮目标，其他区域点击无效。
- [x] 语言选择整个下拉框高亮。
- [x] 自动、提示等联机设置先普通展示，说明完成后再闪烁演示。
- [x] 好友请求、房间邀请和加入请求使用闪烁与未读角标提示。
- [x] 没有接入码时可查看节点下拉框，但“添加节点”和空房间添加节点按钮锁定。
- [x] 教学完成后关闭联机大厅并返回首页。
- [ ] 接入码添加、编辑、删除、过期和连接失败。
- [ ] 节点选择、节点状态、房间搜索、公开房间加入。
- [ ] 创建房间：世界选择、公开/私密、端口和局域网检测。
- [ ] 加入房间：邀请码、校验失败、连接中、成功和退出。
- [x] 好友列表、好友申请、联机邀请、加入申请和在线状态；每个页签均实际点击并截图。
- [x] 提示音开关控制好友请求、房间邀请和加入请求声音调用、合法 WAV 与未读提醒（SETTINGS-10）。
- [ ] 真实扬声器播放三类提示音（SETTINGS-10a）。
- [ ] 联机大厅关闭后返回首页，后台社交服务生命周期正确。
- [ ] 节点、好友或房间网络中断后的重连、诊断日志和状态恢复。

### 网络日志导出与节点反馈专项

以下六项于 2026-10-28 在 Windows 可见窗口执行通过，随后以不占用桌面的 offscreen/定向 Qt 事件复跑通过；详细前置条件、步骤和边界见 [DIAG-01 至 DIAG-06](launcher-diagnostics-test-cases.md)。使用真实生产导出器、C++ 桥和两个隔离节点，不向线上节点发送测试反馈。

| 完成 | 用例 | 必须出现的功能证据 |
| --- | --- | --- |
| [x] | DIAG-01 本地导出 | 实际保存对话框输入路径，ZIP 含新网络快照、Windows 接口/路由/DNS/网关、游戏日志及 P2P 记录；校验哈希、字节数、脱敏与设置排除 |
| [x] | DIAG-02 确认后自动采集上传 | 中文、换行及表情逐字到达真实节点；一条反馈和一个附件；管理员与另一联邦节点实际下载相同字节，匿名请求 401 |
| [x] | DIAG-03 取消和匿名 | 标题/描述/确认框分别取消、Esc、关闭均不采集、不上传，大厅保持可见；重复点击不重复上传，匿名入口禁用 |
| [x] | DIAG-04 真实认证拒绝与重试 | 无效凭据经实际 SSH 拒绝，显示失败且不伪报反馈编号；恢复凭据后同一入口提交成功 |
| [x] | DIAG-05 取消导出 | 保存框取消、Esc、关闭均不生成网络快照或 ZIP，不创建节点反馈 |
| [x] | DIAG-06 输入约束 | 空白/超长标题、超长描述和中文 UTF-8 字节超限由实际异步任务拒绝，采集前失败 |

原生弹窗取消回归发现大厅 QML 的 Esc 快捷键先抢走原生对话框按键，误关大厅；已在原生子弹窗的快捷键覆盖阶段修复，并验证大厅自身的 Esc 仍正常工作。该组只运行被动网络采集，公网 STUN/P2P、线上节点部署与正版登录不由这六项推定完成。

## G. 控件级覆盖

- [x] ActionButton：普通、主按钮、禁用、点击反馈。
- [ ] ChoiceBox：鼠标打开、键盘上下、回车、Esc、禁用选项和弹层边界。
- [x] 开关/复选框：点击、保存、禁用状态。
- [ ] 单选框：互斥选择、键盘操作和重载恢复。
- [ ] 输入框：输入、删除、全选、复制粘贴、最大长度和非法输入。
- [ ] 内存及透明度滑块：点击、左右键、上下限、保存及焦点保持；其他滑块和显示文本边界仍需补齐。
- [ ] 列表：行点击、滚动、分页、空状态、加载状态和错误状态。
- [ ] 弹窗：确认、取消、Esc、遮罩、焦点和关闭后的状态。
- [x] 拖放：整合包拖到主窗口和 QML 子控件上方，读取信息并通过表单完成真实导入。

## H. 已提交问题回归

- [x] `UI-ONBOARD-001`：教程期间误点节点入口不会进入联机节点页面。
- [ ] `UI-SOUND-001`：开关和社交通知声音路径已回归，真实扬声器输出待设备测试。
- [x] `UI-ONBOARD-002`：教学完成后关闭联机大厅并回到首页。
- [x] `UI-CLIENT-001`：pytest 直接触发真实客户端可见 UI 用例，输出截图、操作日志和结果 JSON。
- [x] `UI-CLIENT-002`：真实下载任务覆盖游戏、模组、资源包、光影、整合包和 mrpack 导入。
- [x] `UI-CLIENT-003`：真实联机大厅和好友窗口覆盖节点下拉、好友列表、好友申请、联机邀请、加入申请。
- [x] `UI-CLIENT-004`：自动更新 7 条点击式 UI 用例，覆盖检查/重试、提醒、下载进度与后台下载、新票据重试、CDN 回源、损坏包拒绝安装和旧版同源地址兼容；保存截图、操作日志及请求记录。
- [ ] `UI-CLIENT-005`：该汇总项仍包含正版登录分支，因此保持未完成；离线启动参数、教学重启、启动失败恢复和资源错误页分别按 HOME-45 至 HOME-48 的独立证据核对。
- [x] `UI-CLIENT-006`：实例管理 2 条点击式 UI 用例，覆盖版本选择、目录入口、版本设置、增加/切换目录、空列表、安装入口，以及取消删除、连续删除和删空返回首页。
- [x] `UI-CLIENT-007`：设置专项 10 条加原有设置关联 3 条，覆盖设置模型/继承、生产选源与实际传输、滑块、真实 Java 检测和移除；真实游戏效果另见 `test_game_launch_live.py`。
- [x] `UI-CLIENT-008`：原下载专项 32 条与 7 条共用分支、1 条加载器选源的 Windows 可见合跑为 40 passed、72 个子测试通过。此次新增 API 文件安装、导入权限恢复两项并定向通过，现共 34 条下载方法；不把历史合跑记作新增 34 条全量通过。

## C++ 桥与旧实现移除验收

旧 Python 联机传输、兼容目录、RTC vendoring 工具及依赖已移除。旧测试不再导入 `tunnel`、AsyncSSH、Python ICE/WebRTC 或旧 `hookup.relay/host/client`；`hookup` 保留的是调用 C++ 桥的生产适配层。新增边界测试防止旧实现被重新引入。

```powershell
.build-venv\Scripts\python.exe -m pytest -q tests\test_native_cutover.py tests\test_native_bridge_runtime.py tests\test_native_bridge_services.py
```

`test_native_bridge_runtime.py` 分别启动真实 DLL/EXE，验证初始化为 C++、错误后继续请求、并发调用及关闭重启。`test_native_bridge_services.py` 在独立进程运行原生仓库的 4 条真实节点验收：接入码、房间/聊天、完整模组清单与哈希、禁止中转传文件时游戏仍可收发、个人码及社交签名。它使用当前原生仓库的管理层测试环境，管理层的 Python `tunnel` 不是旧客户端传输实现。两项集成测试缺少构建或依赖时会明确 skip，不能据此勾选通过；也不代表 Minecraft 或公网 NAT 已验收。

## 本轮执行记录

| 日期 | 范围 | 证据 | 结果 |
|---|---|---|---|
| 2026-10-28 | 清单补测后的启动/日志相邻回归 | `E:\code\.test-tools\pytest-checklist-launch-related-verified-20261028.txt` | 29 passed、6 subtests passed，10.85 秒，退出码 0；首次旧夹具缺少版本 JSON 导致会话测试失败，补充有效元数据后复跑通过，保留首次失败日志。覆盖多开/单独停止、冻结配置、启动前命令、继承版本、日志与诊断 |
| 2026-10-28 | 本轮清单缺口定向功能回归 | `E:\code\.test-tools\pytest-checklist-gaps-final-20261028.txt`；`checklist-gaps-final-20261028/` | 12 passed、9 subtests passed，34.21 秒，退出码 0；教学重启、离线参数、Java/版本/参数错误恢复、Qt 错误页与日志、API 文件安装、权限/损坏/无清单导入恢复、三类通知声音调用通过。未执行正版登录、真实节点全链路或扬声器实听 |
| 2026-10-28 | 定向 Qt 输入完整页面及关联回归 | `E:\code\.test-tools\pytest-qt-input-functional-verified-20261028.txt`；`qt-input-functional-verified-20261028/`；`qt-input-functional-audit-20261028.json` | 141 passed、97 subtests passed、2 skipped、2 deselected，621.46 秒，退出码 0；80/80 页面报告通过，2023 项记录断言、2872 次操作、171 张截图；覆盖首页、下载、设置、共用分支、加载器选源、教学及关联 QML；2 条桌面验收未启用，2 条正版登录未执行 |
| 2026-10-28 | 定向 Qt 输入与诊断功能离屏回归 | `tests/test_qt_input.py`、`tests/test_diagnostics_ui.py`；`E:\code\.test-tools\pytest-qt-input-diagnostics-20261028.txt`；`qt-input-diagnostics-20261028/` | 9 passed，68.10 秒，退出码 0；6 份诊断报告均记录 offscreen 与 QApplication.sendEvent，130 项断言、66 次操作、3 张截图；真实 ZIP、两节点附件取回及中文元数据验证通过；输入专项核对禁用、遮挡、拖动、滚轮和输入法事件 |
| 2026-10-28 | 定向 Qt 输入导出与大厅冒烟 | `E:\code\.test-tools\pytest-qt-input-smoke-20261028.txt` | 59 passed、8 subtests passed，38.59 秒，退出码 0；离屏执行导出与大厅布局回归 |
| 2026-10-28 | 网络日志导出与节点反馈 Windows 可见回归 | `tests/test_diagnostics_ui.py`；`E:\code\.test-tools\pytest-diagnostics-ui-verified-20261028.txt`；`diagnostics-ui-verified-20261028/` | 6 passed，70.40 秒，退出码 0；6/6 报告通过，130 项记录断言、66 次操作、3 张截图；真实导出、实际 C++ SSH 上传、两节点管理员取回附件、中文元数据、拒绝认证后重试、取消/Esc/匿名和输入限制均通过 |
| 2026-10-28 | 共用分支、完整下载页及加载器选源 Windows 可见回归 | `tests/test_shared_branches_ui.py`、`tests/test_download_ui.py`、`tests/test_loader_source_ui.py`；`E:\code\.test-tools\pytest-shared-download-verified-20261028.txt`；`shared-download-verified-20261028/` | 40 passed、72 subtests passed，294.37 秒，退出码 0；40/40 报告通过，覆盖实际配置写入、任务/文件、五类下载任务和 Fabric/Quilt 选源传输；不据此推定公网服务可达或已完成全部加载器的实际游戏启动 |
| 2026-10-28 | 日志、反馈与联机直接依赖回归 | `E:\code\.test-tools\pytest-diagnostics-related-verified-20261028.txt` | 123 passed、47 subtests passed，27.91 秒，退出码 0；包含反馈上传、连接诊断、NAT/P2P 证据、原生适配、好友入口/目录及大厅布局/打开 |
| 2026-10-28 | 原生桥与实际节点反馈协议 | 相邻原生仓库 `compatibility/tests/test_feedback_native.py`；`E:\code\.test-tools\pytest-native-feedback-20261028.txt` | 4 passed，29.07 秒，退出码 0；实际 SSH 传输、私有管理附件、联邦取回、拒绝未同意/超限和截断传输；保留现有 aiohttp NotAppKeyWarning 一项，不报成零告警 |
| 2026-10-28 | 打包诊断预检与最终产物复核 | `E:\code\.test-tools\unittest-diagnostics-preflight-20261028.txt`；`diagnostics-functional-audit-20261028.json` | 工作流相同 unittest 模块调用 35 条通过；46 份 UI 报告全部通过，两份实际 ZIP 清单逐文件字节/SHA-256 及真实节点回执复核通过 |
| 2026-10-27 | 下载页专项无窗口回归 | `tests/test_download_ui.py`；`E:\code\.test-tools\pytest-download-checklist-final.txt`、`pytest-download-checklist-final-exit.json`；`download-checklist-final/` | 28 passed、52 subtests passed，220.52 秒，退出码 0；28/28 报告 `passed=true`，993 次操作、59 张截图 |
| 2026-10-27 | 下载页专项 Windows 可见鼠标/键盘/滚轮/拖放回归 | `E:\code\.test-tools\pytest-download-ui-windows.txt`、`pytest-download-ui-windows-exit.json`；`download-ui-windows/` | 28 passed、52 subtests passed，220.03 秒，退出码 0；28/28 报告 `passed=true`，996 次操作、59 张截图 |
| 2026-10-27 | 目标实例删除后的恢复补充验证 | `E:\code\.test-tools\pytest-download-target-recovery-offscreen.txt`、`pytest-download-target-recovery-windows.txt` 及对应 `-exit.json`；`download-target-recovery-offscreen/`、`download-target-recovery-windows/` | 两种模式分别 1 passed、27 deselected、3 subtests passed，11.12/12.11 秒，退出码均为 0；实例失效拒绝提交，恢复并重新选择后目标、路径和下载按钮重新有效 |
| 2026-10-27 | 下载核心与关联页面回归 | `E:\code\.test-tools\pytest-download-related.txt`、`pytest-download-related-exit.json`；`download-related-ui/`。范围：内容下载、传输、工作线程、确认弹窗、加载器目录/选择、任务 QML、原 UI 验收、首页、设置和教学 | 130 passed、2 deselected、11 subtests passed，266.76 秒，退出码 0；两条正版登录未执行 |
| 2026-10-27 | 首页清单专项及关联回归，排除正版登录 | `E:\code\.test-tools\pytest-home-checklist-final.txt`、`pytest-home-checklist-final-exit.json`；`home-checklist-final/` | 52 passed、2 deselected、5 subtests passed，214.84 秒，退出码 0；29 条 UI 用例及 23 条教学用例通过。两个正版方法未执行 |
| 2026-10-27 | 首页及实例 Windows 可见鼠标/键盘回放，排除正版登录 | `E:\code\.test-tools\pytest-home-windows-offline.txt`、`pytest-home-core-windows-offline.txt` 及各自的 `-exit.json`；`home-ui-windows-offline/` | 首页扩展与实例 13 passed、1 deselected；原有首页 3 passed、1 deselected；16/16 报告 `passed=true`，180 项记录断言、227 次操作、35 张截图；本轮可见日志未出现下述历史初始化异常输出，不能据此认定历史根因已解决 |
| 2026-10-27 | pytest 客户端 UI 验收用例 | `tests/test_client_ui_acceptance.py`；`E:\code\.test-tools\client-ui-pytest-final\`、`E:\code\.test-tools\client-ui-pytest-visible-final\` | 导航/设置、下载/整合包、联机/好友 3/3 通过；无窗口和 Windows 可见模式均生成 JSON、操作日志和截图 |
| 2026-10-27 | 历史 Windows 可见客户端 UI 回放 | `E:\code\.test-tools\client-ui-windows-final\client-ui-result.json`；28 张截图；`actions.jsonl` | 393 项断言、82 次鼠标/键盘/输入操作，`passed=true`；对应独立回放脚本已移除，后续统一从 pytest 触发 |
| 2026-10-27 | 客户端 UI、教学、设置声音、联机大厅 Qt 回归 | `tests/test_client_ui_acceptance.py`、`tests/test_onboarding.py`、`tests/test_launcher_qml.py`、`tests/test_lobby_layout.py`、`tests/test_lobby_opening.py` | 121 passed，16 个子测试通过 |
| 2026-10-27 | 启动器更新 UI 回归（无窗口） | `tests/test_client_ui_acceptance.py::ClientUiUpdateTests`；`E:\code\.test-tools\client-ui-pytest-update\` | 7/7 通过；真实下载和校验路径；保存截图、操作日志、请求记录和结果 JSON |
| 2026-10-27 | 完整客户端 UI Windows 可见回放 | `tests/test_client_ui_acceptance.py`；`E:\code\.test-tools\client-ui-pytest-update-visible\` | 10/10 通过；113 项断言、67 次鼠标/键盘操作、24 张截图；各用例结果 JSON 均为 `passed=true` |
| 2026-10-27 | 更新控制器与下载协议回归 | `tests/test_launcher_updates.py`、`tests/test_update_client.py` | 19 passed，4 个子测试通过 |
| 2026-10-27 | 补齐首页后的完整客户端 UI 回归（无窗口） | `tests/test_client_ui_acceptance.py`；`E:\code\.test-tools\client-ui-pytest-home-full\` | 16/16 通过；171 项记录断言、122 次操作、45 张截图；新增首页 4 条均通过 |
| 2026-10-27 | 首页 Windows 可见回放及凭据保存检查 | `ClientUiHomeTests`；`E:\code\.test-tools\client-ui-pytest-home-visible\`；复跑日志 `E:\code\.test-tools\client-ui-pytest-home-visible-repeat.log` | 两轮各 4/4 断言通过、退出码 0；最终每轮记录 38 项断言、34 次操作、15 张截图；窗口初始化出现 `0x8001010d` 异常输出，不能记为全程无异常 |
| 2026-10-27 | C++ DLL/EXE 与本机真实节点 | `tests/test_native_bridge_runtime.py`、`tests/test_native_bridge_services.py`；`E:\code\.test-tools\native-bridge-services\native-services.log` | 3 条 pytest 通过，其中节点验收执行原生仓库的 4 条测试；未使用旧客户端传输 |
| 2026-10-27 | 实例管理 Windows 可见操作 | `tests/test_client_ui_acceptance.py::ClientUiInstanceTests`；`E:\code\.test-tools\client-ui-native-visible\` | 2/2 通过；实际临时目录扫描/删除、确认/取消及首页状态均有断言和截图 |
| 2026-10-27 | 移除旧 Python 联机实现后的 Windows 全量 pytest | `E:\code\.test-tools\pytest-native-cleanup-final.txt` | 655 项收集成功；654 passed、1 skipped、158 subtests passed。唯一跳过项需要 Linux ELF 工具链；15 个旧 `tunnel` 收集错误已消失 |
| 2026-10-27 | 移除旧实现后的原生 C++ 测试 | `minecraft-tunnel-native/build` | `ctest --test-dir build --build-config Release --output-on-failure`：3/3 通过 |
| 2026-10-27 | 本轮全量回归中的客户端可见 pytest | `tests/test_client_ui_acceptance.py`；`E:\code\.test-tools\client-ui-native-cleanup-final\` | 16/16 用例通过；173 项断言、122 次可见操作、45 张截图；16/16 报告 `passed=true` |
| 2026-10-27 | 删除独立脚本后的可见 UI、教学、好友及原生边界回归 | `E:\code\.test-tools\pytest-ui-only-final.txt`、`pytest-ui-only-exit.json`；`client-ui-pytest-only-final/` | 48 passed、5 subtests passed，进程退出码 0；Windows `0x8001010d` 输出仍复现，保留待排查 |
| 2026-10-27 | 设置页点击式回归及内容源实际传输 | `tests/test_settings_checklist_ui.py`、`tests/test_settings_ui.py`、`tests/test_installation_receipt.py`；`E:\code\.test-tools\settings-checklist-offscreen-final2\` | 设置入口、来源选择、实际游戏/内容传输、Java 管理、关于和实例继承均有 QML 点击证据；缓存迁移、提示音和 Java 打开目录保持未完成 |
| 2026-10-27 | 功能复核后的 Windows 可见选源/Java 查询/链接分发回归 | `E:\code\.test-tools\pytest-settings-functional-audit-windows.txt`；`settings-functional-audit-windows/` | 4 passed、17 subtests passed，退出码 0；保留生产选源逻辑，核对实际传输主机及回退、每个 Java 大版本查询参数、快捷链接完整 URL；公共源测速输入为固定值 |
| 2026-10-27 | 功能复核后的完整设置关联回归（无窗口） | `E:\code\.test-tools\pytest-settings-functional-audit-offscreen.txt`；`settings-functional-audit-offscreen/` | 16 passed、20 subtests passed，154.19 秒，退出码 0；13 份 UI 报告均通过，另含 3 条安装回执回归 |
| 2026-10-27 | 统一下拉框输入后的完整 Windows 可见设置回归 | `E:\code\.test-tools\pytest-settings-functional-audit-windows-final.txt`；`settings-functional-audit-windows-final/` | 16 passed、20 subtests passed，151.93 秒，退出码 0；13 份 UI 报告全部通过，另含 3 条安装回执回归；结果索引 `E:\code\.test-tools\launcher-functional-test-audit.json` 核对报告、实际游戏返回码及无遗留测试 Java PID |
| 2026-10-27 | 实际 JVM 返回码复核首次运行 | `E:\code\.test-tools\pytest-real-game-functional-audit.txt`；`real-game-functional-audit/` | 首页、实例覆盖、下载 Java 后启动 3 条通过；语言选择在启动前失败，运行退出码 1，未把该轮记为全部通过 |
| 2026-10-27 | 统一下拉框输入后的真实游戏复跑 | `E:\code\.test-tools\pytest-real-game-functional-audit-fixed.txt`；`real-game-functional-audit-fixed/` | 语言/隔离/Java/内存和窗口/优先级/调试 2 passed、4 deselected，201.34 秒，退出码 0；与上轮通过的 3 条合计复核 5 条真实游戏方法，10 次正常关闭均核对实际 JVM 返回码 0；英语和简体中文主菜单截图已查看 |
| 2026-10-27 | 真实 Java/Minecraft 启动与四客户端会话 | `tests/test_game_launch_live.py`；`E:\code\.test-tools\real-game-settings\`；[真实启动用例](launcher-game-launch-test-cases.md) | 6/6 真实启动方法通过；实际 1.21.8 窗口、Java 命令、`latest.log`、退出码和 4 客户端单独停止均有证据；正版/Microsoft 登录未测试 |
| 2026-10-27 | 剪贴板占用回归 | `tests/test_clipboard.py`、`test_chat_controller.py`、`test_room_launch_flow.py`；`E:\code\.test-tools\pytest-clipboard-fixed.txt` | 72 passed、11 subtests passed；复制在短暂占用后重试、持续占用有失败上限、新复制取消旧任务、关闭取消任务；好友码与邀请码仍校验完整内容 |
| 2026-10-27 | 旧联机实现移除后的最终 Windows 全量回归 | `E:\code\.test-tools\pytest-cpp-verified.txt`、`pytest-cpp-verified-exit.json` | 669 项收集成功；668 passed、1 skipped、162 subtests passed，426.41 秒，进程退出码 0；跳过项需要 Linux ELF 工具链，无收集错误 |
| 2026-10-27 | 最终全量回归中的可见 UI 操作 | `E:\code\.test-tools\client-ui-cpp-verified\`；包括 `test_client_ui_acceptance.py`、`test_settings_ui.py` 和 `test_home_ui.py` | 26/26 报告 `passed=true`；287 项记录断言、373 次鼠标/键盘操作、59 张截图；保留真实游戏、扬声器和 Windows 异常输出的未完成说明 |
| 2026-10-27 | 内容类别切换时旧搜索响应回归 | `tests/test_download_ui.py::DownloadChecklistUiTests::test_parallel_search_ignores_stale_results_for_every_kind`；`E:\code\.test-tools\shared-branch-stale-response-windows\`、`shared-branch-stale-response-offscreen\` | Windows 可见及 offscreen 各 1 passed、4 个子测试通过；四类内容中，较慢搜索晚于类别切换返回时，当前类别和结果均保持正确；两个 pytest 进程退出码均为 0 |
| 2026-10-27 | 共用分支定向 Windows 可见回归 | D13、D29；`E:\code\.test-tools\pytest-shared-branches-windows.txt`；`shared-branches-windows/` | 2 passed、12 subtests passed，26.16 秒，退出码 0；覆盖四类内容的旧搜索、来源和类别切换，以及详情加载中返回后的成功/错误响应 |
| 2026-10-28 | 共用分支功能回归（无窗口） | `tests/test_shared_branches_ui.py`；`E:\code\.test-tools\shared-branches-20261028-expanded3\` | 设置取消/禁用、首页启动拦截、通知未读和快捷联机分别核对配置、任务、进程或动作结果；正版验证未执行 |
| 2026-10-28 | Windows 原生窗口与文件夹功能 | `tests/test_windows_shell_live.py`；`E:\code\.test-tools\shared-branches-20261028-shell\` | Explorer 实际打开实例/Java 目录；最小化、恢复、标题栏拖动、关闭重开均通过 |
| 2026-10-28 | 真实原版及可运行整合包链路 | `tests/test_game_launch_live.py`；`E:\code\.test-tools\pytest-shared-runnable-pack-20261028.txt`、`shared-branches-20261028-real-game/` | 原版真实下载/启动、MRPACK 下载与导入各启动并确认资源加载；JVM 失败/异常退出日志与修复重启通过 |
| 2026-10-28 | 五类下载任务与导入边界首次回归 | `tests/test_download_ui.py`；`E:\code\.test-tools\pytest-shared-20261028-full-offscreen.txt`、`pytest-shared-input-boundary-windows-20261028.txt` | 首次无窗口合跑 1 failed、65 passed，未记为整轮通过；名称边界输入焦点修正后 Windows 定向通过，最新完整 Windows 合跑结果见 40 passed 的记录 |
| 2026-10-27 | 收紧异步等待后的完整下载无窗口回归 | `E:\code\.test-tools\pytest-shared-branches-download-full-offscreen-final.txt` 及对应 `-exit.json`；`shared-branches-download-full-offscreen-final/` | 29 passed、60 subtests passed，198.12 秒，退出码 0；29/29 报告通过，71 张截图 |
| 2026-10-27 | 收紧异步等待后的完整下载 Windows 可见回归 | `E:\code\.test-tools\pytest-shared-branches-download-full-windows-final.txt` 及对应 `-exit.json`；`shared-branches-download-full-windows-final/` | 29 passed、60 subtests passed，199.39 秒，退出码 0；新增断言检查旧响应实际回调后的结果，未将线程退出误当作回调已处理 |
| 2026-10-27 | 旧响应保护的故障注入验证（预期失败） | `E:\code\.test-tools\check_stale_guard_mutation.py`、`pytest-shared-branches-mutation-expected-failure.txt` 及对应 `-exit.json` | 独立进程临时移除 `_query_finished` 的旧请求判断，保留原函数及 Qt 绑定；12 个子测试均在旧搜索覆盖或返回后的状态改写断言失败，13.52 秒，退出码 1。生产文件未改；不计为正常通过 |

本次可见回放的实际产物包括：安装 `1.21.8` 的元数据和客户端归档；四类内容下载任务完成；mrpack 导入任务完成并写入 `ui-fixture-import/config/ui-acceptance.json`；联机大厅和好友窗口各页签均有截图。真实启动回归另外保存实际 Java/Minecraft 窗口、`latest.log`、启动命令和退出码；它不覆盖正版授权、真实节点连接或音频设备输出。

历史 Windows 首页可见回放的异常输出发生于 `LauncherQmlCase.setUp()` 显示窗口后第一次事件处理，早于首页操作；当时两轮均复现，但测试仍完成。当前仅确认发生位置，未确认底层原因，保留原始日志作为待排查项。历史设备码弹窗截图保留，不计入本轮正版验收。本轮另检查首页、版本、实例独立设置、删除确认/运行中保护、大厅表单、好友空状态及崩溃日志截图；无窗口模式的默认字体出现方框，不作为中文字体呈现通过证据。

## 整合包与日志新增验收（2026-10-28）

| 状态 | 功能 | 自动化方法与通过标准 |
| --- | --- | --- |
| [x] | 日志搜索、级别、分类、来源、堆栈高亮、暂停、复制、导出 | tests/test_game_log_ui.py；真实 Qt 输入事件，断言筛选数据、导出文件和恢复后的缓冲 |
| [x] | 内容源优先、慢源不抢跑 P2P、未直连禁止房主下载 | tests/test_room_mod_installation.py；验证下载顺序、实际文件字节与失败不发布实例 |
| [x] | 精简/常规导出和静态导入校验 | tests/test_modpack_import.py、test_instance_modpack_entry.py；模组/资源包/光影、修改内容内置、隔离共享边界 |
| [x] | 两种 BUGGPACK 经 UI 导出、UI 导入并启动实际游戏 | tests/test_game_launch_live.py::RealMinecraftUiTests::test_buggpack_export_both_modes_import_and_launch_real_game；实际 JVM、资源包加载与新日志窗口；1 passed，截图与游戏日志：`E:\code\multiplayer-tests\incident-20261028\pack-roundtrip-fixed\test_buggpack_export_both_modes_import_and_launch_real_game\` |
| [x] | 四个真实游戏客户端联机操作 | tests/test_four_game_multiplayer_live.py；四个可见游戏进程经生产 C++ 节点进房、移动、方块同步、聊天、死亡重生、重连和 30 秒稳定性检查；报告：`E:\code\minecraft-tunnel-native\validation-artifacts\vanilla-20261028-020535\report.json` |

## 本轮最终验证补充（2026-10-28）

| 范围 | 证据 | 结果 |
| --- | --- | --- |
| Windows 客户端全量 pytest | `E:\code\buggcraft\build\full-tests-final.xml`、`full-tests-final.log` | 770 passed、18 skipped、279 subtests passed；跳过项为环境门控用例 |
| Windows 可见 UI 全量回放 | `E:\code\buggcraft\build\client-ui-visible-final.log`、`E:\code\.test-tools\client-ui-20261028-final\` | 214 passed、3 deselected、113 subtests passed；3 条需在线账户/节点的用例未执行 |
| 四客户端真实联机 | `E:\code\minecraft-tunnel-native\validation-artifacts\vanilla-20261028-020535\report.json` | 4 个实际 Minecraft 1.21.8 客户端完成进房、移动、方块、聊天、死亡重生和重连验证；1 passed |
| 两台已部署节点公网验收 | `E:\code\minecraft-tunnel-native\build\production-native-20261028-pack-sync\public-acceptance.json`、`public-acceptance.log` | 4/4；HTTPS 与权限、跨节点发现/1 MiB 双向游戏传输、SSH 拒绝错误凭据/主机密钥、UDP/STUN 全部通过；两台目标节点在线，保留历史离线配置 |
| 原生 C++ 全量套件 | `E:\code\minecraft-tunnel-native\build\full-native-tests-recheck.xml`、`full-native-tests-recheck.log` | 170 passed、11 skipped、1303 subtests passed，826.99 秒；1 项 aiohttp 建议告警。此前压力运行中丢包恢复用例曾间歇超时，定向复测与本轮全量复测通过，仍应关注稳定性 |
| 原生协议兼容套件 | `E:\code\minecraft-tunnel-native\build\compatibility-final.log` | 40/40 通过，131.27 秒，验证真实 C++ 核心的协议兼容边界 |
| Web 文档构建、测试与线上资源 | `E:\code\minecraft-tunnel-native\build\developer-docs-build-final.log`、`developer-docs-test-final.log`、`production-native-20261028-pack-sync\public-acceptance.json` | Vue/TypeScript 生产构建通过；Vitest 4 个文件、10 项通过；已部署两台节点的开发文档页面及其构建 JS 均验证包含 2026-10-28 更新、`.buggpack` 和资源包说明 |
| 整合包、日志与联机内容定向 UI 回归 | `E:\code\buggcraft\build\pack-log-sync-final.xml`、`pack-log-sync-final.log` | 44 passed、17 subtests passed，18.39 秒；整合包导入、日志 UI、公开源优先/P2P 限制与可选资源同步通过 |

## 房间准备与玩家管理新增范围（2026-10-28）

已实现锁定实例、成员准备进度、聊天优先布局、安装日志、玩家日志授权和成员管理。完整场景及实机边界见[房间准备验收记录](room-preparation-workflow.md#9-本次实现与验证边界)，不能由一个页面截图推定全部 21 个长流程通过。

| 自动化测试入口 | 实际验证 | 证据 |
| --- | --- | --- |
| `test_room_lobby_ui.py` | 721×505 与 1000×650、聊天默认、长名单分页、菜单确认/取消、日志搜索分类/级别、允许/拒绝/撤回和房主日志弹窗；后台使用夹具 | `build/room-final-ui-verified.log/xml`（含控制器共 13 passed） |
| `test_room_preparation_controller.py` | 绑定实例目录、自动关联兼容世界与多世界选择、通知去重、日志脱敏与界限、旧任务/倒序快照隔离 | 同上；控制器验证不替代实际 JVM 目录交叉切换 |
| `test_room_lobby_live_ui.py` | 真实 C++ 节点、双桥会话和发布 QML；鼠标键盘聊天、请求/允许/撤回脱敏日志、双方确认转让，检查实际节点结果 | `build/room-live-ui.log/xml`，1 passed；外壳和账号为隔离夹具 |
| `test_download_ui.py::DownloadChecklistUiTests::test_every_download_kind_passes_waiting_running_and_completed_with_real_files` | 游戏核心、模组、资源包、光影、整合包真实 HTTP 下载；等待/传输/完成、可见进度和正速度 | `build/room-download-speed-final.log/xml`，1 passed |
| 原生 `test_room_lobby.py` | 真实核心和桥进程，进度序号、配置指纹、越权拒绝、踢出/解禁/重入、转让不打断游戏字节流、日志授权与批次原子校验 | 原生全量 `build/room-native-verified.log/xml`，176 passed、11 skipped |
| `test_four_game_multiplayer_live.py`，显式 `BUGGCRAFT_FOUR_GAME_LIVE=1` | 四个真实 JVM/窗口，同世界移动/方块/聊天、死亡重生、重连、转让管理后继续游戏 | `build/room-four-games-final.log/xml`，1 passed；原生 `validation-artifacts/vanilla-20261028-115739/` |

效果图在 `build/room-preparation-ui/`，含 `room-default-chat.png`、`preparation-room-721.png`、`room-install-logs.png`、`real-node-authorized-logs.png` 和 `real-node-transferred-manager.png`。四游戏验收使用已经安装的原版实例，不等同于三个客机从零下载。真实音频、全屏通知、公网混合 P2P/中转和四启动器全新安装仍需独立实测。历史离屏混跑 `0xc0000374` 没有记为已修复；本轮 Windows 软件渲染顺序运行。

## 下载并发设置专项（2026-10-28）

入口为“设置 → 通用设置 → 下载并发数”，默认 32，可选 1/2/4/8/16/32/64；按每个新下载任务限制文件并行数。游戏依赖、整合包导入、内容下载和房间同步共用该配置；批量下载不叠加分段，单文件分段最多 4 路且服从设置，设为 1 时关闭分段。最多 4 个独立下载任务的队列规则单独保持。

| 范围 | 证据 | 结果 |
| --- | --- | --- |
| 核心下载、导入、房间同步、设置持久化和 Java 下载回归 | `build/download-concurrency-core.xml`、`download-concurrency-core.log`；`test_download_concurrency.py` 等 9 个测试模块 | 94 passed、62 subtests passed，50.54 秒，退出码 0；本地真实 HTTP 下载并校验文件，导入覆盖 1–64 路，房间公开源大文件覆盖 1/2/4 路且不叠加 Range；无 P2P 直连也可从源完成同步 |
| 原有 QML 页面、首次教学与打包边界回归 | `build/download-concurrency-related.xml`、`download-concurrency-related.log`；`test_launcher_qml.py`、`test_onboarding.py`、`test_slim_packaging.py` | 58 passed、16 subtests passed，78.47 秒，退出码 0；offscreen 模式确认新设置加入后原有页面/教学逻辑仍通过，中文视觉另由 Windows 截图检查 |
| 首轮完整设置/下载 Windows 可见回归 | `build/download-concurrency-ui.xml`、`download-concurrency-ui.log`；`E:\code\.test-tools\download-concurrency-ui-final-20261028/` | 1 failed、46 passed、88 subtests passed，405.04 秒；模组文件滚轮翻页一次失败，不记为全轮通过。设置七档保存、1/4 路 UI 安装实传均通过 |
| 滚轮目标坐标修正后的四类分页定向回归 | `build/download-concurrency-pagination.xml`、`download-concurrency-pagination.log`；`download-concurrency-pagination-recheck-20261028/` | 1 passed、31 deselected、4 subtests passed，20.97 秒；每次滚动重新定位异步布局后的列表区域，保持真实滚轮操作；追加失败时保存截图和滚动位置，未降低结果断言 |
| 最终完整设置/下载 Windows 可见回归 | `build/download-concurrency-ui-verified.xml`、`download-concurrency-ui-verified.log`；`E:\code\.test-tools\download-concurrency-ui-verified-20261028/` | 46 passed、89 subtests passed，401.25 秒，退出码 0；46/46 UI 报告通过，包含七档并发保存、实际 1/4 路游戏安装、全部四类分页、下载/导入、取消和重试 |

本地 HTTP 服务用于可复现地阻塞和计数文件流；上述并发测试不以公网速度作为通过条件。设置 UI 测试真实点击选项并点击安装；仅非法值边界直接调用控制器，以验证无法从下拉框输入的坏配置。

## 仍需真实环境执行的优先项

- [x] 启动真实 Minecraft，验证 Java 参数、版本目录、实际退出码和停止按钮；见 [真实启动测试用例](launcher-game-launch-test-cases.md)。
- [ ] Java 不兼容、游戏文件缺失和参数错误等真实启动失败 → 查看提示/日志 → 修复后重试；不能以 Java 包下载失败代替游戏启动失败验证。
- [x] 开启和关闭“允许多开”，验证第二个实例、四客户端和停止单个会话；崩溃恢复仍需专门故障注入。
- [x] 临时实例的取消删除、确认删除、连续删除至空及首页回退；不操作用户游戏数据。
- [x] 重复导入、损坏 mrpack、缺少清单和目录权限错误的 UI 提示，恢复后可导入且原实例不变（DOWNLOAD-57/58）。
- [ ] 输入真实启动器接入码，验证节点添加、过期、切换、断网重连和创建/加入房间。
- [ ] 在真实音频设备上验证好友请求、房间邀请、加入申请的提示音开关；自动化回放目前验证开关和通知路径，不能证明扬声器实际发声。

新增功能的合入门槛：补一条矩阵用例、补一个正向和一个异常 UI 操作、运行可见回放并检查截图，再运行 Qt 回归套件。

## 2026-10-28 工作区恢复后的复验

大厅世界状态补充：公开房间在游戏尚未启动、玩家下载和准备客户端时同样显示；列表区分“准备中”和“世界已开放”，加入方式遵守房间的邀请码设置。缺少节点状态时显示“状态未知”，不误报世界已开放。`tests/test_lobby_layout.py` 的 Windows 软件渲染回归为 63 passed、14 subtests passed，证据为 `build/hall-preparation-states-20261028.log/xml`；新用例覆盖两种世界状态与两种加入方式的组合、同一房间开放/关闭后的状态变化。效果图在 `build/hall-preparation-states-20261028/hall-waiting-ready-direct.png` 和 `hall-waiting-ready-invite.png`。这是大厅状态与布局的定向回归，不能替代全部客户端 UI 或真实游戏下载验收。

同次运行原生 `test_public_preparation_room_is_visible_without_game_port`、`test_directory_and_room_control` 和 `test_federation_lookup`，共 13 项通过，日志为原生仓库 `build/hall-preparation-directory-20261028.log`。准备房间用例实际连接本地 C++ 节点，检查无游戏端口时仍可列出/解析、开启邀请码后不返回入房密钥、设为私密后不再列出且不能公开解析；其余用例覆盖房间控制权限与联邦账户查找，不将这些结果写成公网实测。

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| Windows 可见客户端 UI、首页、下载、设置、教学、房间大厅及准备控制器 | 120 passed、2 deselected、96 subtests passed；82 份逐用例 JSON 均为通过，保存 174 张截图和 82 份操作记录 | `build/client-ui-visible-resume-20261028.log/xml`；`E:\code\.test-tools\client-ui-visible-resume-20261028\` |
| 房间流程、成员日志授权和撤回、原生节点 | 可见界面包含聊天优先布局、成员/安装日志页签及授权日志弹窗；原生联邦和权限专项 20 passed、1 skipped | 可见界面见上表；原生 `E:\code\minecraft-tunnel-native\build\room-directory-regression-verified.log` |
| 公开准备房间目录 | 补回归并修复：无游戏端口的公开房间仍列为 waiting；邀请要求开启时 resolve 不返回入房密钥，改为私密后不再公开可见 | `E:\code\minecraft-tunnel-native\tests\test_native.py::NativeTests::test_public_preparation_room_is_visible_without_game_port` |
| 原生 Web 开发者文档 | Vue/TypeScript 构建成功；4 个测试文件、10 项通过 | `E:\code\minecraft-tunnel-native\build\room-directory-web-build.log`、`room-directory-web-test.log` |
| 两台部署节点和公网用例 | 两台节点已逐台升级至 `room-20261028-r2`；预发布 97 项通过；使用更新后的验收源码完成公网测试 5/5，验证 HTTPS、访问控制、联邦数据传输、等待房间解析与邀请密钥隐藏、日志授权/撤回、转让/踢出、错误 SSH 凭据和 UDP | `E:\code\minecraft-tunnel-native\build\room-r2-updated-acceptance\public-acceptance.json`、`command.log`；预发布记录 `production-native-room-20261028-r2\predeployment-regression.log`；逐台发布记录 `room-production-activate-node1-r2.log`、`room-production-activate-node2-r2.log` |
| 四个真实 Minecraft 客户端 | 4 个同版本原版客户端通过 C++ 节点实际进入同一世界并完成移动、方块、聊天、重生、重连及转让后保持游戏连接。此次策略为 relay | `E:\code\minecraft-tunnel-native\validation-artifacts\vanilla-20261028-115739\report.json`、`gui-four-clients.png`；启动器运行记录 `build/room-four-games-final.log/xml` |

本轮没有把既有四窗口中转结果记成 P2P 通过。公开公网节点专项验证了 HTTPS、跨节点目录/游戏数据和 UDP/STUN；不同玩家网络之间的真实 P2P 及 P2P/中转混合仍待测。四种不同整合包/游戏的新客机完整安装、失败恢复、资源下载和同服键鼠验证尚未形成通过证据。真实声卡提示音、真实接入码账户 UI，以及 Java/游戏文件真实启动失败后修复重试仍保持未完成。


