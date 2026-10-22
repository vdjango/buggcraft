# 启动器桥接接入

Buggcraft bridge 是运行在玩家电脑上的独立连接程序。第三方启动器通过标准输入输出调用 JSON-RPC 2.0，不需要 Python 环境，不需要集成 Python SDK，也不需要实现 SSH、ICE、DTLS 或 SCTP。节点服务仍独立部署在服务器上。

```text
你的启动器 ── 本地进程管道 / JSON-RPC ── buggcraft-bridge
                                               ├─ 节点：身份校验、目录与房间信令
                                               └─ 游戏：P2P 优先，必要时加密中转
```

## 下载与启动

从 [Package bridge 构建任务](https://github.com/vdjango/buggcraft/actions/workflows/bridge.yml) 下载对应系统的产物。Windows x64 为 ZIP，Linux x64、macOS Intel 与 Apple Silicon 为 tar.gz。解压并保留整个 `buggcraft-bridge/` 目录；Windows 启动 `buggcraft-bridge.exe`，其他系统启动 `buggcraft-bridge`。不能只复制可执行文件而丢弃 `_internal/`。

启动器以子进程启动它，重定向 stdin、stdout、stderr；Windows 可通过 `CREATE_NO_WINDOW` 隐藏控制台窗口。不要使用 shell 拼接命令，不要通过命令行传入接入码。程序没有公开 HTTP 端口，也不注册常驻系统服务。`--version` 输出构建提交、平台与协议版本。

每行一条 UTF-8 JSON 消息，换行后刷新 stdin。stdout 只含 JSON-RPC 响应；stderr 是诊断输出，应持续读取。当前请求串行处理，不支持 batch，不发送事件通知；启动器按需调用 `session.list` 刷新状态。初始化返回 `methods`，界面只展示组件实际支持的功能。

## 最小流程

1. 调用 `bridge.initialize`，确认协议版本为 1。
2. 将用户提供的节点接入码传给 `node.add`，保留返回的 `node` 句柄。
3. 房主调用 `room.host`，传入游戏的本机监听端口；把返回的房间邀请码交给朋友。
4. 访客调用 `room.join`，把返回的 `address`（如 `127.0.0.1:54123`）交给游戏。
5. 退出联机时调用 `room.close`；退出启动器前关闭 stdin 并等待桥接程序退出。

```json
{"jsonrpc":"2.0","id":1,"method":"bridge.initialize","params":{"protocol":1}}
{"jsonrpc":"2.0","id":2,"method":"node.add","params":{"code":"buggnode1-用户接入码"}}
{"jsonrpc":"2.0","id":3,"method":"room.join","params":{"node":"返回的节点句柄","invite":"bugg1-房间邀请码","transport":"auto"}}
{"jsonrpc":"2.0","id":4,"method":"room.close","params":{"session":"返回的会话句柄"}}
```

句柄只在当前桥接进程内有效，重启后重新添加节点。桥接程序不将用户接入码写入磁盘；启动器自行使用操作系统安全存储。匿名接入可联机，个人接入码携带账号授权，但当前桥接接口尚未提供好友操作和网页登录；不能因身份为 `account` 就声称已有好友接口。

## 接口

| 方法 | 参数 | 结果 |
| --- | --- | --- |
| `bridge.initialize` | `protocol:1` | 协议、构建信息、方法清单、资源上限 |
| `node.add` | `code` | `node,name,identity`，身份为 `anonymous` 或 `account` |
| `node.remove` | `node` | `removed`，有活动会话时拒绝 |
| `room.list` | `node,offset?` | 节点公开目录及分页信息 |
| `room.host` | `node,game_port,transport?` | `session,room,invite,transport,state` |
| `room.join` | `node,invite,transport?` | `session,room,address,transport,state` |
| `room.close` | `session` | `closed` |
| `session.list` | 空对象 | 当前会话列表、实际路径和本机地址 |

`transport` 默认为 `auto`，先尝试 P2P；指定 `relay` 只使用中转。一个房间的不同访客可以使用不同路径。默认创建的是邀请码房间；当前 `room.host` 尚未开放大厅公开房间设置，`room.join` 需要邀请码。节点原生协议中的扩展能力不等于桥接接口已经支持。

同一房间的直连对端会得知网络地址，需隐藏对端地址时选择中转。已建立的游戏 TCP 连接不能在网络断开后无损迁移；断线后需重新连接。公开节点协议和服务配置见[节点文档](https://github.com/vdjango/minecraft-tunnel/blob/main/PROTOCOL_STANDARD.md)。

请求最长 8192 字节（含换行），最多 16 个节点、8 个房间会话。请求不带 id 时为通知，无响应；不建议将创建会话作为通知发送，否则无法取得句柄。节点操作可能需要等待连接超时；应用应为建房/加入预留至少 30 秒，同时保持界面响应。正常退出先关闭会话，再关闭 stdin；超时后由宿主结束子进程，不能依赖强杀完成远端即时清理。

错误响应使用 `error.code/message`：标准错误 `-32700/-32600/-32601/-32602`，节点连接失败 `-32000`、未知会话 `-32004`、节点仍有会话 `-32009`、资源上限 `-32010`、房间提前关闭 `-32020`、启动超时 `-32021`。请求 id 必须与响应匹配，不要把错误响应当成成功。诊断和错误文本不应作为程序判断条件。

## 构建与验证

在目标系统使用 Python 3.11 安装 `requirements-bridge-build.txt`，执行 `python scripts/build_bridge.py`。不安装启动器 UI 依赖。当前传输实现使用完整 aiortc，因此包含其 PyAV 等依赖；没有宣称已完成网络库裁剪。发行目录附带许可、对应 Git 源码和依赖清单，压缩包旁提供 SHA-256。当前没有受信任的代码签名或 Apple 公证。

macOS Intel 的 cryptography 50.0.2 没有对应预编译 wheel。源码构建需准备 Rust 和 Homebrew OpenSSL，并先执行 `OPENSSL_STATIC=1 OPENSSL_DIR="$(brew --prefix openssl@3)" python -m pip install --no-cache-dir --no-binary cryptography cryptography==50.0.2`，再安装上述构建依赖。静态链接避免与 Python 自带的另一个 OpenSSL 3 动态库混用；CI 执行同一步骤。打包后的用户不需要这些构建工具。Linux/macOS 复制发行目录时须保留符号链接，发行文件因此采用 tar.gz。

设置 `BUGGCRAFT_NODE_SOURCE` 为节点源码仓库路径，运行 `python -m unittest tests.test_bridge_package -v`。设置 `BUGGCRAFT_BRIDGE_EXECUTABLE` 指向构建后的程序后，同一套用例还会复制完整发行目录到带空格路径，移除 Python 环境变量与开发工具 PATH，从无关工作目录运行二进制，验证两进程 P2P、中转、混合路径、兆字节传输、EOF、关闭释放端口、公钥拒绝及错误帧。

本机 P2P 测试不代表覆盖所有公网 NAT；跨运营商、对称 NAT、UDP 阻断仍需不同网络的设备验收。CI 只有测试通过才上传对应平台发行包。
