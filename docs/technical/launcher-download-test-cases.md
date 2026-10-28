# 启动器下载页面测试用例

对应 [功能清单第 2 节](launcher-function-coverage-checklist.md#2-下载页面)，DOWNLOAD-01 至 DOWNLOAD-58 与原清单逐项对应。完成标记只放在清单中：全部分支执行通过才打勾，未执行或仅验证部分步骤的条目保持空框。正版登录按要求不测试。

2026-10-27 本轮执行：无窗口及 Windows 可见模式各 29 条 UI 方法、60 个子测试通过；新增共用分支用例 D29 覆盖四类内容的详情/版本请求晚到成功与错误。关联回归 130 条、11 个子测试通过，排除 2 条正版登录。实例失效后重新选择恢复的补充用例在两种模式各通过 1 条、3 个子测试。清单完成 42/55 项；尚未完整验证的 DOWNLOAD-05、08 至 12、20、25、30、31、35、38、49 保持空框。完整证据路径见文末所链测试矩阵。

## 测试方法与证据

自动化入口为 `tests/test_download_ui.py::DownloadChecklistUiTests`。启动生产主窗口和 QML，用 Qt 鼠标、键盘、滚轮、拖放事件操作。断言包括文件字节与哈希校验、目标目录、安装元数据、实例扫描及首页刷新、任务生命周期、日志、持久化和重开恢复。失败不能仅凭页面提示判定：还检查是否错误生成最终文件、是否误改其他实例、是否允许恢复。

远程搜索、来源与版本列表、翻译响应使用隔离夹具；文件通过本机 HTTP 服务传输，生产下载器、校验、解压、整合包导入和任务工作线程照常运行。下载资源包含可用的测试归档及元数据，不能据此认定可启动 Minecraft。没有替换 `TasksPage.start_install`、下载工作线程或真实文件写入来制造成功结果。

磁盘满和权限不足用目标文件写入处的系统异常注入，不真的写满磁盘或更改用户目录权限；断流通过 HTTP 实际提前关闭响应；校验错误通过实际损坏传输字节；并发与取消使用 HTTP 屏障。整合包测试覆盖 MRPACK 和 CurseForge ZIP；本轮夹具无真实 Java 加载器及依赖，不能代表所有公开整合包安装和游戏运行。

每例均创建临时配置、游戏目录及缓存，只删除本例创建的文件。产物包括 `client-ui-result.json`、`actions.jsonl`、`catalogue-requests.json`、`http-requests.json` 和截图。用例包含子测试时，任一分支失败均使报告失败；同时必须检查 pytest 退出码，不以 JSON 或截图存在判定成功。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QUICK_BACKEND = "software"
$env:BUGGCRAFT_UI_OUTPUT = "E:\code\.test-tools\download-checklist-final"
.build-venv\Scripts\python.exe -m pytest -q tests/test_download_ui.py

# Windows 可见鼠标/键盘回放；执行后检查截图与日志
$env:QT_QPA_PLATFORM = "windows"
$env:BUGGCRAFT_UI_OUTPUT = "E:\code\.test-tools\download-ui-windows"
.build-venv\Scripts\python.exe -m pytest -q tests/test_download_ui.py
```

## 自动化方法索引

下表方法名省略 `test_` 前缀。编号仅用于映射，完成与否以清单和执行证据为准。

| 方法代号 | 自动化方法 | 检查的功能结果 |
|---|---|---|
| D1 | `download_category_navigation_history_and_detail_return` | 五类切换、项目详情返回、下载记录与游戏下载导航 |
| D2 | `game_filters_search_empty_clear_and_install_return` | 正式版/快照/旧版/全部、搜索/清空、无结果、安装返回/取消 |
| D3 | `game_catalogue_network_error_retry_and_cache_write` | 实际 HTTP 清单失败、重试恢复及缓存写盘 |
| D4 | `vanilla_install_refreshes_instances_header_and_home_target` | 原版下载与校验、实际客户端归档、实例/头部/首页即时刷新 |
| D5 | `loader_versions_replace_remove_incompatibility_and_new_game` | 四加载器的选择、更换、互斥、移除及游戏版本切换；OptiFine 说明 |
| D6 | `loader_empty_failed_list_retry_and_back` | 空加载器列表、错误原因、重新请求、恢复与返回 |
| D7 | `fabric_quilt_api_versions_replace_remove_and_reset` | Fabric/Quilt 的 API 选择、更换、移除及不同游戏版本请求 |
| D8 | `content_sources_search_clear_empty_error_and_retry_for_every_kind` | 四类各自的三来源、搜索按钮/回车、清空、无结果、错误与换源重试 |
| D9 | `project_details_files_search_selection_and_cancel_for_every_kind` | 四类详情、文件搜索与选择、确认版本、取消/关闭、不误提交任务 |
| D10 | `projects_and_version_files_append_by_mouse_wheel_for_every_kind` | 四类项目与文件列表实际滚动追加、去重、后续文件搜索和选择 |
| D11 | `content_downloads_write_verified_files_to_selected_instance` | 模组/资源包/光影目标实例选择、实际文件内容和历史路径 |
| D12 | `confirmation_target_compatibility_and_deleted_instance` | 头部及确认弹窗换实例、版本不兼容阻止、实例已删除时重验 |
| D13 | `parallel_search_ignores_stale_results_for_every_kind` | 四类快慢搜索、来源切换及搜索未完成时切换类别；旧响应到达后仍保留当前来源和类别的项目 |
| D14 | `translation_original_and_versions_tabs_for_every_kind` | 设置页开启翻译、四类译文/原文切换、版本页签 |
| D15 | `version_file_failure_retries_first_page_for_every_kind` | 四类文件首屏请求失败后的真实重新请求、恢复和选择 |
| D16 | `streaming_progress_cancel_log_tabs_and_retry` | 实际流式进度、两类日志、正在取消/已取消、无不完整文件、重试 |
| D17 | `failed_download_visible_error_log_and_recovery` | HTTP 错误展示与日志、重试成功、保留失败历史 |
| D18 | `modpack_download_installs_new_instance_without_replacing_existing` | 下载/校验后调用真实导入器、新实例、原实例保留与首页选择 |
| D19 | `modpack_import_mrpack_and_curseforge_zip_name_and_instance_refresh` | 两种导入格式、自动命名/改名、解压及实例/首页刷新 |
| D20 | `import_cancel_corrupt_missing_manifest_and_invalid_names_recover` | 取消文件选择、损坏/无清单/普通资源 ZIP、空名/非法/重名及修复重试 |
| D21 | `drop_modpack_over_home_and_qml_controls_opens_inspected_form` | 主窗口及 QML 上方真实拖放事件，导入表单、改名和安装 |
| D22 | `import_failure_resume_reuses_same_task_and_preserves_existing_instances` | 整合包失败原因、同一任务继续安装、保护已有实例 |
| D23 | `hash_failure_disk_full_and_permission_error_reject_files_then_retry` | 损坏字节、ENOSPC、EACCES、拒绝发布最终文件及恢复重试 |
| D24 | `parallel_queue_duplicate_submission_and_clear_preserve_running_tasks` | 排队与并行、重复提交、页面切换、清除记录保留运行任务、记录筛选 |
| D25 | `history_reopens_from_disk_and_completed_content_can_reinstall` | 内容重新安装、完整主窗口重建、历史/日志恢复及中断记录重试 |
| D26 | `interrupted_transfer_and_unavailable_first_source_recover` | 真实 HTTP 断流、失败不发布文件、首源不可用时切备用源及来源日志 |
| D27 | `import_cancel_then_continue_installs_same_instance` | 导入取消、同一任务继续、实例发布与列表可见 |
| D28 | `downloaded_modpack_download_and_install_failures_resume_from_history` | 下载型整合包的压缩包下载失败、客户端依赖安装失败，两阶段日志及继续安装 |
| D29 | `back_from_loading_project_discards_late_success_and_error_for_every_kind` | 四类详情和版本请求在加载中返回；晚到成功/错误不恢复已取消详情、不覆盖列表、不创建任务，返回后可重新打开并下载 |

## 逐项操作与预期

前置：已完成首次教学；有两个隔离游戏实例及上述可控服务。界面步骤必须实际操作，不能通过直接调用控制器方法代替。表内“另测”给出尚未验证的部分，不计入完成。

### 2.1 页面切换

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-01 | 头部下载 → 游戏下载 → 游戏/模组/资源包/光影/整合包 | 类别及对应结果区同步，D1 |
| DOWNLOAD-02 | 游戏下载 → 下载记录 → 游戏下载 | 内容与记录页可用，返回后类别有效，D1 |
| DOWNLOAD-03 | 分类 → 项目详情加载中返回 → 等待晚到响应 → 重新打开；换分类 → 切回 | 返回对应列表；晚到详情/版本成功或错误不覆盖列表状态，重新打开仍可取得文件；D1/D9/D29 |

### 2.2 游戏版本与原版安装

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-04 | 正式版/快照/旧版/全部 → 搜索 → 选择版本 | 分类数量、关键词及安装目标正确，D2 |
| DOWNLOAD-05 | 原版安装 → 下载记录 → 完成 → 实例 → 首页 → 启动 | D4 验证真实下载、文件及刷新；真实 Minecraft 启动另测，整条不提前勾选 |
| DOWNLOAD-06 | 输入关键词 → 清空/无结果 → 更换词和分类 | 不残留旧结果，清空恢复列表，D2 |
| DOWNLOAD-07 | 清单服务失败 → 重试；安装页返回/取消 → 重选 | 保留错误，重新请求并写缓存，取消无任务，D2/D3 |

### 2.3 加载器与 API

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-08 | Forge 版本 → 安装 → 完成 → 实例 → 启动 | D5 覆盖选择；真实安装器产物与游戏启动另测 |
| DOWNLOAD-09 | NeoForge 版本 → 安装 → 完成 → 实例 → 启动 | 同上，不能用 Forge 结果代替 NeoForge |
| DOWNLOAD-10 | Fabric Loader → 安装 → 完成 → 实例 → 启动 | 同上，需真实 Fabric 安装及进程证据 |
| DOWNLOAD-11 | Quilt Loader → 安装 → 完成 → 实例 → 启动 | 同上，需真实 Quilt 安装及进程证据 |
| DOWNLOAD-12 | Fabric/Quilt → Fabric API；Quilt → QSL/QFAPI → 安装 → 查看文件 | D7 覆盖版本选择；真实加载器与 API 联合安装另测 |
| DOWNLOAD-13 | 选择加载器/API → 更换版本 → 移除 → 换另一加载器 | 页面选择及依赖状态同步，D5/D7 |
| DOWNLOAD-14 | 选择加载器 → 查看互斥组件 → 换游戏版本 → 重选加载器/API | 禁止互斥选项，按新游戏版本重新请求，D5/D7 |
| DOWNLOAD-15 | 空加载器列表/加载失败 → 重载/返回 | 空与失败明确区分，重载实际请求且可恢复，D6 |
| DOWNLOAD-16 | 查看 OptiFine 卡片 | 显示“需官方安装器”，不能当作自动安装入口，D5 |

### 2.4 模组

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-17 | 模组三来源分别搜索 → 选择项目 | 返回所选来源的项目与详情，D8 |
| DOWNLOAD-18 | 查看介绍/作者/来源/游戏版本 → 文件 → 搜索并选择文件 | 详情数据和所选具体版本一致，D9 |
| DOWNLOAD-19 | 下载 → 展开目标实例 → 换实例 → 查看兼容提示 → 确认 | 不兼容禁止提交，兼容实例可下载并记录路径，D11/D12 |
| DOWNLOAD-20 | 下载完成 → mods → 启动游戏并核对模组/依赖 | D11 校验文件和目录；真实游戏加载及依赖解析另测 |
| DOWNLOAD-21 | 返回列表；确认弹窗取消/关闭；不兼容/已删除实例 → 重选 | 不误提交、不下载到其他实例；重新选择可恢复，D9/D12 |

### 2.5 资源包

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-22 | 三来源分别搜索资源包 → 选择项目 | 来源、列表与详情对应，D8 |
| DOWNLOAD-23 | 介绍/支持版本 → 文件 → 搜索并选择 | 文件选择和确认版本正确，D9 |
| DOWNLOAD-24 | 选目标 → 确认 → 下载完成 → resourcepacks | 实际字节、路径及历史一致，D11 |
| DOWNLOAD-25 | 启动对应游戏 → 资源包设置 → 启用 | 游戏内显示及启用另测，不以 ZIP 下载成功代替 |
| DOWNLOAD-26 | 详情返回；确认取消/关闭；无兼容文件 → 换文件/实例 | 文件空结果可清空恢复，目标不兼容可换兼容实例，D9/D12 |

### 2.6 光影

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-27 | 三来源分别搜索光影 → 选择项目 | 来源、列表与详情对应，D8 |
| DOWNLOAD-28 | 介绍/支持版本 → 文件 → 搜索并选择 | 文件选择和确认版本正确，D9 |
| DOWNLOAD-29 | 选目标 → 确认 → 完成 → shaderpacks | 实际字节、路径及历史一致，D11 |
| DOWNLOAD-30 | 兼容光影组件 → 启动 → 光影设置 → 启用 | 游戏内生效另测，文件存在不代表渲染已启用 |
| DOWNLOAD-31 | 详情返回；确认取消/关闭；无光影组件时查看限制 | D9 验证取消/返回，D11 验证原版目标的文件下载；游戏内限制/提示仍另核对 |

### 2.7 整合包下载安装

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-32 | 三来源分别搜索整合包 → 选择项目 | 来源、列表与详情对应，D8 |
| DOWNLOAD-33 | 介绍/游戏版本/加载器要求 → 文件 → 选整合包版本 | 明确是独立实例，版本文件选择正确，D9/D18 |
| DOWNLOAD-34 | 确认独立实例 → 下载 → 校验 → 自动安装 | 真实导入器写入新实例元数据与覆盖文件，D18 |
| DOWNLOAD-35 | 完成 → 实例 → 新实例 → 首页 → 启动，核对原实例 | D18 验证新实例和原实例元数据保留；真实游戏启动另测 |
| DOWNLOAD-36 | 详情返回/取消；下载或安装失败 → 日志 → 继续 | D9/D28 覆盖确认、两种失败阶段的实际错误、日志和继续安装 |

### 2.8 导入整合包

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-37 | 导入 → 选择 MRPACK/受支持 ZIP → 读取信息 | 两种格式识别，自动命名，D19 |
| DOWNLOAD-38 | 改实例名 → 导入 → 依赖/加载器/解压 → 实例 → 启动 | D19 覆盖原版包导入和解压；真实带依赖/加载器整合包及游戏启动另测 |
| DOWNLOAD-39 | 单文件拖入主窗口/QML → 查看信息 → 改名 → 导入 | 接收真实 Qt 拖放事件，创建对应新实例，D21 |
| DOWNLOAD-40 | 取消文件选择/返回；损坏包/无清单/普通资源 ZIP → 重选 | 不误接受无效包，可选择正确包恢复，D20 |
| DOWNLOAD-41 | 空名/非法名/重名 → 提交 → 改名重试 | 空名禁用，非法/重名明确拒绝且无任务，改名可安装，D20 |
| DOWNLOAD-42 | 导入中取消/失败 → 记录 → 继续 → 查看实例 | D22/D27 分别覆盖失败、取消后原任务继续及完成后实例可见 |

### 2.9 四类共用操作

以下步骤必须在模组、资源包、光影、整合包中分别执行；对应方法以四个子测试保留证据。

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-43 | 回车搜索/按钮搜索 → 清空 → 重搜 | 最终关键词与结果一致，D8 |
| DOWNLOAD-44 | 无结果/网络错误/来源不可用 → 换词/换源 → 重试 | 区分空结果与失败，恢复后不残留错误，D8 |
| DOWNLOAD-45 | 三来源切换；慢请求未完时新搜索/换来源 | 来源一致且旧结果不能覆盖新结果，D8/D13 |
| DOWNLOAD-46 | 项目列表滚动追加；文件列表搜索/滚动追加/选择 | 首批/追加、去重和后续文件选择正确，D10 |
| DOWNLOAD-47 | 介绍/文件页签；开启翻译 → 译文/原文 | 四类原文和译文可切换，D14；不代表公网翻译质量 |
| DOWNLOAD-48 | 详情页换首页目标；确认弹窗换实例 | D12 覆盖模组/资源包/光影兼容目标更新，整合包继续使用明确的独立安装目录 |

### 2.10 下载记录

| 编号 | 操作步骤 | 预期结果与验证方法 |
|---|---|---|
| DOWNLOAD-49 | 五类分别发任务 → 等待/进行/完成 | 五类实际任务和文件由 D4/D11/D18 验证，排队和进行中由 D24 验证；五类每阶段的组合证据未齐全不勾选 |
| DOWNLOAD-50 | 任务日志 → 文件进度/文字日志 → 关闭 → 列表 | 真实下载进度与文字日志可切换、关闭及重开，D16/D17/D25 |
| DOWNLOAD-51 | 下载中取消 → 正在取消 → 已取消；失败 → 错误 → 重试 | 不生成不完整最终文件，恢复后校验成功，D16/D17 |
| DOWNLOAD-52 | 导入失败/取消 → 继续；已完成普通内容 → 重装 | D22/D27 覆盖失败/取消续装，D25 覆盖普通内容已完成任务重装 |
| DOWNLOAD-53 | 多任务排队/并行 → 切页 → 返回；重复提交 | 两任务实际并发，重复不新建，清理不取消活跃任务，D24 |
| DOWNLOAD-54 | 断流/首源失败/校验失败/磁盘满/权限不足 → 恢复 → 重试 | 实际断流和哈希拒绝，文件写入异常注入，恢复后校验成功，D23/D26；公网镜像健康/测速不在此项证明范围 |
| DOWNLOAD-55 | 清除结束记录但保留运行任务 → 关闭重开 → 查看与重试 | 空历史写盘、完整窗口恢复完成记录、未完成记录转“已中断”并可重试，D24/D25 |

## 回归发现与修复

## 新增功能结果用例

| 编号 | 操作 | 功能结果与证据 |
|---|---|---|
| D30 | 游戏、模组、资源包、光影、整合包各提交一次；先占满线程，再逐项放行 | 五类任务实际经历等待、传输、完成；任务记录、最终文件和整合包解压结果均核对，`test_every_download_kind_passes_waiting_running_and_completed_with_real_files` |
| D31 | 四类内容确认框分别点击外部、取消、关闭、Esc，再重新确认 | 关闭分支不创建任务；重新确认才开始真实下载，`test_content_confirmation_cancel_close_escape_and_outside_for_every_kind` |
| D32 | 导入名称输入空值、路径分隔符、保留名、尾点和 101 字符；再输入前后空格及 100 字符 | 非法输入在按钮层拦截，边界名称实际写入目标目录并能被实例扫描发现，`test_import_name_invalid_paths_reserved_names_and_exact_length_boundaries` |
| D33 | 通用设置逐项选择下载并发数 1/2/4/8/16/32/64；选 1 和 4 后从 UI 安装游戏 | 配置写盘并重读、真实 HTTP 阻塞时活跃文件恰为 1/4、放行后核对全部库文件字节；`test_settings_checklist_ui.py::test_download_concurrency_control_saves_and_limits_values`。核心补充：`test_download_concurrency.py`、`test_import_uses_configured_1_to_64_real_http_workers_with_verified_files`、`test_download_transport.py` 和 `test_room_mod_installation.py`；验证导入 1–64 路、房间 1/2/4 路、单文件分段服从设置及旧配置/非法值边界 |
| DOWNLOAD-56 | 新建 1.21.8 Fabric 实例选择 Fabric API 并安装；新建 Quilt 实例分别选择 Fabric API 与 QSL/QFAPI 并安装 | 加载器实例实际生成；每个 API JAR 通过本地 HTTP 下载并哈希校验后写入该实例 `mods`；共享 `mods` 不被创建或污染 | [x] `test_api_choices_install_verified_files_in_selected_loader_instance`；生产目录与内容安装链路，目录清单、字节和 HTTP 请求均断言 |
| DOWNLOAD-57 | 分别选择损坏 `.mrpack`、无清单 `.mrpack`、普通 ZIP、普通资源 ZIP；修正后重新选有效包 | 页面显示错误并禁止提交任务；有效包可恢复导入 | [x] `test_import_cancel_corrupt_missing_manifest_and_invalid_names_recover`；9 个分支通过 |
| DOWNLOAD-58 | 选择有效包并输入名称；在导入前让目标目录创建返回权限拒绝；查看任务和日志，再恢复目录权限并点击继续 | 显示具体权限失败且无半成品；保留其他实例；重试后完成同一任务和新实例 | [x] `test_import_directory_permission_failure_keeps_instances_and_retries`；权限系统异常只注入到临时测试目标目录 |

1. 内容搜索失败后修改关键词再点“重试”，原来使用旧的视图快照关键词。重试信号现传递输入框当前文本，D8 在四类分别回归。
2. 下载记录“日志”点击时，更新任务模型销毁调用行，后续访问该行 QML 上下文中的 `root` 报错。日志操作现由持续存在的 TaskHistory 页面函数完成，D16/D17/D25 验证运行中、失败后及重开后的日志。
3. 版本文件首屏失败后，原“重试加载”只处理已有后续页，没有重新请求首屏。现按首屏/后续页分别请求并保留同一项目，D15 在四类分别回归。

执行数量、通过结果、证据目录与未覆盖范围更新至 [客户端 UI 测试矩阵](client-ui-test-matrix.md#本轮执行记录)。
