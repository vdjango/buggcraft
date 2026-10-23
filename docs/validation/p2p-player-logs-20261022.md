# 2026-10-22 玩家 P2P 失败分析与修复

分析输入：工作区 `error/` 下的三个 `Buggcraft-diagnostics-20261022-225639.zip`、`225707.zip`、`225711.zip`。原包保留，解压和本轮验证输出位于 `error/p2p-analysis/`。

2026-10-23 更新：已进一步按 STUN 目标的实际路由选择探测接口；本机同节点验证的建连时间从 10.656 秒降到 1.781 秒，两个 VMware 接口的局域网候选继续保留。详细策略与回退见文末。

## 已确认的失败原因

三个诊断包对应一位房主、两位访客，合计五次访客 P2P 尝试。五次均在默认的 **4 秒总协商超时**后进入 SSH 中转；房主尚在收集本地候选，没有发出 answer，访客 ICE 保持 `new`。因此这些记录没有进入双方候选间的连通性检查，无法用来判定玩家 NAT 是否支持打洞。

房主同时启用 WLAN、VMware VMnet1 和 VMnet8。aioice 对所有候选接口查询 STUN：WLAN 很快取得应答，两个 VMware 接口不断报 `WinError 1231`，候选收集仍等待这些任务，底层上限是 **5 秒**。原来的总协商超时比单次候选收集上限还短。

第一轮的具体证据如下，各机器绝对时钟存在偏差，需结合各自持续时间和信令顺序判断：

| 位置 | 日志证据 | 含义 |
| --- | --- | --- |
| 房主 `225707`，会话 `20261022T134921.565508Z-79984.log:5170` | 22:17:03.369，`gathering=gathering` | 开始生成 answer 的候选 |
| 同一房主日志 `:5187` 附近 | 两个协议报网络不可达，第三个协议约 20 ms 后收到 STUN Binding RESPONSE | 公网 STUN 服务可用，但多接口收集尚未完成 |
| 同一房主日志 `:5227` | 22:17:07.103，`connection=closed gathering=gathering` | 候选收集结束前，访客离开导致连接关闭 |
| 访客 `225639`，会话 `20261022T140423.629398Z-17256.log:198` | 22:17:03.937，本地候选收集已完成，含 `srflx` | 访客已获得公网映射 |
| 同一访客日志 `:210` | 22:17:07.671，`peer_fallback`，堆栈停在 `connected.wait()`，`TimeoutError` | 等待房主 answer 期间触发总超时 |

后续 22:18、22:23 和 22:29 的两次并发访客尝试重复同一模式。原实现回退后销毁 P2P 对象并创建固定 SSH 转发，不会在本次连接中继续等待迟到的 answer，所以界面一直显示中转。

日志中的无效链路本地地址和停用网卡还会导致 `WinError 10049`；它们增加噪声，但本轮阻塞候选收集的是仍启用、无法访问 STUN 的 VMware 接口。单纯过滤停用网卡无法独立解决该超时问题。

## 代码修复

- `hookup/relay.py`：默认协商预算改为 15 秒，覆盖双方顺序执行的两次最多 5 秒候选收集及信令、ICE、DTLS；显式更短预算仍生效，失败仍回退中转。
- `hookup/ice.py`：通过局部 aioice 子类过滤已确认停用接口及回环、链路本地等无效地址。启用的虚拟/VPN 接口保留，仍可用于同网段玩家；不通过名称禁用 VMware。接口状态读取失败时保留有效地址。
- `hookup/bridge.py`：房间上线的外层等待增加到 30 秒，避免在新的 P2P 预算耗尽、完成中转回退前终止整个加入过程。
- `hookup/peer.py`：记录 offer/answer 的发送、接收和耗时，记录回退所处阶段与异常类型，不记录完整 SDP 或 ICE 密钥。
- 同步维护生成脚本和生成模块 SHA-256，可按原有流程重现数据通道子集。
- bridge 依赖清单同步加入 `psutil`，确保独立组件也能读取网卡状态。

## 验证

新增正式回归使用真实本机 SSH、ICE、DTLS、SCTP 与 UDP 黑洞服务。双方 STUN 收集各等待约 5 秒后，仍通过 host 候选建立 P2P，随后完成 128 KiB 双向逐字节校验，并禁止游戏打开中转连接。旧实现约 4.84 秒失败并显示 `relay`；修复后约 13.18 秒完成整项测试。输出分别为 `regression-before.log`、`regression-after.log`。

另在保留两个 VMware 网卡的本机，使用玩家节点 `81.68.225.236:3334` 的真实公网 STUN：双方均获得 `srflx`，约 **10.656 秒**建立 P2P，随后完成 **2 MiB 双向逐字节校验**，游戏中转连接为零。结果为 `public-stun-result.json`，详细信令为 `public-stun-detail.log`，重现脚本为 `verify_public_stun.py`。最终选中本机 VMware 的 host 候选，因此这是多接口超时修复与公网 STUN 验证，**不是跨 NAT 验收**。

正式回归 **30 项全部通过，92.852 秒**，结果见 `p2p-regression-final.log`，覆盖地址过滤、P2P/中转、协商超时、混合房间、通道 ID、退出清理、新旧数据通道互通、证书指纹校验、生成文件校验和 stdio bridge。PowerShell 把 unittest 的 stderr 包装成 `NativeCommandError` 文本，验证依据为 Python 退出码 0 和日志末尾的 `Ran 30 tests / OK`。

