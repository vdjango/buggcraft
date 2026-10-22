# 公开房间与邀请码验收

验收日期：2026-10-20。应用代码为 Python 与 QML；无需 Docker、虚拟网卡或新增账号。

## 用户行为

| 创建设置 | 大厅可见 | 加入行为 |
| --- | --- | --- |
| 不公开 | 否 | 持有邀请码后加入 |
| 公开，关闭“加入需要邀请码” | 是 | 列表点击“加入”，直接连接 |
| 公开，开启“加入需要邀请码” | 是 | 列表点击“输入邀请码”，填写该房间邀请码后连接 |

创建按钮统一为“创建房间”。创建后的房主提示随加入方式变化；允许直接加入的房间仍可复制邀请码供朋友使用。受保护房间点击同样的“加入”按钮后以弹窗输入邀请码，显示房间名称，其他房间的邀请码不能误加入，取消后清除目标房间。

## 服务端约束

房间描述包含布尔值 `require_invite`，列表与签名联邦公告一起传递。受保护公开房间的 `resolve` 响应不含 secret，私密房间拒绝公开解析；已知公开房间 ID 和节点访问凭据不足以通过游戏客户端认证。私密房间强制需要邀请码，非法配置类型被拒绝。旧节点缺少 `room-invite-policy-v1` 能力时，SDK 停止创建受保护公开房间，不能静默降级为直接加入。

## 已执行验证

- `tests/test_lobby_layout.py`：真实 QML 鼠标操作、三种访问设置、开关显示/保留、列表标签、邀请弹窗及房主提示。
- `tests/test_room_launch_flow.py`：控制器参数传递、直接加入、目标邀请码匹配及返回清理。
- `tests/test_room_access.py`：真实加密节点连续 10 次循环，交替覆盖三种访问模式；每次一房主、三客户端，逐客户端校验 64 KiB 随机数据，关闭后验证通知与目录移除。还检查错误密钥、无效配置及旧节点能力拒绝。
- `tests/test_node_federation.py`：4 个真实加密节点，受保护房间可跨节点发现、凭邀请码加入并传输/聊天，公开目录和联邦公告均不泄漏 secret。
- `tests/test_game_chat_ui.py`：从 QML 创建公开直加入和公开凭邀请码房间，三个访客分别通过列表进入；错误邀请码被拒绝，正确邀请码可用。Minecraft Java 1.21.8 原版测试世界中，四名独立协议角色真正进入世界，每种模式完成 10 轮游戏消息收发，关闭房间后所有大厅清除会话。此项使用本机节点与隔离测试世界。

2026-10-20 远程原节点与预览节点已部署邀请码策略；预览节点另同步了当时服务端模块，保留回滚副本并通过服务健康检查。两个远程节点分别完成连续 10 次一房主三客户端传输循环；预览节点最终同步后再次通过同一循环。远程测试是加密传输与目录验收，不冒充远程游戏角色操作。随后按用户要求，两个节点均已停止并取消开机自启；2026-10-21 的本地补测没有重新启动它们，也没有向它们部署本轮分页改动。

原始记录：

- [QML 与四角色游戏结果](../../../multiplayer-tests/room-access-game-ui-result.json)
- [四角色游戏界面回归日志](../../../multiplayer-tests/room-access-game-ui-final-20261020.log)
- [原节点 10 次连接日志](../../../multiplayer-tests/room-access-remote-primary-20261020.log)
- [预览节点最终 10 次连接日志](../../../multiplayer-tests/room-access-remote-preview-final-20261020.log)
- [远程节点结果摘要](../../../multiplayer-tests/room-access-remote-result.json)
- [公开房间设置截图](../../../multiplayer-tests/create-public-invite-review.png)
- [大厅加入方式截图](../../../multiplayer-tests/hall-access-modes-review.png)

最终结果说明：最后一次完整发现执行了 156 项，其中一个聊天身份用例因执行期间代码状态变化报错；不将该次标为全量通过。随后重新加载代码，执行除已经通过的版本矩阵、实际游戏、游戏界面和四节点联邦四组外的全部用例，最终 **145 项，141 项通过、4 项跳过，零失败/错误**（[最终补测日志](../../../multiplayer-tests/launcher-room-access-targeted-final-20261020.log)）。该补测中的聊天身份用例正常；相关 QML 布局 32 项和两项实际游戏界面测试也已分别通过。跳过项为两项指定真实 LAN 的测试、实际安装测试及远程节点测试；远程节点已按上文单独显式执行。未把分批结果描述成单次全量零失败。

复跑命令（buggcraft 目录）：

```powershell
python -X utf8 -m unittest discover -s tests -p test_room_access.py -v
python -X utf8 -m unittest discover -s tests -p test_lobby_layout.py -v
python -X utf8 -m unittest discover -s tests -p test_game_chat_ui.py -v
# 远程验证需显式指定已经授权的节点配置；凭据不写入报告。
$env:BUGGCRAFT_ACCESS_PROFILE='你的节点配置路径'
python -X utf8 -m unittest tests.test_room_access.RemoteRoomAccessTests -v
```

本次没有重复全部 85 个版本的聊天矩阵、100 名真实玩家容量或长期运行验收。相应范围继续以原验收文档为准。
