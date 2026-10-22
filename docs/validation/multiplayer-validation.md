# 联机验证记录

游戏与服务测试日期：2026-10-18；大厅布局、流程及双向游戏聊天回归更新于 2026-10-20。代码仍处于发布验收阶段。产品实现使用 Python；独立测试目录中的 Mineflayer/Java 辅助程序用于执行协议角色操作及验证原版 LAN 解析，不是产品运行依赖。

## 已通过

|验证|实测结果与边界|原始记录|
|---|---|---|
|真实游戏四角色十轮|原版 Java 1.21.8，独立本机世界；一个角色直连主机，三个角色经授权公网节点进入同一世界；移动、破坏/放置及其他角色观察、同 UUID 退出重入、物品/位置和方块持久性每轮通过；最终部署后重跑通过|../../../multiplayer-tests/gameplay-result.json|
|持续游戏稳定|四角色十轮后保持 1801 秒，未记录失败事件；总记录 UTC 14:45:27 至 15:19:26；这次持续测试早于最后的全局/单客户端限额变更|../../../multiplayer-tests/gameplay-soak-result.json|
|图形客户端进入世界|四个独立原版客户端曾分别进入隔离测试世界，服务端日志确认；完整键鼠操作、截图和多人菜单点击验收尚未完成；四客户端现已静音|../../../multiplayer-tests/game-server/logs/|
|真实 LAN 接收与列表|使用安装的原版 1.21.8 接收器及房间列表解析类，收到 127.0.0.1:25576；未修改游戏 jar；这验证报文链路，不等于画面点击验收|../../../multiplayer-tests/lan-result.json|
|大厅 LAN 自动检测|真实原版服务返回版本 1.21.8、协议 772；本机发现后探测成功，已加入的代理端口可排除|../../../multiplayer-tests/lan-probe-result.json|
|QML 大厅集成|真实点击新的 QML 控件；分页面导航、两步创建、LAN 查找与状态探测、搜索、好友新增/编辑/移除确认、版本不匹配、重复连接复用、复制与关闭重开通过；好友/公开列表交替加入、64 KiB 校验、离开连续 10 轮；三个并存房间及长名称；900×620 和 1120×760 布局截图检查；无 QML 运行错误；真实本地加密节点与状态/回显测试端，不属于游戏角色测试|../../../multiplayer-tests/ui_integration.py|
|大厅与游戏双向聊天|4 个隔离启动器窗口（1 房主、3 客户端）及 4 个进入同一 vanilla 1.21.8 世界的游戏协议玩家；大厅 QML 发言到达所有游戏角色，任一游戏角色发言均出现在 4 个大厅聊天列表；10 轮双向收发，聊天通道断开并重连后继续双向收发，无游戏错误或 QML 运行错误|../../../multiplayer-tests/chat-game-ui-result.json、../../../multiplayer-tests/chat-game-ui-console.log、../../../multiplayer-tests/chat-game-ui-0.png|
|100 条同时活动通道|100 个独立加密访客连接、100 条活动游戏 TCP 通道，10 轮共回传 32,768,000 字节且逐字节一致；最近结果约 16.0 MiB/s；单次 32 KiB 满载回显 P50 177.58 ms、P95 188.56 ms|../../../multiplayer-tests/capacity-result.json|
|公网转发往返|3 个客户端、300 次 64 字节回显；最终部署后 P50 38.97 ms、P95 47.50 ms、最大 63.24 ms；主机和客户端位于同一测试电脑，并非不同地区真实玩家的 SLA|../../../multiplayer-tests/node-latency-result.json|
|自动化回归|unittest discover 共执行 32 项通过，包含继承/导入导致重复执行的基础传输案例；覆盖认证、公钥、隔离、拒绝任意转发、断开清理、重启重连、限额释放、目录权限、超大报文、兼容检查、参数解析、原子保存和安全解压|../../../multiplayer-tests/test_rooms.py 等|
|启动器入口与状态|隔离配置下主窗口打开 QML 大厅，开始/下载/设置/实例切换；原启动布局保持；快速启动/停止状态、运行中错误提示、Java 搜索中关闭及联机后台清理通过；网络受限的版本清单失败不计为游戏下载验收|../../../multiplayer-tests/launcher_smoke.py|
|服务器部署|Ubuntu 原生 Python venv + systemd，公网 TCP 3333；最终服务启动于 23:22:22 CST，回归后检查 active，约 23.2 MiB 内存；没有 Docker|../../../minecraft-tunnel/deploy/|

