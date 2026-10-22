# 节点可用性与大厅回归

日期：2026-10-21。无节点、配置损坏、连接尚未验证或检查失败时，创建和加入入口禁用；Python 控制器同时检查，不能通过直接调用界面操作绕过。成功请求房间目录后解锁，后续后台检查失败重新禁用，恢复后解锁。后台检查不清空正在填写的表单或已加载的分页。

## 正式用例

`tests/test_room_node_availability.py` 共 18 项通过（23.525 秒），覆盖：

- 没有配置、尚未验证、损坏配置以及节点被移除时拦截创建和加入。
- 创建过程中掉线、好友加入、公开房间加入和邀请码加入的后台拦截。
- 刷新或切换节点后忽略旧结果，取消邀请弹窗后忽略迟到的房间解析结果。
- 健康检查失败及恢复保留当前页面、房间和分页位置。
- 分页失败在原游标重试，合并时去重，搜索防抖及旧搜索结果失效。
- 启动真实本地加密节点，连续 10 轮停止、检查、拒绝创建/加入、恢复、解锁。
- 45 个公开房间按 20、20、5 分页，搜索初始 20 条之外的房间。
- 真实目录请求拒绝非法分页参数；旧节点按 20、20、20、5 读取 65 条且不遗漏。

`tests/test_lobby_layout.py` 共 36 项通过。真实 QML 控件操作覆盖无可用节点时禁用按钮、恢复后启用、表单仍可取消、默认 20 条且不提前继续请求、邀请码弹窗、房间返回确认、复制反馈不挤动聊天、独立好友窗口及浮钮拖动。测试使用隔离状态，不替换玩家配置。

## 实际游戏

`tests/test_game_chat_ui.py` 两项通过（45.608 秒）。在本地 Minecraft Java 1.21.8 原版隔离世界中，四个独立协议角色进入游戏、四个 QML 大厅保持连接，完成 10 轮双向聊天和聊天断线恢复。公开直接加入、公开凭邀请码两种模式分别通过四角色进入世界和 10 轮聊天，房主确认关闭后访客收到通知并清除会话。

这些是实际协议角色，不是四个图形客户端；本次没有重新执行破坏方块、物品持久性、全部版本聊天矩阵、百人真实游戏容量或长期运行验收。相应历史范围见 [联机验证](multiplayer-validation.md) 和 [启动器验收](launcher-validation.md)。

## 远程服务状态

按用户要求停止 `buggcraft-relay.service` 与 `buggcraft-node-test.service`，并取消开机自启。最终 SSH 复查两项均为 `inactive/dead/disabled`，3333、3334、18443 均无监听；配置、密钥和数据保留。本轮没有重启或部署远程节点，全部新增测试使用本地节点。

## 复跑

在 buggcraft 目录执行：

```powershell
python -X utf8 -m unittest discover -s tests -p test_room_node_availability.py -v
python -X utf8 -m unittest discover -s tests -p test_lobby_layout.py -v
python -X utf8 -m unittest discover -s tests -p test_game_chat_ui.py -v
```

游戏测试需要工作区现有 Java、Node.js、测试依赖和游戏服务端资源。未设置远程测试环境变量，因此不会因执行这些用例重新启用已停远程节点。

界面复查截图：[节点不可用](../../../multiplayer-tests/hall-offline-review-20261021.png)、[20 条初始列表](../../../multiplayer-tests/hall-paged-review-20261021.png)、[房间详情](../../../multiplayer-tests/room-connected-review-20261021.png)。实际游戏结果：[四大厅双向聊天](../../../multiplayer-tests/chat-game-ui-result.json)、[两种公开加入模式](../../../multiplayer-tests/room-access-game-ui-result.json)。
