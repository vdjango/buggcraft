# 2026-10-28 启动器构建 UI 回归

发布对象是 Buggcraft 启动器。`Package launcher` 会构建并内置 C++ 联机桥，然后测试客户端页面和安装包；单独的 `Package bridge` 成功不能代表启动器发布成功。

本次发布版本固定为 **`v1.0.1-alpha.1`**，不自动递增。发布入口是 GitHub Actions 的 `Release launcher build` 手动工作流，必须填写明确版本号并从 `main` 分支运行。工作流会确认当前 `main` SHA 的最新 `Package launcher` 推送构建通过，逐一核对 Windows x64、Linux x64 / ARM64、macOS Intel / ARM64 五个平台后，才会重打这个版本标签。标签构建自身还有同 SHA 的 `main` 成功门禁；五个平台启动器包和包内运行检查全部成功后，才会生成 GitHub 草稿并同步下载站。版本发布失败时按原工作流重跑失败任务，不递增版本号。

## 已修复

- 游戏启动测试的输出目录改为绝对路径。子进程以实例目录启动时，仍能把启动参数回执写到验收目录。
- 游戏退出时将实际退出码追加到调试日志；异常退出后的“查看日志”可以看到退出原因对应的代码。
- UI 输入等待控件布局及祖先滚动容器停止移动。Linux 的滚轮惯性不再吞掉测试的第一次点击；仍通过 Qt 鼠标事件操作真实控件，不直接调用业务槽或忽略失败。
- 大厅搜索用例等待 300 毫秒防抖请求发出，再提供目录响应。清空搜索后节点恢复可用，随后通过真实按钮进入创建、加入页面。
- CI 保留 pytest 日志、JUnit、截图和逐项操作记录，并将失败断言写入 Actions 注释。
- macOS 路径断言使用规范化后的临时目录，避免将 `/var` 与 `/private/var` 的同一目录误判为不同目录；日志弹窗用例等待实际关闭及计时器停止，覆盖平台关闭动画。
- Windows Java 管理 UI 回归继续使用真实异步扫描与可执行文件版本探测，但将搜索边界限定为已安装 Java 的目录，避免扫描 CI 镜像的整个 Program Files。扫描器本身也会跳过重叠目录与重复 Java 探测；新扫描仍重新验证版本，取消仍可生效。
- 打包预检的各测试模块使用独立 Python 进程，启用 faulthandler，并合并完整日志；单项失败或崩溃仍阻止发布，不跳过原有断言。
- 模态对话框在打开后显式接收键盘焦点；日志回归给嵌入式 QQuickWidget 设置真实点击所对应的鼠标焦点，确认弹窗获得焦点后用 Esc 关闭并确认刷新计时器停止。macOS 无桌面合成器的测试不会因合成鼠标事件未触发系统焦点切换而误判。
- 联机诊断导出用例规范化目标目录，避免 Windows 的 `RUNNER~1` 与 `runneradmin` 两种路径写法导致文件已正确导出却断言失败。

## 本地及 Linux 测试机证据

| 验证 | 结果 |
| --- | --- |
| Linux 原失败的设置、并发下载、语言、内存和加载器 UI 定向回归 | 6 passed，6 subtests passed |
| Windows 设置、加载器及 Qt 输入定向回归 | 5 passed，4 subtests passed |
| 大厅搜索修复后的 Windows 与 Linux 定向回归 | 各 1 passed |
| 发布文件校验、游戏进程管理和日志回归 | 23 passed，16 subtests passed |
| 本轮 Java 管理 UI、Java 选择及扫描去重回归 | 16 passed，16 subtests passed |
| 本轮导航与房间客户端准备回归 | 27 tests，全部通过 |
| 本轮真实 HTTP 并发下载、取消、校验及源回退 | 27 tests，全部通过 |
| 本轮完整独立进程打包预检（Windows） | 52 个模块、483 项，0 失败；日志见 `dist/preflight.log` |
| `cd0e17a` 完整 Windows UI 重跑 | 120 passed，2 deselected，96 subtests passed；结果保存在 `.test-tools/release-alpha1-main-ui` |
| 模态日志焦点、Esc 和内容确认相关定向回归 | 8 passed，40 deselected，17 subtests passed |
| Linux 首轮完整 UI 集合 | 115 passed，4 skipped，2 deselected，96 subtests passed；唯一失败是该轮运行期间修复的大厅搜索用例，后续定向复测通过 |
| Windows 首轮完整 UI 集合 | 119 passed，2 deselected，96 subtests passed；唯一失败同上，修复后单独复测通过；该轮包含引导闭环和退出检查 |

完整平台门禁以最新 `Package launcher` 运行结果为准。上述 Linux 首轮结果不记作全套通过，平台跳过项也不记作执行成功。