四角色的操作由实际登录游戏世界的协议客户端执行，没有用回显 TCP 冒充角色。100 通道测试仅验证转发容量，没有 100 个游戏角色，也没有验证百人世界的游戏 tick、区块或主机性能。

2026-10-19 实例同步补充：`ui_integration.py` 实际点击 QML 已安装实例下拉框，验证 Fabric 派生版本自动识别、切换原版、未选实例保留邀请码并自动继续、版本不符拒绝；继续执行十轮加密连接与回显。`launcher_smoke.py` 使用实际首页控件验证双向同步、运行中的实例锁定与退出后恢复选择。上述均为界面与元数据/链路测试，本轮未重跑游戏角色操作。

2026-10-19 选择控件补充：扩展 `launcher_smoke.py`，实际点击首页弹层的文字区域、悬停其他版本、键盘选择及连续十次取消/重开；检查每次点击仅激活一次。空目录、目录切换、展开后文件消失、21 项长列表边界与滚动、外部点击传递、右键不触发、共用设置下拉框箭头点击与悬停不提交均通过。空弹层的 Esc 与已打开大厅快捷键冲突已复现并修复。截图见 `../../../multiplayer-tests/version-picker-hover.png`、`version-picker-long-list.png`、`settings-picker-hover.png`。本机原配置指向的 `F:/HMCL-3.6.12/.minecraft/versions` 实际为空，与缓存中的两个 Forge ID 不一致；刷新会清除失效选择，不会伪造安装成功。

## 本轮未完成的验收

macOS/Linux 图形客户端真机、完整四图形窗口键鼠操作、真实百人角色和多地区网络、整合包兼容矩阵、24 小时以上稳定性、丢包/抖动/带宽受限场景、节点故障迁移、全部游戏下载与安装流程、签名安装包和正式发布检查均待完成。现有单节点不能承诺高可用。邀请持有者共用房间能力，扩大使用前仍需独立主机凭据和邀请轮换设计。

## 可重跑入口

在工作区根目录运行；测试使用隔离存档与测试账号，不能替代正式玩家身份认证。

    python -m unittest discover -s multiplayer-tests -p "test_*.py" -v
    python multiplayer-tests/ui_integration.py
    python multiplayer-tests/launcher_smoke.py
    python multiplayer-tests/lan_actual.py
    python multiplayer-tests/probe_game.py
    python multiplayer-tests/node_benchmark.py
    python multiplayer-tests/gameplay.py --rounds 10 --soak-seconds 1800

游戏测试需要已安装的 Java 21、原版 1.21.8 资源、隔离目录中的服务端和 Node 测试依赖。脚本中的 Java 路径和资产位置属于本机测试配置。gameplay.py 和 probe_game.py 共用隔离世界与 25575 端口，应顺序运行。gameplay-result.json 会覆盖前次记录，长稳结果已经另存。公网测试使用 git 忽略的可信节点配置，文档和结果不含访问 token。

2026-10-20 大厅重设计回归：在固定 721×505 窗口使用顶部标签导航，移除可折叠菜单；沿用首页暗紫配色、像素品牌及正常文字大小。真实 QML 点击覆盖创建、查找世界、实例选择、加入、搜索、好友新增/编辑/移除、节点选择/导入/导出、关闭后重开和版本拒绝；10 轮本地加密加入/64 KiB 校验/离开、三个同时存在房间通过，无 QML 错误。正式 `buggcraft/tests` 中的布局用例另检查列表空间、主操作、固定导航与好友按钮文字可读性。此项为界面和本地协议验证，没有重新执行公网游戏角色操作。

