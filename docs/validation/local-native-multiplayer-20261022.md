# 2026-10-22 本机真实游戏联机验证

## 环境与操作

Windows、Java 21、Minecraft Java 1.21.8。使用已有游戏资源，以独立游戏目录和临时世界启动三个原生图形客户端；服务端和联机节点均只监听本机。未使用玩家账号令牌、已有存档或公网节点。

脚本：[`scripts/validate_local_multiplayer.py`](../../scripts/validate_local_multiplayer.py)。本轮输出位于工作区 `buggcraft/dist/native-multiplayer-20261022/`；该目录为本地验证产物，不纳入源码或发布运行包。

## 实际结果

- `BuggP2P`：通过真实 ICE / DTLS / SCTP 通道进入世界，日志记录候选、选中的候选对及游戏数据流量。
- `BuggRelay`：选择强制中继进入世界，同时拦截 `create_pc`，验证该客户端没有发起 P2P 协商。
- `BuggAuto`：注入 UDP 不可用故障，自动回退 SSH 中继后进入世界。
- 三个客户端同时在线，完成五轮服务器传送和广播。每轮逐端检查 Minecraft `latest.log` 确认收到对应消息，并查询真实服务器确认在线人数为 3。
- 主动关闭 `BuggP2P` 的 PeerConnection，确认原游戏会话断开。重启该测试客户端，使用同一监听端口，经中继重新进服；再次确认消息接收与三个玩家在线。
- 约 76.92 秒完成，结果为通过。测试只关闭本轮创建的游戏进程与本地服务端。
- 每个端点独立保存网络快照，本轮共 4 份；原生 Windows 网络采集成功，包含网卡、路由和 DNS。P2P 会话日志与应用日志一起导出为 `diagnostics.zip`。

结果文件：`dist/native-multiplayer-20261022/result.json`；每个客户端的启动输出与游戏日志分别位于同目录下的角色文件夹中。

## 结论范围

验证的是当前源码数据通道在本机的真实 Minecraft 流量、混合路径及故障后的重新连接。不是仅以回显服务冒充游戏，也没有把本机 ICE 成功记成跨 NAT 打洞成功。不同家庭路由器、运营商、校园网及手机热点仍需双方实际环境测试；当前 NAT 分类按证据保持 `unknown`。

## 本轮发布包

本机输出：`dist/tester-20261022/release/`。运行包为 52,750,468 字节（约 50.31 MiB），SHA-256：`1370ea38c2b87ac6008135b41f7b42fe01d84a3b9816140183a0262f947f2030`。

- 对 ZIP 逐文件验证大小、SHA-256 和 CRC，从该 ZIP 全新解压后，以清理过 Python / Qt 路径的环境运行。
- Windows 和 offscreen 两种后端的 17 项成品检查均通过，包括加密 64 KiB 往返、Qt 主窗口与联机界面、默认 `.minecraft`、整合包无 Key 输入及日志导出。
- 正常模式实际启动解压后的 `Buggcraft.exe`，确认出现可见的 Buggcraft 主窗口。
- 本轮未签名 `Buggcraft-Setup.exe` 被当前 Windows 应用程序控制以 4551 拦截，离线安装未完成验证；`validation.json` 保留失败记录，不记作通过。当前可测试交付使用便携运行包 ZIP。
- 85 项相关回归通过，另补充 2 项日志导出交互测试通过；真实 Java 服务端与四个独立协议客户端的 2 项游戏聊天集成测试通过。原生图形客户端的实际测试结果见上文。
