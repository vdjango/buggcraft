# 启动器版本发布与自动同步

GitHub Actions 构建完成后，平台直接从 GitHub 拉取产物，缓存到服务器并验证完整性。发布者无需下载、解压或手动上传。后台只需设置是否需要审核。

## 入口与账户

- 版本后台：https://download.bugg.icu/admin/
- 公开下载页：https://download.bugg.icu/
- 使用下载平台独立管理员账户；密码不写入代码仓库，保存在本机私有运维资料中。

## 1. 配置审核方式

打开版本后台，在「GitHub 产物审核」中选择并保存：

| 设置 | 新产物校验完成后的状态 | 后续操作 |
| --- | --- | --- |
| 需要审核（默认） | 待审核 | 检查版本、说明与文件，审核通过后发布 |
| 无需审核 | 已发布 | 自动出现在下载页与更新接口 |

设置只影响此后新入库的版本。切换为无需审核，不会将已有待审核版本自动发布。无论是否审核，文件完整性校验都必须通过。

```mermaid
flowchart TD
  A[推送版本标签] --> B[GitHub Actions 四平台构建与测试]
  B --> C[生成 GitHub Release 草稿]
  C --> D[通知平台自动拉取产物]
  D --> E[服务器缓存与 SHA-256 校验]
  E --> F{是否需要审核}
  F -->|是| G[待审核 → 审核通过 → 发布]
  F -->|否| H[自动发布]
  G --> I[下载页与启动器更新接口]
  H --> I
```

## 2. 发起新版本构建

完成代码审查和测试后，为已推送的提交创建语义化版本标签：

```bash
git switch main
git pull --ff-only
git tag -a v1.2.3 -m "Buggcraft 1.2.3"
git push origin v1.2.3
```

正式版使用 `v1.2.3`，测试版使用 `v1.3.0-rc.1` 等预发布版本。平台根据 GitHub Release 的预发布标记选择正式或测试通道，并校验其与版本号一致。不要复用版本号；修复安装包应提高版本号。

在 GitHub Actions 中查看 **Package launcher**。四个平台全部构建、测试成功后，`release` 任务创建 GitHub Release 草稿，并调用平台同步接口。GitHub 草稿无需公开，官网发布由平台后台控制。

## 3. 平台自动缓存

正常流程全自动：

1. 工作流获取 GitHub Actions 短期身份凭证，通知平台同步对应标签。
2. 平台验证仓库、标签、工作流、签名与有效期，使用该任务临时 GitHub Token 读取草稿产物。
3. 平台并行下载、计算 SHA-256、比对校验文件与版本标记。
4. 文件完整且校验通过后，原子入库，按照当前审核设置进入待审核或直接发布。
5. 工作流等待平台确认完成，再结束任务。临时 Token 不写入磁盘，不需要配置长期 GitHub PAT。

平台还会每 5 分钟检查一次公开 GitHub Release，后台可点「立即检查 GitHub」。公开轮询无法读取私有草稿；若草稿同步失败，在 GitHub Actions 重跑对应 `release` 任务即可。后台展示检查时间、同步状态、失败原因与版本处理结果。

同一版本重复同步会跳过已有记录。已撤回版本不会被自动重新发布。缺少完整文件的历史版本会显示「构建文件尚未齐全」，不会生成不完整版本。

### 产物约定

| 平台 | 安装包 | 校验文件 |
| --- | --- | --- |
| Windows x64 | `Buggcraft.exe` | `SHA256SUMS-windows-x64.txt` |
| Linux x86_64 | `Buggcraft` | `SHA256SUMS-linux-x86_64.txt` |
| macOS Apple Silicon | `Buggcraft-macos-arm64.zip` | `SHA256SUMS-macos-arm64.txt` |
| macOS Intel | `Buggcraft-macos-x86_64.zip` | `SHA256SUMS-macos-x86_64.txt` |
| 版本标记 | `BUGGCRAFT_VERSION.txt` | 内容必须等于不带 `v` 的标签版本 |