`225711` 的崩溃文件另有 `0x8001010d`，当前线程位于 `main.initialize_application`，其他线程在下载。该堆栈没有 P2P 协商调用，现有记录不足以将此崩溃与上述 4 秒协商超时建立因果关系，本轮没有把它记为已修复。

## 玩家复测

本轮修改源代码，未替换玩家使用的 Windows 成品。重新打包后让房主和两位访客使用新版本，退出并重新加入房间。仅重启旧包不会应用修复。

复测时观察 `peer_signal_sent type=offer`、房主的 `peer_signal_received type=offer` / `peer_signal_sent type=answer`、访客的 `peer_signal_received type=answer`，以及 `selected_pair`、`peer_ready`、`endpoint_online path=p2p`。若收到 answer 后仍失败，用新增的 `stage=ice-connect`、ICE 检查和双方候选进一步判断 NAT、防火墙或运营商 UDP 限制。

本次诊断包的 NAT 类型为 `unknown`，也没有可用公网 IPv6 候选，不能据此认定对称 NAT 或承诺所有玩家可直连。真正不支持直连的网络仍会在预算结束后使用中转；自动模式下，加入失败网络时等待可能比旧版本增加约 11 秒。

## 2026-10-23 按实际出口探测与分层回退

策略按系统路由判断，没有固定 WLAN、以太网或 VPN 的名称：

1. 对所有有效接口绑定真实 UDP socket，保留 IPv4/IPv6 的 host 候选。单个接口绑定失败只跳过该地址；全部无法绑定时直接进入中转回退。
2. 把选中的 STUN 主机解析为 IPv4 目标，DNS 等待不超过 500 ms；通过不发送数据的 UDP `connect()` / `getsockname()` 询问系统实际出口。STUN 请求使用同一个已解析目标，避免 DNS 结果变化导致出口判断与请求目标不一致。
3. 优先在匹配该出口的 socket 上查询 STUN，成功即结束收集，其他网卡继续保留局域网候选。
4. 首选接口报错立即扩大到其他有效 IPv4 接口；1 秒仍无响应也扩大范围。首选请求继续等待，迟到的有效应答仍可使用。任一接口得到有效映射后停止多余探测。
5. 路由查询失败或返回的出口没有成功绑定时，回退为全部有效 IPv4 接口并行探测；DNS、首选与后备探测共享最多 5 秒的收集预算。
6. STUN 全部失败仍使用 host 候选尝试局域网/VPN 直连；协商的总预算继续为 15 秒。ICE 明确失败、信令断开或节点报告不可用时立即降级 SSH，不必耗尽预算。数据已经发送的游戏 TCP 流不重放，失败后的新连接可走中转。
7. 返回或取消前取消并等待全部 STUN 任务，清理事务和重传定时器；访客中途退出时，房主立即取消该访客的应答任务，其他访客继续正常使用房间。关闭流程继续回收 UDP、DTLS、SCTP 和游戏监听。

该改动局限于 `hookup.ice.Connection` 的候选收集策略；ICE 连通检查、候选选定、DTLS 指纹校验和 SCTP 仍使用原实现。配置 TURN 的调用者继续使用上游收集方法。

日志使用 PeerConnection 的 `trace` 关联出口决策、探测、候选和回退，已加入正式连接日志的 logger 配置与导出路径：

| 日志事件 | 可检查的内容 |
| --- | --- |
| `ice_host_bind` / `ice_address_skipped` | 无法绑定或被过滤的地址及原因 |
| `ice_gather_policy` / `ice_route` | STUN 目标、系统出口、候选数量，以及是否退回全部接口 |
| `ice_stun_start` / `ice_stun_result` | 首选/后备接口、映射地址、异常类型、耗时或取消原因 |
| `ice_stun_fallback` | 首选报错或响应慢，剩余接口数量与预算 |
| `ice_gather_complete` | 保留的 host/srflx 数量、完成原因和总耗时 |
| `peer_signal_sent` / `peer_signal_received` | offer/answer 的流向与耗时 |
| `peer_fallback` / `peer_fallback_complete` | 异常类型、协商阶段、预算及中转清理完成 |
| `game_path` / `selected_pair` | 实际游戏路径及选中的候选对 |

这些事件不增加完整 SDP、密钥、令牌或密码记录；日志仍经过现有脱敏格式器。

保留两个 VMware 接口、继续使用 `81.68.225.236:3334` 公网 STUN 的实测中，两端各保留三个 host 候选，但 STUN 只查询 WLAN 的 `192.168.2.6`：每端候选收集约 **62 ms**，完整建连 **1.781 秒**，**2 MiB 双向逐字节校验通过，游戏中转连接为零**。原始输出为 `error/p2p-analysis/route-first/public-stun-result.json`、`public-stun-detail.log`。与上一轮一样，两个端点都运行在本机，选中 VMware host 候选，该结果验证出口策略及本机加密传输，不能代替玩家跨 NAT 复测。

故障测试同时覆盖路由未知、出口地址未绑定、主接口报错、主接口慢/迟到应答、STUN 全黑洞、接口消失、IPv6 host 保留、查询超时、取消与 socket 回收、ICE 明确失败、信令不可用/断开、中途退出后房间仍能继续加入。最终 **58 项回归全部通过，耗时 103.813 秒，Python 退出码为 0**；正式回归日志为 `error/p2p-analysis/route-first/regression-final.log`。

负载校验通过的验证日志仍可能包含状态探测连接重置及流 ACK 收尾超时告警；本轮不把它记为长时间稳定性或跨 NAT 验收。当前仍为源码修改，未重新生成或发布 Windows 成品。