界面参考：[QML 多房间大厅](../../../multiplayer-tests/lobby-multiple-rooms.png)、[721×505 大厅](../../../multiplayer-tests/lobby-preview-compact.png)、[空房间态](../../../multiplayer-tests/lobby-preview-empty.png)、[创建第一步](../../../multiplayer-tests/lobby-create-step1.png)、[创建第二步](../../../multiplayer-tests/lobby-create-step2.png)、[好友页](../../../multiplayer-tests/lobby-friends.png)、[加入后的指引](../../../multiplayer-tests/lobby-client-ready.png)。截图来自实际 QQuickWidget 页面，已检查，不包含服务访问凭据。构建脚本的 QML/Qt Quick 资源配置经 dry-run 检查，未编译正式安装包。迁移范围见 [QML 界面说明](../technical/qml-interface.md)。

2026-10-20 房间沟通回归：顶部搜索可按名称/版本/加载器过滤并显示匹配房间数；好友窗口可从首页或大厅独立打开和关闭。连接详情内的房间聊天经过实际 QML 发送/接收验证。正式游戏集成用例启动本地 1.21.8 vanilla 世界、一个房主观察桥和 4 个实际游戏角色（房主角色加 3 个隧道客户端角色），双向聊天 10 轮、断开/重连聊天通道后继续收发，并经过 16 秒游戏保活；均为本机回环，不是公网测试。节点聊天中继另有三客户端隔离、最近历史、伪造身份/游戏操作拒绝、速率及超长帧测试。聊天桥只覆盖文档列出的离线/LAN vanilla 条件，不能外推为所有版本、模组或正版在线验证兼容。独立好友窗口、超长 Unicode 消息分段与未识别游戏包回归列入正式单元测试。

本轮 `buggcraft/tests` 共 49 项通过，`multiplayer-tests` 既有 49 项回归通过；首页入口及 QML 实点回归通过。2026-10-20 已升级授权 Ubuntu 节点的房间聊天模块，保留旧模块回滚副本；服务正常重启。公网节点另完成 3 客户端、2 个隔离房间、10 轮消息、断线重连和最近历史补发验证，没有在本次公网验证中发送游戏数据包。记录：[游戏双向聊天](../../../multiplayer-tests/chat-game-result.json)、[公网节点聊天](../../../multiplayer-tests/chat-node-result.json)。

2026-10-20 大厅层级调整：标签与搜索同排，创建/加入/刷新和数量同排，下面直接显示房间列表。创建和邀请码加入页隐藏大厅菜单与好友浮钮，实际返回、取消、探测、实例选择、创建与加入流程通过。正式布局用例增至 12 项，检查各层位置、搜索与数量同步、搜索保留、浮钮拖动不打开窗口、边界、提示栏避让与键盘访问。`buggcraft/tests` 全量 51 项通过（53.4 秒），包含本地真实游戏四角色双向聊天、10 轮和重连；随后新增两项提示栏避让用例，布局 12 项再跑通过。实际 QML 回归仍覆盖好友操作、房间聊天、连续 10 轮加密加入/64 KiB 校验/离开、三房间并存，无 QML 错误；本次布局调整未重跑公网负载。

2026-10-20 导航细化：空会话隐藏“我的房间”，创建/加入后出现，取消与无效邀请不产生空入口；连接中、重连、失败和离开记录仍能查看。二级页面返回入口移至标题栏左侧，移除大厅顶部品牌图片和房间详情底部重复返回；独立好友编辑页同样支持标题栏返回且不保存未提交表单。`test_lobby_layout.py` 14 项、`test_lobby_navigation.py` 2 项通过；真实 QML 点击重新执行并通过，仍覆盖十轮加密加入/离开与三房间并存，无 QML 错误。

2026-10-20 大厅与游戏聊天端到端回归：启动 4 个真实启动器 QML 大厅窗口，完成一个房主和三个客户端加入；再用 4 个 Minecraft 1.21.8 游戏协议玩家进入同一隔离世界。通过每个 QML 房间聊天输入框交替用 Enter/发送按钮发言，四个游戏角色均收到；再由四个游戏角色轮流发言，确认所有四个可见大厅列表各出现一次且来源/昵称正确。完整往返 10 轮后，断开一个客户端的独立聊天 SSH 通道并确认重连，再双向发言成功。测试保存 QML 聊天窗口截图、游戏服务端日志及机器可读结果。它验证游戏协议会话和真实 QML 收发界面，不是四个可视 Minecraft 图形客户端测试；版本为 vanilla 1.21.8 / 协议 772，其他协议、正版在线验证及模组核心仍按上文的支持边界处理。重跑：`python -m unittest discover -s tests -p test_game_chat_ui.py -v`。

