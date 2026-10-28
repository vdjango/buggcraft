# 网络日志导出与节点反馈测试用例

本组核对实际文件、上传回执与节点附件，不以按钮变化代替功能通过。正版/Microsoft 验证不在本轮范围。

## 执行环境

- `tests/test_diagnostics_ui.py` 创建真实启动器窗口，默认通过 Qt offscreen 离屏渲染和定向鼠标/键盘/输入法事件操作生产入口与保存对话框；不移动系统鼠标，不借用桌面剪贴板输入中文。
- `tests/diagnostics_node_fixture.py` 在独立进程启动两个本机隔离节点，使用生产 SSH、Web 管理、账号、反馈存储与联邦同步实现；不向线上节点写测试反馈。
- 启动器执行生产异步采集器、独立 C++ 桥进程和上传协议，不替换 ZIP 导出或上传返回值。当前 Windows 的接口、地址、路由、DNS 和网关实际采集。
- 这组确定性用例只关闭公网 STUN 主动探测。因此 NAT 标注必须为未知，不能用本机成功代替公网穿透验证。探测器另外由 `tests/test_nat_probe.py` 覆盖。
- 需要相邻 `minecraft-tunnel-native` 源码、已构建的原生桥及节点测试依赖；路径可由 `BUGGCRAFT_NATIVE_REPO` 指定。依赖缺失直接失败，不伪装通过。

## 点击式功能用例

| 编号 | 操作 | 必须核对的实际结果 | 自动化方法 |
| --- | --- | --- | --- |
| DIAG-01 | 联机大厅 → 导出日志 → 实际保存框输入不带 `.zip` 的完整路径 → 保存 | 自动补齐后缀并生成可读取 ZIP；包含本次新网络快照、Windows 接口/路由/DNS/网关、P2P 会话记录和所选游戏日志；逐文件字节数与 SHA-256 符合清单；诊断需要的地址保留，示例凭据脱敏，设置文件排除；节点反馈数为 0 | `test_export_click_saves_network_game_archive_without_uploading` |
| DIAG-02 | 个人接入码登录 → 提交诊断 → 输入中文标题、含换行和表情的描述 → 确认框默认“否” → 明确选择“是” → 上传期间重复点击 | 只创建一个异步任务和一条反馈；真实 C++ 桥经 SSH 向当前节点提交；显示节点返回的反馈编号；管理员实际取回附件，另一受信任节点同步后取回相同字节；节点存储的标题/描述逐字一致；匿名下载返回 401；附件内容再次按 DIAG-01 检查 | `test_submit_click_uploads_to_current_node_and_federated_admin_download` |
| DIAG-03 | 标题框和描述框分别点击取消、按 Esc、关闭；确认框分别选“否”、按 Esc、关闭；切换匿名状态尝试点击 | 不启动采集、不生成新快照、不创建上传任务/反馈；每种取消后大厅仍可见；没有原生弹窗时大厅 Esc 恢复正常；匿名按钮禁用且不弹提交窗口 | `test_cancel_consent_or_anonymous_never_collects_or_uploads` |
| DIAG-04 | 使用无效凭据向真实节点提交 → 查看失败 → 恢复有效凭据 → 从同一 UI 重新提交 | 服务端确实拒绝认证；启动器显示上传未完成，不能显示成功编号，节点不存在反馈；恢复后可重新采集、上传并创建一条反馈 | `test_actual_node_rejects_invalid_token_and_retry_uploads_after_repair` |
| DIAG-05 | 导出日志 → 保存框分别点击取消、按 Esc、关闭 | 不启动导出任务，不生成网络快照或 ZIP；大厅保持可见，节点反馈数为 0 | `test_export_cancel_escape_and_close_create_no_archive_or_snapshot` |
| DIAG-06 | 提交诊断 → 分别输入空白标题、121 字符标题、4001 字符描述、3000 个中文字符的描述 → 确认 | 真实异步任务在采集前报告输入错误；不产生网络快照或节点反馈，不显示成功编号；中文描述触发 UTF-8 字节限制而非错误地按字符数放行 | `test_invalid_metadata_fails_before_network_collection_or_node_upload` |

DIAG-03 曾发现真实缺陷：QQuickWidget 中大厅的 Esc 快捷键先于原生确认框处理，关闭了大厅而确认框仍停留。修复在原生子弹窗的 `ShortcutOverride` 阶段优先让该弹窗处理 Esc，并保留 Qt 原本的取消/否语义；不直接模拟“取消”结果，也不改变房间连接状态。

## 协议、失败与隐私回归

