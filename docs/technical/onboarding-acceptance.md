# 首次启动引导验收

引导使用启动器原有设置、首页、联机大厅和创建页面。教学阶段只允许当前目标、下拉选项和教学继续按钮接受操作。接入码、好友和房间创建都不要求在教学中真实完成。

## 自动测试

`tests/test_onboarding.py` 使用实际 QML 和鼠标、键盘事件验证下列行为，其中无节点完整流程还使用真实 `MultiplayerController`。

| 场景 | 必须满足的结果 |
| --- | --- |
| 设置入口 | 点击设置后继续显示语言教学；折叠的分组会展开并滚动到目标 |
| 语言高亮 | 光效覆盖整个下拉框，遮罩挖空宽度与控件宽度一致 |
| 展开语言列表 | 弹出列表可见、不被遮罩压暗；说明卡片避开列表 |
| 选择语言 | 鼠标点选、方向键加 Enter 均能保存语言并进入翻译步骤 |
| 聚焦 | 其他设置、联机方式点击无效；Tab 不能把焦点转移到其他控件 |
| 快捷联机 | 关闭、首页提示、自动创建或加入均能保存；每项有行为说明 |
| 提示音选择 | 高亮真实“好友与联机提示音”开关；可反复切换、立即保存；点击继续或 Enter 可保留当前选择 |
| 提示音控制 | 好友申请与房间邀请受同一开关控制；关闭后不播放、重新开启立即恢复；大厅关闭后仍可播放通知 |
| 闪烁教学 | 联机按钮先保持普通状态；点击“体验闪烁”或按 Enter 后才播放动画 |
| 好友教学 | 无接入码时临时显示好友按钮、闪烁和未读数；结束后恢复实际可见状态 |
| 节点列表 | 整个选择框高亮且能展开；点选教学菜单不会离开教学去要求填写接入码 |
| 继续方式 | 鼠标按钮和 Enter 均能推进教学；两种提示使用不同颜色 |
| 无节点创建 | 可进入创建页面观看真实不可用状态；无需接入码即可完成教学 |
| 两种创建方式 | 先聚焦“先开房，稍后进入游戏”，再认识“关联已开放的世界”；可点击演示世界面板，但不发起扫描或建房；其他按钮继续锁定 |
| 教学副作用 | 不加入剪贴板房间、不触发自动创建、不扫描模拟世界、不添加好友 |
| 结束恢复 | 完成或跳过后保存完成状态；恢复真实节点和世界，关闭大厅、返回启动器首页；后台服务保留，大厅仍可重新打开 |
| 排版 | 每一步的完整说明和卡片都在窗口内 |

Windows 原生窗口回归命令：

```powershell
$env:QT_QPA_PLATFORM = 'windows'
.\.build-venv\Scripts\python.exe -m pytest -q `
  tests/test_onboarding.py tests/test_launcher_qml.py `
  tests/test_social_notifications.py `
  tests/test_lobby_layout.py tests/test_lobby_navigation.py `
  tests/test_lobby_opening.py
$env:QT_QPA_PLATFORM = 'offscreen'
.\.build-venv\Scripts\python.exe -m pytest -q tests/test_room_launch_flow.py
```

## 实际客户端验收

```powershell
$env:QT_QPA_PLATFORM = 'windows'
.\.build-venv\Scripts\python.exe -m pytest -s -q tests/test_onboarding.py
```

正式入口统一为 pytest，独立教学回放脚本已移除。用例直接创建生产启动器窗口，操作真实 QML 页面；配置、游戏目录及节点数据使用临时目录。`test_real_controller_completes_without_a_node_or_clipboard_join`、`test_mouse_completion_closes_lobby_and_returns_to_home` 和 `test_click_through_to_real_lobby_and_create_page_without_creating_room` 覆盖无节点完整流程、教学结束关闭大厅及真实创建页面。

首页、设置和联机大厅的逐步截图及操作日志由 `tests/test_client_ui_acceptance.py` 保存，输出目录通过 `BUGGCRAFT_UI_OUTPUT` 指定，详见 [客户端 UI 测试矩阵](client-ui-test-matrix.md)。教学专项当前通过断言验证，历史 `acceptance.json` 仅保留为既有执行证据。

这项验收覆盖引导交互和无节点状态；真实跨机联机仍由独立的联机测试覆盖。

## 2026-10-27 首轮结果

- Windows 原生窗口：119 项测试、20 个子用例通过。
- 房间创建与启动流程：39 项测试、11 个子用例通过。
- 正常入口启动的真实客户端：完整教学路径 83 项检查通过，截图逐页复核；进程保持运行。
- 验收数据：工作区 `.test-tools/onboarding-review/acceptance.json`；截图位于同一目录。
- 界面回归 XML：`.test-tools/onboarding-acceptance-windows/regression.xml`；房间流程 XML：同目录 `room-launch.xml`。

## 2026-10-27 提示音与教学收尾补充

- 教学、启动器页面和通知声音：63 项测试、4 个子用例通过（XML 计数合计 67），无失败。
- 大厅窗口打开与关闭：4 项测试通过；关闭大厅保留后台控制器并可重新打开。
- 真实 Windows 客户端已走通新增提示音步骤：反复切换可保存，完成后关闭大厅并返回首页，后台好友服务保留。
- 测试结果：`.test-tools/onboarding-sound/focused.xml`、`lobby-opening.xml`；真实交互记录与截图位于同目录 `runtime/`。