版本标记由工作流根据标签生成，用于校验本次产物的发布版本，不代替可执行文件本身的版本检查。校验文件采用 `SHA256  文件名` 格式。

单文件上限 1.5 GB，整组文件上限 3.5 GB；同步前预留至少「本次文件大小 + 5 GiB」磁盘空间。最多同时下载两个文件，以流式方式写盘和计算哈希，不把整包读入内存。未发布文件存放于私有目录，公开下载接口不提供访问。

### 备用手动导入

页面底部折叠项「备用：手动导入构建文件」仅用于同步故障时应急。它支持 8 MiB 分片上传、进度显示与失败重试；日常发布不需要使用。

## 4. 审核、发布与撤回

需要审核时，新同步版本直接进入「待审核」。管理员检查版本号、通道、发行说明和文件清单，点击「审核通过」，再点击「发布版本」。可以退回草稿，或撤回已发布版本。

草稿、待审核、审核通过状态均不出现在公开下载与更新接口中。发布后立即可用，无需等待历史缓存定时任务。正式版版本号必须高于当前已发布正式版。

撤回后，公开列表、更新检查和文件下载均停止提供该版本；服务器保留文件和审计记录。已安装的客户端不会自动降级。恢复撤回版本需要管理员操作，GitHub 自动同步不会代为恢复。

## 5. 接口

### 管理接口

管理接口使用下载平台管理员登录会话；写操作同时校验 CSRF。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/admin/launcher/releases` | 版本记录、审核设置、同步状态、CSRF |
| POST | `/api/admin/launcher/settings` | 设置 `publish_mode`：`manual` 或 `automatic` |
| POST | `/api/admin/launcher/sync` | 立即检查公开 GitHub Release |
| POST | `/api/admin/launcher/releases/{version}/transition` | 提交、审核、发布、撤回等状态操作 |
| POST | `/api/launcher/github-sync` | Actions 专用同步与状态查询，要求指定工作流的 OIDC 身份 |

Actions 同步请求携带 `tag`、`action: sync` 和临时 `github_token`；状态请求携带 `tag`、`action: status`。OIDC 的 audience 必须等于 `https://download.bugg.icu/api/launcher/github-sync`，只接受 `vdjango/buggcraft` 仓库 `.github/workflows/package.yml` 的标签运行。

### 公开接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/launcher/releases` | 已发布版本与撤回版本号 |
| GET | `/api/launcher/update` | 查询指定平台、通道的可用更新 |
| GET | `/api/launcher/assets/{version}/{name}` | 下载已发布的服务器缓存文件 |

更新检查示例：

```text
https://download.bugg.icu/api/launcher/update?current=1.2.2&platform=windows-x64&channel=stable
```

`platform` 支持 `windows-x64`、`linux-x86_64`、`macos-x86_64`、`macos-arm64`；`channel` 支持 `stable`、`beta`。测试通道同时接收更新的正式版。响应有更新时包含文件大小、SHA-256、服务器下载地址和发行说明。客户端必须再次校验文件大小与哈希。

## 6. 运维与历史兼容

版本、设置和审核记录位于下载平台数据目录的 `launcher-releases/releases.json`，同步状态位于 `github-sync.json`，文件位于 `assets/`。这些属于持久化数据，应独立备份，部署时不能覆盖。服务重启会将未完成同步标记为中断；公开版本下轮重试，草稿可重跑 Actions。

下载页保留部署前的历史版本快照 `release-history.json`，并与平台已发布列表合并；平台记录优先，撤回版本会隐藏。旧的 GitHub 历史缓存任务继续维护已有文件，但不会绕过新平台审核，将后续 GitHub 版本直接显示在下载页。

尚未包含自动更新代码的旧启动器，需要用户先从官网下载并安装一次新版。服务器发布新接口不能替旧客户端补上更新代码。
