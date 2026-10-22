# 多节点联邦验证记录

验证日期：2026-10-20。测试环境为 Windows 本地 Python 3.11、四个独立节点进程，以及 Ubuntu Python 3.12 的独立公网测试节点。

## 已完成

- 节点接入码：网页领取、启动器公钥校验后添加、去重保存、备用入口缓存；仍兼容 JSON 导入。
- 公开 HTTPS 状态页：桌面及手机布局，节点、房间、连接、通道、运行时间与 SSH 指纹。
- 管理与玩家授权分离：scrypt 摘要、登录限速、HttpOnly 会话、CSRF/Origin 校验，管理员可设置名称、领取策略、维护状态与本地隔离节点。
- 联邦：管理员邀请入网、传递发现、签名状态交换，跨入口定位房间，游戏连接直接到房间所属节点；无需主节点选举。
- 恢复：缓存入口离线后的替代连接、房间节点故障后的房主重建和访客重新定位；私密房间不公开元数据。

## 本地四进程测试

运行 minecraft-tunnel/deploy/local_cluster.py，四个服务监听 127.0.0.1 的 SSH 34331–34334 和 HTTPS 18443–18446。脚本通过真实管理员 HTTPS API 完成 B 加入 A、A 加入 B、C 加入 B、B 加入 C、D 加入 B，最终四个节点各看到完整网络。

在 `minecraft-tunnel` 仓库根目录运行：

    python deploy/check_cluster.py --clients 5 --report ../multiplayer-tests/node-cluster-results.json

结果：4 个房间、20 个启动器 SDK 客户端，每个客户端校验 1 MiB 回显，共 40 MiB 双向流量，单次完成耗时 1.80 秒。确认任意入口可发现各房间、客户端实际连接对应房间所属节点、SHA256 完整性和聊天隔离。这是本机集成结果，不是公网带宽、真实 Minecraft 人数或最大容量结论。

测试中发现持续同步会被重复首次接入消息暂时覆盖房间目录，已将首次接入与后续拉取分离；新增持续后台同步回归。另测试 128 间含最大长度 Unicode 元数据的房间，经分页在所有入口完整返回。

## 自动与浏览器回归

buggcraft 目录安装测试依赖并将两个项目源码加入 PYTHONPATH 后运行：

    python -X utf8 -m unittest tests.test_node_federation tests.test_node_portal tests.test_chat_controller tests.test_lobby_layout tests.test_visibility tests.test_version_storage tests.test_settings_isolation -v
    python -X utf8 -m unittest discover -s tests -p test_room_lifecycle.py -v
    python -X utf8 -m unittest discover -s tests -p test_room_chat.py -v

联邦测试覆盖传递发现、持续同步、跨入口数据与聊天、私密房间、入口缓存重载、入口故障、房间节点故障、公钥不匹配、伪造/重放/错误网络记录及 Unicode 满容量分页。网页测试覆盖公开信息脱敏、授权隔离、CSRF、Origin、限速、拒绝非对象 JSON 和远端明文认证。控制器覆盖验证失败与过期结果不落盘，以及去重保存和备用入口持久化。

最终合并运行上述联邦、网页、控制器、布局、可见性、版本存储、设置隔离、房间生命周期及聊天测试，共 62 项全部通过，耗时 103.858 秒。Qt 退出时仍出现既有的 3 个不可回收对象 ResourceWarning，不影响本次断言结果，但未据此宣称完整客户端发布验收。

真实 Edge 检查了本地网页领取接入码、管理员登录、节点清单和登出；公网网页以 1440 像素桌面和 390 像素手机检查，无横向溢出、无 JavaScript 错误。截图在 ../../../multiplayer-tests/node-web/。

## 公网独立测试部署

公网网页：https://81.68.225.236:18443/；联机节点 TCP 3334。使用自签名 HTTPS 证书，首次访问请核对私密凭据文件里的证书 SHA256；正式部署建议域名及受信任证书。

- 独立目录：/opt/buggcraft-federation-test-20261020。
- 独立 systemd 服务与非登录账户：buggcraft-node-test.service / buggcraft-node-test。
- 配置目录：/opt/buggcraft-federation-test-20261020/config/node，仅服务账户可访问。
- 已设置开机启动，使用专用 venv、资源限制与 systemd 文件系统保护。
- 只新增 UFW 的 TCP 3334 和 18443 放行规则。
- 管理员与玩家密码已私下保存到本机 minecraft-tunnel/config/remote-test/admin-credentials.txt；不要提交或公开该文件。远端 SSH 凭据未复制进项目配置。

公网验证：HTTPS 可达、管理员/玩家鉴权与登出成功、SSH 公钥固定验证通过，真实 SDK 经公网节点完成 2 MiB 双向回显完整性测试。部署前后 Nginx 配置 SHA256、网站内容 SHA256、Nginx 和原 buggcraft-relay 的进程 ID 均相同；网站仍为 HTTP 200。原 80 端口网站与 3333 端口联机服务未修改、未重启。

节点维护命令：

    sudo systemctl status buggcraft-node-test.service
    sudo journalctl -u buggcraft-node-test.service -n 100 --no-pager
    sudo systemctl restart buggcraft-node-test.service