2026-10-20 多版本游戏聊天桥回归：通过 Mojang 版本清单校验的 vanilla 服务端，对 1.6.4/78、1.7.10/5、1.8.9/47、1.12.2/340、1.16.5/754、1.18.2/758、1.19/759、1.19.2/760、1.19.3/761、1.20.1/763、1.20.4/765 分别完成 10 轮跨观察者双向消息、同名参与者重连及 12 秒 keepalive。1.6.4 同时验证旧版状态探测、握手和加密传输。结果见 [`chat-version-results.json`](../../../multiplayer-tests/chat-version-results.json)。这是离线/LAN vanilla 协议覆盖，不代表正版在线认证、强制签名聊天、Forge/Fabric 等模组握手兼容。

2026-10-20 房间生命周期回归：临时关闭主机世界后，访客收到 waiting 状态，房间聊天仍可用；重开同端口恢复数据转发；房主网络中断进入宽限期；房主明确关闭时向三名访客广播 closed，断开游戏通道并在会话内清除房间和聊天记录。额外覆盖聊天通道暂时中断时通过状态轮询发现关闭。运行 `python -X utf8 -m unittest discover -s tests -p test_room_lifecycle.py -v` 和 `python -X utf8 -m unittest discover -s tests -p test_lobby_navigation.py -v`。

加入上述界面与游戏集成用例后，`buggcraft/tests` 全量 58 项在 86.8 秒内通过，无跳过项。覆盖聊天协议、房间隔离、去重、失败草稿与重试、两项真实游戏集成、界面导航/布局、下载工作线程、加载器目录、启动进程、设置隔离及版本存储。测试在 Windows 本机回环完成；服务端离线测试世界的日志含无法访问公网公钥接口的环境错误和断开清理时的闭合通道告警，不计作正版认证或公网链路验收。

2026-10-20 最终复测：`buggcraft/tests` 全量 **72 项通过**（517.8 秒，无跳过），含上述 11 版真实服务端矩阵、四游戏角色与四 QML 大厅的双向聊天、房间临时等待/恢复、换 LAN 端口、明确关闭及断线访客停止重试。旧版 1.6.4 连接清理增加超时，避免 Windows 退出等待不结束。矩阵按观察者先登录、第二角色再登录的顺序冷启动，随后同时在线，避开此前 1.20.x 冷启动并发登录触发的服务端内部异常。原始输出见 [`launcher-suite.log`](../../../multiplayer-tests/launcher-suite.log)。PowerShell 将 unittest 的 stderr 包装为 NativeCommandError；验收以日志末尾 `Ran 72 tests / OK` 为准。

同日 `multiplayer-tests` 底层全量 **49 项通过**（89.2 秒），含十轮三客户端完整性/半关闭、100 条并发通道、节点重启恢复、房间关闭后旧邀请码失效；记录见 [`transport-suite-final.log`](../../../multiplayer-tests/transport-suite-final.log)。授权 Ubuntu 节点已原生部署本轮生命周期更新并验证三客户端、两房间、十轮聊天及关闭通知，结果见 [`chat-node-result.json`](../../../multiplayer-tests/chat-node-result.json)。

最终部署后的公网游戏操作复测于北京时间 2026-10-20 16:41–16:46 完成：1.21.8 原版世界、一名主机角色与三名经公网节点进入的访客角色，连续 **10 轮**，每轮四个角色分别破坏/放置方块、移动、退出并以同角色重进；所有观察者看到相同变化，UUID、位置、背包物品及方块变化保留。十轮后额外保活 **30 秒**，没有错误或被踢事件。房主同时运行游戏聊天桥。此项使用实际 Minecraft 协议角色，未操作四个图形游戏窗口。结果见 [`gameplay-result.json`](../../../multiplayer-tests/gameplay-result.json)、[`gameplay-final.log`](../../../multiplayer-tests/gameplay-final.log)。历史 1801 秒记录保留在 `gameplay-soak-result.json`，本轮没有把短保活计为新的长稳测试。

