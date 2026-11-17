# 联机 HTTPS 稳定性与测试版发布

2026-11-18。修复对象为账号已授权后，内嵌联机桥报告 `HTTPS /v1/presence/open failed: Error`，无法进入联机大厅。启动器改动位于独立 worktree 的 `main`，保留移动端功能工作区及其未提交改动。

## 原因与实现

实际旧单文件桥的 `node.add` 复现了身份挑战请求失败；隔离重编译的动态桥也复现在线会话超时。当前系统把服务域名解析到代理 Fake-IP，连续健康请求有多次在 TLS 握手阶段超时；使用实际服务器地址并保持原域名和证书校验时，健康请求约 0.25 秒完成。没有修改用户代理、系统 DNS 或服务端配置。

单次动态 libcurl 测试曾出现 HTTP/1.1 成功、默认协议超时的差异；继续重复后确认 HTTP/1.1 同样间歇失败，且 Windows 单文件使用的裁剪版 curl 未启用 HTTP/2。因此未将 HTTP/2 作为结论，也未保留强制协议版本的临时改动。

原 `profile_exchange::https_json` 每次创建和销毁 curl handle；完整登录需要健康、身份挑战、证明、在线会话等多个独立 TLS 连接。修复仍扩展这一唯一所有者：每线程缓存至多四条连接，线程退出释放；重置请求选项后复用 TLS/keep-alive。瞬时连接错误最多三次尝试，单次连接三秒，共享原请求总期限；只有尚未到达 HTTP 请求发送阶段、零请求字节且无响应才允许重试。已发送的 POST、证书错误和业务拒绝不重放。错误增加数值码及 DNS/连接/TLS/响应阶段，避免裁剪版 curl 仅显示 `Error`。

启动器 Windows 单文件构建与 macOS/Linux 装配共同锁定 `v0.3.13-alpha.2` 桥。`BUGG_BUILD_VERSION` 保留完整测试后缀，CMake/Windows 数值资源使用数字基线，应用版本及 Windows 字符串资源使用完整版本。Mac bundle 的系统数值版本仍为数字基线。发布仍为 Prerelease，下载站仍使用测试渠道。

## 验证边界

- 修改前原生桥/节点 14 项相关回归通过；这不能替代 HTTPS 故障复现。
- 新增四项真实 TLS 故障回归通过：同线程复用连接且清除旧授权头；握手被中断可恢复且无重复 HTTP 操作；服务端读取 POST 后断开不能重放；不可信证书直接拒绝且不重试。
- 使用本机已保存的授权档案，新桥连续三次真实 `node.add` 成功，耗时约 3.08、12.09、3.08 秒；进程结束清理各自会话。没有将凭据、账号资料或请求体写入报告。
- 以上本地结果不等于所有平台、所有网络或全部游戏验证通过。

Mac CI 发现系统 curl 在服务端读完请求后断开时仍可能返回零请求大小；改用 `CURLOPT_PREREQFUNCTION` 标记请求阶段，保守禁止此后的重放。第一次 alpha.1 构建未发布，修复继续使用 alpha.2。网页构建后的 DOM 清单也已同步。

## 发布与最终产物

启动器标签 `v2.0.4-alpha.2` 来自主分支 `5e2e92a`，桥标签 `v0.3.13-alpha.2` 来自主分支 `68d5247`。桥构建运行 `44138568366` 的网页、五个平台协议与发布任务全部通过。启动器运行 `44138806996` 的 Windows x64、Linux x64/ARM64、macOS Intel/ARM64 五个平台任务通过，包含归档解压、程序入口和部署后 Qt 依赖检查。Mac ARM 第一次因 GitHub 容量不足取消，补跑通过；Windows 复用原有本地静态 Qt 的 Actions 构建入口，临时 runner 与仓库变量在任务完成后恢复。

最终 Windows CI 单文件 SHA-256：`5576a22bfe650e60e136ff379d2408617697a56129c59d185e322f3822e5793d`。实际该文件的内嵌桥连续三次连接 `node.bugg.icu` 成功，耗时 3.672、5.297、3.578 秒。固定本地入口 `E:/code/bugg/build/bugg.exe` 已同步同一文件；未替换正在运行的 `E:/bugg/bugg.exe`。本地独立构建另通过打包联机 CTest，以及真实原生控制服务、账号别名、好友邀请、游戏载荷哈希、EOF 和关闭恢复的集成用例。

GitHub 发布为 Prerelease，下载站发布为 beta。GitHub 托管发布机通知下载站时连接超时，因此发布任务最终状态包含这一失败，不能称整个工作流全绿。通过已有 SSH 管理入口，将公开 GitHub 原始附件按其摘要校验后传输到发布服务，再复用 `_commit_upload`、审核和发布状态转换入库；未重压原生 ZIP。五个平台的存储文件 SHA-256 全部等于 GitHub 摘要，官网实际显示 alpha.2 且五个下载入口均指向原生 ZIP。托管机到下载站的公网连接问题没有作为本次桥修复的一部分宣称解决。

下载站另修复同基线测试版的排序：仅已登记为 beta 的历史纯数字版本，排在相同数字基线的带后缀修复之前；真正 stable 或未知数字安装不降级。53 项本地发布回归通过，线上隔离的三项排序回归通过；五个平台公开更新接口的 `current=2.0.4&channel=beta` 均返回 `2.0.4-alpha.2`。部署保留回退目录 `/opt/buggcraft-releases/backups/presence-update-sort-20261117T173948Z`。

证据保存在 `E:/code/bugg/build/ci-release-v2.0.4-alpha.2/`：`native-final-jobs.json`、`launcher-final-jobs.json`、`ci-packaged-login.json`、`packaged-multiplayer.log`、`native-control-integration.log`、`numeric-beta-updates.json`、`server-original-hashes.json` 和 `published-download-page.png`。本次没有实体 Mac/Linux 游戏运行、跨两台设备公网游戏或全部模组组合的验收结论。
