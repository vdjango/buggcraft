# 微软正版登录修复与验证

2026-10-21。本次修复沿用现有 Microsoft 应用 ID，不在客户端保存应用密钥，不读取 Windows 或其他启动器的账号凭据。

## 本次故障原因

实际失败日志中，首次交换授权码返回 `invalid_client`，描述为请求必须包含 `client_secret`；同一时刻又出现一次交换请求，返回授权码失效。原实现每次重试重新连接信号，成功关闭登录窗也发出“取消登录”，本地回调超时还误用了数值字段的 `emit()`。短期游戏令牌过期时原逻辑清除账号，没有使用已保存的刷新令牌。

微软要求密钥说明这次回调被按机密客户端处理；不能据此认定玩家没有购买游戏。桌面启动器应使用公共客户端，不应把应用密钥打包分发。微软对此的说明见 [AADSTS7000218 排查](https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/app-integration/confidential-client-application-authentication-error-aadsts7000218)。这不是微软账号密码错误的证据。

## 当前行为

1. 点击正版登录后，后台向微软 `consumers` 租户取得设备登录码，打开微软返回的 HTTPS 登录页。
2. 登录窗显示登录码和“复制登录码”，用户在微软页面选择拥有 Java 版的账号，完成微软要求的验证。Windows 已登录该账号仍可能要求 Windows Hello、PIN 或其他本人验证。
3. 遵循微软返回的轮询间隔，处理等待授权、减速、拒绝、过期和取消。只有 Xbox Live、XSTS、Minecraft 令牌和有效 Java 版角色档案全部取得后，才向首页报告正版登录成功。
4. 不再要求许可列表同时出现两个固定商品名称；有效的 Minecraft Java 角色档案才是本步骤的结果。无 Java 角色、Xbox 档案未建立、家庭限制和网络失败均明确报错。
5. 自动恢复过期账号时使用刷新令牌；刷新后保存轮换的新令牌。启动前检查令牌，需要刷新时等待刷新完成，再继续本次启动。头像下载失败使用默认头像。
6. 登录重试不会叠加信号；取消旧请求后不接收其结果；成功关闭与取消分开。保留供原生回调配置使用的浏览器 PKCE 实现，校验随机 `state`，授权码只消费一次。

设备登录遵循 [Microsoft 官方设备授权流程](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)。微软不支持 `verification_uri_complete`，因此不伪造自动填码地址。发行方可通过 `BUGGCRAFT_MICROSOFT_CLIENT_ID` 提供自己的已注册公共客户端；相应应用仍须具备 Minecraft 服务访问资格。该配置属于发行方配置，不要求普通玩家填写。

## 本次实际验证

- 微软在线设备码接口真实返回 HTTP 200；未完成账号授权时，令牌接口返回 `authorization_pending`，不再使用出错的 Web 回调交换路径。
- 真实启动器的正版登录按钮打开微软页面，页面识别到本机账号，并进入 Windows Hello PIN 验证。尚未完成该本人验证，因此**没有把真实账号的 Minecraft 角色读取、正版进服或真实令牌刷新记为通过**。
- `tests/test_microsoft_auth.py`：28 项正式 unittest 通过。覆盖设备授权等待/成功/拒绝/减速/取消、跨次请求隔离、刷新令牌轮换与旧版端点兼容、角色校验、头像失败、实际 HTTP 回调及端口复用、错误状态与路径、超时、JWT 更换、过期缓存保留、写入失败保留旧凭据及真实登录窗按钮行为。模拟服务响应的测试不等于上述真实账号验证。
- 同轮启动器完整回归 212 项：208 项通过、4 项因未启用对应实机环境跳过、零失败（455.027 秒），见 [原始日志](../../../multiplayer-tests/launcher-auth-final-suite-20261021.log)。登录窗取消置顶、调整排版后重新打开启动器首页。

```powershell
python -X utf8 -m unittest discover -s buggcraft/tests -p test_microsoft_auth.py -v
```

账号本人的 PIN/验证码只能在微软或 Windows 官方验证界面完成；启动器不会索取、保存或代填。