仍未验收：macOS/Linux 图形客户端、模组专用握手与强制签名聊天、真实百人游戏和本轮 24 小时长稳；完整启动器功能与正式发布待办仍见 [完善计划](../planning/multiplayer-roadmap.md) 和 [启动器操作验收](launcher-validation.md)。全正式版的协议映射、独立协议分支及逐版实服回归见下文。

2026-10-20 标题栏整理：大厅与好友窗共用轻量标题栏，一级页有窗口名称，二级页返回箭头与页面标题同排；删除正文重复标题，创建与加入页统一底部取消/提交。正式布局测试 **18 项**、导航测试 **4 项**通过，覆盖标题唯一性及对齐、窗口控制不遮挡、好友编辑返回不保存、加入页提交与取消。实际 QML 操作回归完成十轮加密加入/64 KiB 校验/退出、三房间并存及版本拒绝，未发现 QML 错误。随后重新执行四大厅窗口与四游戏协议角色的 **10 轮双向聊天**，包括聊天通道重连，全部通过；结果见 [`chat-game-ui-result.json`](../../../multiplayer-tests/chat-game-ui-result.json)。本轮仅改界面，未改聊天/转发协议。

2026-10-20 Java 全正式版聊天协议回归：Mojang 正式版本清单中 1.6.4 至 26.3 共 85 个 Java 版均有协议档案；每个独立协议分支均使用 SHA-1 校验的 Mojang 原版服务端进行 10 轮双向收发、同一身份退出重进和持续连接检查。52 种现代协议加 1.6.4 旧协议全部通过，并额外通过 1.7.3 与 1.13.2 两个服务器样本；合计 55 项通过、零失败，耗时 639.3 秒。机器结果见 [chat-version-results.json](../../../multiplayer-tests/chat-version-results.json)，完整日志见 [chat-all-protocols-20261020.log](../../../multiplayer-tests/chat-all-protocols-20261020.log)。协议映射完整性由正式单元测试核验；本矩阵验证 vanilla 离线/LAN 协议，不涵盖在线认证专服、强制签名聊天或模组握手。

随后补齐了共享协议的其余 30 个正式版，最终 **85/85 个正式版全部实服通过**，每版均含十轮消息、同身份重连和保活，机器结果保存在同一个 chat-version-results.json。增量回归及过滤修复后的重点版本重测见 [chat-all-releases-20261020.log](../../../multiplayer-tests/chat-all-releases-20261020.log)。修复新版私聊/队伍聊天向整个房间转发的问题，并增加正式单元测试；当前只转发原版公共聊天类型。版本覆盖单元测试改用 tests/fixtures/java_releases.json 内的 Mojang 清单快照，不再依赖本机下载缓存。全部服务端文件的发布者 SHA-1 复核记录见 [chat-publisher-verification-20261020.log](../../../multiplayer-tests/chat-publisher-verification-20261020.log)。本轮的逐版测试使用协议客户端，并非 85 版图形客户端逐版操作验收。

2026-10-20 最新代码最终全量复测：buggcraft/tests 共 **113 项，111 项通过、2 项跳过、零失败**，耗时 327.555 秒；原始 UTF-8 日志见 [launcher-suite-verified-20261020.log](../../../multiplayer-tests/launcher-suite-verified-20261020.log)。跳过项分别为需要已开放真实 LAN 世界的四大厅聊天测试，以及需显式启用的实际加载器安装到图形游戏进世界测试；默认套件中的四游戏协议角色、四 QML 大厅聊天集成及断线恢复均实际执行并通过。不能把这两项跳过视为本轮实际 LAN 或加载器安装通过。所有 85 个测试服务端再次按发布者元数据核对长度和 SHA-1，零不符。启动器在独立查看配置下重新打开，保留首页供桌面检查。在线认证专服、强制签名聊天、模组握手和快照版仍不在此次兼容声明中。