| 范围 | 自动化入口 | 通过标准 |
| --- | --- | --- |
| 同意与输入约束 | `tests/test_feedback_upload.py` | 只有布尔 `True` 允许采集；空白/超长标题和描述、UTF-8 控制帧超限在采集前拒绝 |
| 上传尺寸与采集错误 | 同上 | 空 ZIP、超过 20 MiB、采集写盘错误均不连接节点，实际临时文件/目录清理完成 |
| 上传隔离与兼容 | 同上 | 使用独立桥进程；错误后关闭该桥并清理 ZIP；旧桥缺少接口时明确报完整启动器升级，不发送附件 |
| 导出证据完整性 | `tests/test_connection_diagnostics.py` | 先刷新原生日志再扫描；保留分玩家/分会话、轮转、游戏与崩溃证据；缺失/跳过/采集失败有记录；不打包设置、存档和游戏选项 |
| 采集失败与脱敏 | 同上 | 路由查询超时仍落盘接口快照；发现失败不能谎报无 IPv6；代理仅记录是否配置；请求头、令牌和 ICE 凭据脱敏 |
| 实际原生上传/节点存储 | 相邻原生仓库 `compatibility/tests/test_feedback_native.py` | 未同意/超限不创建反馈；传输截断保留问题说明、没有附件或 `.part`；实际桥回执校验字节与 SHA-256；管理员和联邦取回附件一致 |

## 重跑与证据

在启动器仓库执行：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_QUICK_BACKEND = 'software'
$env:BUGGCRAFT_UI_OUTPUT = 'E:\code\.test-tools\diagnostics-ui'
.build-venv\Scripts\python.exe -m pytest tests/test_diagnostics_ui.py -vv
.build-venv\Scripts\python.exe -m pytest tests/test_feedback_upload.py tests/test_connection_diagnostics.py -q
```

节点协议测试须从相邻原生仓库的 `compatibility` 目录启动，并将该目录和 `src` 加到 `PYTHONPATH`。不要在同一 Python 进程混合两个仓库的 `tests` 包。

每条 UI 用例保存 `actions.jsonl`、增量 `live-actions.jsonl` 和 `client-ui-result.json`；成功导出/上传和认证失败保存截图；上传成功另保存实际节点收到的 ZIP 与 `node-receipt.json`。私有测试账号只在临时节点内存在，测试结束清理。

2026-10-28 定向 Qt 输入复跑：`tests/test_qt_input.py` 的 3 条真实控件输入回归，加上述 6 条诊断功能用例，共 9 passed，68.10 秒，退出码 0。六份报告记录 `qt_platform=offscreen`、`mouse_input=QApplication.sendEvent`；实际 ZIP 和两个节点管理员取回校验继续通过。日志 `E:\code\.test-tools\pytest-qt-input-diagnostics-20261028.txt`，证据目录 `qt-input-diagnostics-20261028/`。完整业务断言沿用下述可见基线；Qt 离屏结果不证明系统窗口管理行为，相关边界见 [不占用桌面的 Qt 输入](client-ui-test-matrix.md#不占用桌面的-qt-输入)。

公共输入层的完整页面及关联回归另有 141 passed、97 subtests passed，2 条桌面测试未启用、2 条正版登录排除，退出码 0。`E:\code\.test-tools\audit-qt-input-functional-20261028.py` 复核 80 份页面报告、6 份诊断报告、两个实际 ZIP 及两节点回执全部通过，结果保存为 `qt-input-functional-audit-20261028.json`；没有用控件状态代替实际文件与上传结果。

2026-10-28 Windows 可见回归：6/6 通过，70.40 秒，进程退出码 0，六份结果报告均为 `passed=true`。证据目录为 `E:\code\.test-tools\diagnostics-ui-verified-20261028\`，pytest 日志为 `pytest-diagnostics-ui-verified-20261028.txt`。反馈、导出与加载器目录单测合跑为 32 passed、21 个子测试通过，其中反馈/导出本身 23 条；原生节点协议独立回归 4 passed，均保留实际执行日志。

直接依赖回归另有 123 passed、47 个子测试通过，包含好友入口/目录及大厅布局/打开；共用分支、完整下载页和加载器选源的 Windows 可见合跑为 40 passed、72 个子测试通过，40 份 UI 报告全部通过。分别保留 `pytest-diagnostics-related-verified-20261028.txt` 和 `pytest-shared-download-verified-20261028.txt`，不把初次失败日志写成通过结果。

打包工作流使用的 `unittest` 调用方式另行执行诊断/反馈/NAT/P2P 四个模块，35 条全部通过（`unittest-diagnostics-preflight-20261028.txt`）。产物复核脚本 `E:\code\.test-tools\audit-diagnostics-functional-20261028.py` 再次读取 46 份 UI 报告、本地/节点两份实际 ZIP 的逐文件清单和节点回执，输出 `diagnostics-functional-audit-20261028.json`；核对结果全部通过。

执行结果与完成勾选统一登记在 [功能覆盖清单](launcher-function-coverage-checklist.md#5-网络诊断导出与节点反馈) 和 [UI 测试矩阵](client-ui-test-matrix.md)。源码/本机测试通过不代表已经发布或部署到生产节点。
