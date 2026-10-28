# 联机测试与日志

## 给测试者

1. Windows 离线使用：保留 `Buggcraft-Setup.exe` 和运行包 ZIP 在同一目录，再运行安装程序；也可直接解压运行包并打开 `Buggcraft.exe`。游戏默认下载到入口旁的 `.minecraft`，已选择的游戏目录继续有效。
2. 整合包从实例页导入，选择支持的整合包 ZIP 和实例名称即可，不需要输入 API Key。CurseForge 文件通过公共资源服务解析，服务或文件不可用时会明确报错。
3. 两端选择兼容的游戏、加载器和模组。创建房间后加入，记录双方网络环境（家庭宽带、手机热点、校园网等）、操作时间和问题表现。
4. 先选择「P2P 优先，自动中转」。遇到问题时退出房间，在大厅选择「仅通过节点中转」后重新加入；此模式跳过 P2P 协商。自动模式在协商失败时自动中继，既有游戏 TCP 连接中断时仍需在 Minecraft 内重新连接。
5. 复现后点击大厅顶部「导出日志」，保存 ZIP；两端各导出一份。导出在后台重新采集当前网络，不要求先成功加入房间。提供发生时间、游戏版本、双方网络说明和 ZIP 即可对照。

导出包包含 `p2p-sessions/network-export-*.json`：网卡及本地地址、Windows 网络配置类型、有线/无线网卡类型、默认网关、DNS、IPv4/IPv6 路由表。此前各次联机的网络快照与会话日志继续保留；STUN、ICE 候选和选中链路记录在对应会话日志中，可用 trace ID 对照。仅凭本地路由或一次 STUN 不能确认上游路由器数量、完整 NAT 类型，未测得的值保持未知。

当前选中实例的 `logs/latest.log`、`logs/debug.log`、最近 20 份轮转日志、最近五份客户端崩溃报告与 JVM 的 `hs_err_pid*.log` / `replay_pid*.log` 同时导出，归档在 `game/`。压缩日志解压后过滤凭据，单份解压最多 32 MiB。`game/inventory.json` 包含模组文件名、大小、版本/ID/名称/声明依赖等元数据，以及资源包、光影包文件列表、游戏与继承版本元数据、Java 版本、系统和内存信息；显卡与驱动信息保存在网络快照的 `graphics` 中。JAR 仅读取清单，不执行代码、不导出二进制、不计算全部模组哈希，以降低磁盘负担。单份模组元数据上限 256 KiB，合计 8 MiB，文件列表每类最多 5000 项。

过滤 token 和命令行认证参数，不导出账号配置或世界存档。导出日志合计最多 200 MiB。`diagnostics.json` 记录实际采集清单、当前实例路径、缺失的游戏日志及网络采集错误，采集失败时不再无声遗漏。没有生成的日志和未声明的模组信息保持缺失，不以导出成功表示全部资料存在。

## 更新节点接入码

已有匿名节点时，直接粘贴网页登录后领取的个人接入码。相同公钥的节点会显示更新确认；确认后覆盖旧接入码并刷新账号与好友，无需先删除匿名节点。重新领取个人码也是同样流程。取消则保留原码。个人码过期、缺少好友授权或服务验证失败时，大厅显示原因和重试入口；不会一直只显示「个人码待验证」。现有房间保持连接，新码用于后续连接。

## 人数与退出检查

- 分别用 P2P 和仅中继加入同一房间：节点的房间成员数应包含两者，不能按中继游戏流数量推算人数。成员已加入但尚未进入 Minecraft 时，只增加房间成员数。
- 多名玩家进入 Minecraft 后核对游戏内人数，再让一人退出游戏但保留启动器房间连接：游戏内人数应下降，成员数保持不变。房主约每 2 秒上报，网页约每 5 秒刷新；读取失败或超过 15 秒未上报时显示未知，不能作为零人。开启聊天同步时，游戏内人数扣除聊天虚拟玩家。
- 访客手动关闭主启动器后应退出成员列表，房主和其他成员继续连接；房主手动关闭后，房间应移除，访客收到房间关闭。也要覆盖 Minecraft 仍运行，以及先退出房间马上关闭启动器两种情况。
- 游戏启动后的自动隐藏、最小化和关闭大厅窗口应继续保持房间。强制结束进程或断网属于异常掉线，节点检测后仍有 120 秒恢复宽限期；记录检测与回收时间，不按手动退出的即时清理标准判断。

## 保存内容

- Windows 日志在启动入口的日志目录；直接运行解压包时在 EXE 旁，从安装入口运行时在安装入口旁。macOS 默认 `~/Library/Logs/Buggcraft`。可用 `BUGGCRAFT_LOG_DIR` 指定目录。
- `buggcraft.log` 保留应用事件；`p2p-sessions/<UTC 时间>-<进程号>.log` 每次启动单独留存，记录 STUN 选择、ICE 状态与候选、选中路径、连接耗时、流量汇总、中继降级原因和异常。不会按每个游戏数据包刷日志。
- `p2p-sessions/network-<trace_id>.json` 每次建立联机端点时异步保存，包含网卡、地址范围、路由、网关、DNS 和代理环境变量是否存在。相同 `trace_id` 可关联连接事件。Windows 采集有 8 秒时限，失败时仍保存已有信息，不阻塞联机。
- NAT 类型证据不足时为 `unknown`。局域网地址、CGNAT 地址段和单个 STUN 映射均不能单独证明某种 NAT 类型；路由快照也不能替代其他运营商和路由器的实际环境。
- 每个会话日志为 10 MiB 轮转、最多 8 个备份；旧会话不会因重新启动被覆盖，可按需手动清理。导出按新到旧最多纳入 200 MiB 原始日志，超额文件列在 ZIP 的 `diagnostics.json` 中。
- 导出不包含账号设置、节点配置或游戏存档；密码、令牌和 ICE 密码会脱敏。为排障保留 IP、网卡名称与本地路径，请通过私下渠道提供。

## 开发者复测

联机底层测试在 `minecraft-tunnel-native` 中执行，先运行 `ctest --test-dir build --build-config Release --output-on-failure`。启动器仓库使用以下 pytest 用例验证原生调用边界和真实界面：

```powershell
.build-venv/Scripts/python.exe -m pytest -q tests/test_native_bridge_runtime.py tests/test_native_bridge_services.py tests/test_native_cutover.py tests/test_native_routes.py tests/test_native_transport_poll.py
$env:QT_QPA_PLATFORM = 'windows'
.build-venv/Scripts/python.exe -m pytest -s -q tests/test_client_ui_acceptance.py tests/test_friend_entry_ui.py
```

`test_native_bridge_runtime.py` 使用真实 C++ Bridge DLL / EXE；`test_native_bridge_services.py` 在隔离进程中执行原生仓库的本机节点验收，缺少构建或测试依赖时明确跳过。UI 用例通过 Qt 鼠标键盘事件操作生产页面，联机服务响应使用隔离夹具。Minecraft 进程和公网连接需按 [联机回归用例](../technical/multiplayer-regression-cases.md) 另行记录。旧 Python SSH/ICE 测试和脚本已移除。

本机自连验证实现和真实游戏流量，不能证明跨家庭宽带、校园网、移动网络或对称 NAT 的打洞成功率。不同网络的测试结果需分开记录。