按用户要求，每次同步更新后重启本测试服务，并检查公网状态与页面，方便直接刷新查看。2026-10-20 已执行重启并重新验证公网网页、鉴权及转发；原网站和旧服务保持运行。

需要停止本次测试时只操作 buggcraft-node-test.service。升级时保留配置和密钥，维护窗口内仅重启该测试服务。

## 账号、心跳和代理入口补充验证

本轮联邦、网页、账号、控制器、布局、房间生命周期及聊天的组合回归共 57 项通过，耗时 113.613 秒。随后补充代理入口地址更新回归：账号相关 8 项通过，耗时 6.603 秒；重新运行联邦 7 项全部通过，耗时 85.689 秒。两次测试范围重叠，不相加作为唯一测试数量。

Edge 实际使用 WebCrypto 完成 A 注册、密文设置同步、B 登录与资料解密，检查发出请求和 B 磁盘副本未含明文密码或私密备忘。记录在 ../../../multiplayer-tests/node-account-browser-results.json，截图 account-desktop.png、account-mobile.png。启用账号模块后的四进程匿名联机仍完成 4 房间、20 客户端、40 MiB 校验，耗时 2.37 秒，记录 node-cluster-accounts-results.json。

已向独立公网测试服务同步 47 个源文件并重启，保留原有配置和密钥。更新后再次验证公开 HTTPS、管理员和玩家授权、SSH 固定公钥及 2 MiB 双向转发；网站内容及 Nginx 配置哈希、原网站和旧联机服务进程均未改变。真实浏览器验证管理页注册开关保存后公开状态随之变化，并恢复原先关闭注册的策略；手机账号窗口无横向溢出，未出现脚本错误。截图 remote-desktop.png、remote-mobile.png、remote-admin.png、remote-account-mobile.png。

代理入口只完成配置及本地回归，目前没有独立 TCP 代理或防护资源，未设置源站访问限制，未验证代理后的公网访问；不能据此声称已经隐藏源站或抵御容量型攻击。详细说明见[账号与源站保护](../technical/node-accounts-security.md)。

## 服务端清理与节点入口改版

2026-10-20 已核对入口和导入引用，将未使用的旧 common/core/discovery/loadbalancer/monitor/network/node 框架、plugins、example、空 Docker 配置、旧 activate.bat、tree.txt 和旧架构图移出服务项目。本机可恢复备份位于 E:/code/.task-archives/minecraft-tunnel-legacy-20261020；未清理配置、密钥或当前 tunnel 实现。requirements.txt 统一引用实际依赖，main.py 与 relay_main.py 共用启动函数，README 和协议文档按当前实现重写。

启动器移除节点 Tab；大厅右侧下拉框负责切换节点，“添加与管理节点”打开有返回入口的次级页，左侧管理已添加节点、右侧填写接入码。JSON 导入与接入码统一执行固定公钥和连接验证，成功后保存独立副本。界面以正式字体在 721×505 下检查；预览位于 E:/code/.task-archives/node-layout-20261020/。

本轮布局与控制器组合 33 项通过；网页、账号、联邦、房间生命周期及聊天组合 34 项通过；四 QML 大厅与四真实游戏协议角色十轮聊天集成 1 项通过。随后增加节点验证中、失败反馈下操作按钮不被遮挡的布局回归，单项通过，共 69 项。Qt 游戏集成退出仍有 1 个不可回收对象 ResourceWarning，未据此宣称发布验收。

清理后的四个独立节点使用 SSH 34531–34534、HTTPS 18643–18646，通过真实管理接口组成联邦。四房间、20 个匿名客户端完成 40 MiB 双向完整性、任意入口发现、所属节点中转和聊天隔离，耗时 3.27 秒。记录在 minecraft-tunnel/config/local-probe/cleanup/validation.json。

独立公网测试服务同步 20 个当前代码/说明文件并重启；旧框架目录移入该服务自身 updates 备份，不触碰其他服务。保留已有注册策略，本次观察为开放注册（默认初始化仍关闭），未替用户改回。公网 HTTPS、管理员和玩家鉴权、固定 SSH 公钥以及 2 MiB 双向转发全部通过；桌面 1440/手机 390 的真实浏览器无溢出或脚本错误。原网站仍为 HTTP 200，内容和 Nginx 配置哈希、原网站及旧联机服务进程未变。

## 当前限制

联邦当前最多 32 节点、每节点同步最多 128 房间，约每 2 秒同步、10 秒过期。恢复时间受网络和重试影响；已建立游戏 TCP、Minecraft 会话、内存聊天记录不能迁移，玩家需重新进入游戏。目录故障切换不等于游戏无损迁移。

这是互信运营者间的无主目录，不是 Raft 或拜占庭共识。支持本节点屏蔽成员，但不是全网身份封禁。成员共享入网授权，持密钥者可能创建新身份；不支持两个已有联邦在线自动合并，不提供按负载自动分房或抗容量型 DDoS 的基础设施能力。公网只部署了一台独立测试节点，多节点公网及真实游戏长期容量仍需后续验收。
