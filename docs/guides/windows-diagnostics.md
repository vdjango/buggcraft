# Windows 故障日志

如果安装器下载完成后窗口消失，先查看安装器所在目录：

- `Buggcraft-install.log`：安装器记录 Windows 版本、系统和进程位数、.NET 版本、CPU 数、内存、下载进度、文件校验、安装过程和异常堆栈。
- `buggcraft.log`：启动器启动过程和运行时错误，保留最近四个 5 MiB 日志文件。
- `buggcraft-crash.log`：Python 原生崩溃堆栈。
- `p2p-sessions/`：按启动次数保留的联机日志，以及按连接编号关联的独立网卡、路由、网关和 DNS 快照；大厅可直接「导出日志」。操作与保留范围见[联机测试指南](network-tester-guide.md)。

从安装器启动时，以上日志保存在 `Buggcraft-Setup.exe` 所在目录。子进程异常退出后还会复制一份到 `error\<退出码>\`，例如退出码 1 对应 `error\1\`；安装器自身失败保存在 `error\installer\`。`buggcraft-stderr.log` 保存应用标准错误，`buggcraft-native.log` 保存子进程输出；即使 Python 还没启动，安装器也会记录进程退出码。直接运行安装后的 `Buggcraft.exe` 时，日志保存在该 exe 所在目录。若安装器目录无法写入，日志会回退到 `%LOCALAPPDATA%\Buggcraft\logs`。

运行包默认下载并解压到安装器旁边的 `Buggcraft-runtime\<版本>\`，下载中的压缩包保存在同一文件夹下的 `<版本>.download`。安装器目录不可写时才回退到 `%LOCALAPPDATA%\Buggcraft\runtime`，并在安装日志记下回退路径。下载中断或解压、文件校验失败时，`.download` 和安装日志会保留；安装成功后下载缓存会删除，日志仍保留。

## 在其他电脑测试

2026-10-22 收到的浅目录启动崩溃：日志出现 main.py 资源查找处 IndexError: 2，原因是安装路径上方不足三层，代码直接索引固定上级目录。已改为只遍历实际存在的父目录；不需要玩家把启动器移动到源码目录。该问题与日志中提到的 Python 版本或下载源无关。

1. 将最新版 `Buggcraft-Setup.exe` 放进一个可以写入的普通文件夹，再运行它。先保留这个文件夹，失败后不要清理缓存或删除日志。
2. 记录失败的大致时间、当时进行到哪一步，以及是否出现过启动器主窗口。若有错误提示，同时保留提示内容。
3. 将安装器旁边的 `error\<退出码>\` 目录或 `Buggcraft-install.log` 和所有 `buggcraft*.log*` 文件一起打包回传。无需发送账号配置、个人接入码或整个运行时目录。故障收集脚本会自动包含这些日志。
4. 如果该目录没有日志，再检查 `%LOCALAPPDATA%\Buggcraft\logs`。两个位置都没有时，请说明“没有生成日志”。

日志可以帮助区分下载、文件损坏、依赖加载、界面初始化和进程崩溃。程序尚未获得运行机会时，可能无法生成应用日志；此时需要结合故障电脑的系统事件继续检查。不能用另一台电脑的拦截记录推断这台电脑的故障原因。

日志会包含本机程序路径；分享前请检查并遮盖个人目录名等不想公开的信息。请发送日志文件本身，便于保留完整堆栈和前后的记录。

## 提示“智能应用控制已阻止”

如果 Windows 提示无法验证 `Buggcraft-Setup.exe` 的发布者，安装器可能尚未开始运行，此次尝试不会生成安装器日志。这类提示应同时保留截图，不能按下载失败或依赖缺失处理。

这种情况下可下载同目录的 `collect-launcher-diagnostics.ps1`，在 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\collect-launcher-diagnostics.ps1 -LauncherPath .\Buggcraft-Setup.exe
```

脚本不启动安装器，会收集安装器日志及 `error` 子目录中的日志、运行包关键文件的目录与大小、文件 SHA-256、签名状态、Windows 10/11 版本、系统硬件信息，以及最近两天的 SmartScreen、代码完整性、Defender 和应用事件，最后生成 `Buggcraft-diagnostics-时间.zip`。不会复制账号配置或整个运行包；只发送这个 ZIP 和截图即可。

当前测试包的安装器和主程序尚未签名。重新下载同一个包不会改变其签名状态。Windows 智能应用控制目前没有单个应用的放行选项；面向启用该功能的电脑发布前，需要完成受信任的代码签名，并验证安装器、主程序和运行组件的实际加载。

安装器不会自动修改 Windows 安全设置。签名前的功能测试可在单独的测试环境进行；不要将要求用户关闭系统防护作为安装流程。

参考：[Microsoft 智能应用控制常见问题](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions) 和 [SmartScreen 声誉说明](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation)。
