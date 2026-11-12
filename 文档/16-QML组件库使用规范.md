# QML 组件库使用规范

SelectField.options 可选 group 为只读分组标题，选项必须按 group 连续排列；标题不进入选择模型、不发 chosen，组内行缩进。搜索同时匹配组名与名称。目录 worker 统一归组/排序：CF 依官方父子类别分组，父类别在组内提供“全部某类”的二级选项（仍对应官方原 ID）；MR 依官方 header 分组。普通无 group 的下拉仍复用原行为。

2026-11-10 广场布局更新：顶部资源页签、靠右的源选择、最右的收起图标；搜索和内容分类一同行，收起后整行隐藏。安装目标在底部左侧，自动版本/加载器/分类/结果摘要在底部右侧，不再提供独立版本或加载器选择。SelectField 新增 compact=false、popupWidth=0，shortName 可缩短触发器文字、弹层仍显示完整名称；compact 使用 30 px 及较小内边距，popupWidth 允许窄触发器配宽弹层，仍统一避让窗口边界。

2026-11-10 TaskCard：task.contentItems 存在时默认展开安装明细，可收起，显示总项数和失败数量；每项复用 ProgressItem 显示名称、版本、文件名、是否依赖、状态与原因，仅 downloading 显示进度条。ListViewport 高度常规最多 250、面板最多 210，内部滚动；TaskCard.viewportLimit 可接列表实际高度，扣除摘要/提示/内边距后分配明细空间。installed 表示本地校验通过、未重复下载。ContentInstallOptions 显示已安装版本，匹配版仍可重新安装；另一版本保留替换入口，确认替换后可安装，不因已安装而禁用全部操作。

SelectField.showSelectedCaption 默认 true；在线目标/版本选择可关闭副标题以避免重复占高。positionPopup() 在弹层打开及尺寸确定后从真实控件映射位置，避免筛选折叠后保留旧坐标。Pagination.countKnown 默认 true，false 时只显示真实游标页序，hasMore 决定能否后翻。ContentImage.ready/loading 仅报告 Qt 图片状态；插图在 ready 时保存 Qt 原生尺寸快照后保持比例，避免布局与 implicitHeight 互相反馈；加载/失败占位 36 px，失败提供原图链接。可选 link 仅消费 worker 校验的 HTTP(S) 地址，悬停提示可点击并打开原链接。TaskCard 对 done 且 missingDependencies 非空的任务显示“待补齐依赖”、具体依赖及原因，并沿用 retryRequested 发出“重试依赖”；不把安装成功等同游戏依赖完整。

2026-11-10 图文控件：LoadingIndicator(text) 表示不确定等待，复用 AppIcon(refresh) 的 900 ms 旋转动画与状态文字，隐藏时停止（避免软件渲染下 BusyIndicator 不显示），不把元数据查询画成下载进度。ContentImage(source,illustration,accessibleName,link) 使用 Qt 异步图片机制；图标解码宽 96，插图最多宽 1024、保持比例，失败显示共用图标。RichDocument(blocks,introduction) 使用 ListViewport 虚拟化 worker 生成的 html/image 块，image.link 存在时预览宽最多 220，避免徽章/视频入口挤掉正文；普通截图使用阅读区域宽度。图文只读，链接仅打开 HTTP(S)，不使用 WebEngine。三者不含内容平台或安装策略。

广场筛选由同排的 IconButton 控制收起搜索/分类行；目标在页脚左侧，版本/加载器/分类/数量在右侧，面板用明确两行。详情常规图文占主体、安装表单在右；面板介绍/安装用 NavigationBar 切换，同一 ContentInstallOptions 复用。搜索、安装等待均不占用大块下载进度空间。

2026-11-10 NodeLogin(status) 输出 loginRequested()/logoutRequested()/settingsRequested()；不再内联服务配置表单。RoomsPage/FriendsPage.loginOrigin 消费非敏感偏好。MultiplayerSettingsPage(loginOrigin,customService) 输出 originEdited/customServiceEdited；LanguagePage.contentTranslation/contentTranslationEdited 接持久偏好。ContentInstallOptions 统一呈现元信息和详情译文切换；ContentDetailsPage 不预留全宽简介/译文条。TasksPage 统计和清空操作移至列表下方，按真实页脚高度分配列表。

## 目标与分层

像使用 Element UI 一样，页面 import 一套组件后声明式组合；不引入 Vue、网页或第二套绘制框架。所有颜色、圆角和交互反馈来自 Bugg.DesignSystem，两种主题只改变布局。

    qml/Main.qml                    # 应用状态与事件装配，不画控件
    qml/Bugg/DesignSystem/           # 通用控件，禁止引用业务页面
    qml/Bugg/Shell/                  # FloatingShell / ClassicShell / WindowController
    qml/Bugg/Pages/                  # ToolDeck + 启动、广场、联机、好友、设置

现有 DesignTokens、UiText、ActionButton、IconButton、NavItem、AppIcon、DockHandle 均继续复用。经 rg 检索，现有 Main.qml 内联了工具栏/窗口容器，SettingsPage 内联了设置行，SearchPage 和 RoomsPage 分别绘制输入框；这些是本次抽取对象。旧启动器仅有旧布局和外观设置，没有可直接复用的双布局壳；不复制旧 QML。

## 通用组件接口

补充接口：`SelectField(options, selection, busy, label, placeholderText)` 输出 `chosen(id)`，共用搜索输入和虚拟列表。`SubpageHeader.homeRequested` 提供直接回首页；`ListRow/InteractiveSurface.hoverFeedbackEnabled` 可关闭鼠标悬停底色，保留键盘焦点。InteractiveSurface 接受 `QtQuick.Templates.Control`，统一识别按钮/下拉框的 down 状态；不再局限 AbstractButton。SelectionMenu 使用 `DesignTokens.floatingSurface` 半透明浮层，文字仍为中性调色板。

| 组件 | 输入 | 输出/插槽 |
| --- | --- | --- |
| Surface | padding、radius、color | contentItem / 默认内容插槽 |
| InteractiveSurface | control（T.Control）、selected、hoverFeedbackEnabled、restingColor、hoverColor、selectedColor、pressedColor | 统一按钮/下拉框悬停、按下、键盘焦点与 120 ms 颜色过渡；颜色可由控件 palette 注入，不承担业务 |
| SelectField | options(id/name/caption)、selection、busy、label、placeholderText | chosen(id)；同一 ComboBox/Popup/InputField/ListView/ListRow，搜索、虚拟化、悬停、选中、键盘提交共用，不在页面手绘版本列表 |
| IconButton | iconName、accessibleName、selected、feedbackEnabled | clicked；窗口收起/关闭使用 feedbackEnabled=false，不画矩形反馈 |
| WindowFrame | radius、color、backdropSource、backdropSources、backdropActive、backdropShade、backdropOpacity、backdropVisible | contentItem / 默认内容插槽；组合 BackdropCarousel，透明度 180 ms 过渡；收起/贴边立即隐藏图片 |
| BackdropCarousel | sources、fallbackSource、radius、shade、active、interval | currentSource 只读；默认 12 秒间隔、420 ms 淡入，双图异步加载；失败有界跳过、隐藏暂停，圆角遮罩只在原生图形后端启用 |
| FilePicker | title、nameFilters、multiple、available | filesChosen(urls)，确认时输出本地 URL；取消不输出，available=false 关闭；不读文件、不写设置 |
| BrandButton | docked | clicked、moveRequested |
| NavigationBar | items、selectedIndex、vertical、itemWidth、itemHeight、underline | selected(index)，共用 NavItem；常规页使用下划线 |
| WindowControls | showCollapse、showDivider | collapseRequested、closeRequested；常规页放右上角，收起不用系统最小化图标 |
| PageHeader | title、caption、titleSize、wrapCaption | 自动高度；默认副标题换行，顶栏使用单行省略 |
| Divider | width/height | 统一分隔线 |
| InputField | text、placeholderText、leadingIcon | TextField 原生 accepted、textEdited；可放尾部按钮 |
| CheckOption | text、checked | CheckBox 原生 toggled |
| ChoiceCard | text、caption、iconName、selected | clicked；选中状态由调用方持有 |
| SettingRow | text、value | clicked |
| SummaryButton | text、caption、expanded、titleSize、titleWeight、centered、feedbackEnabled | clicked；主页游戏摘要 feedbackEnabled=false，悬停不画底色 |
| ProfileButton | text、caption、initials、menuOpen | 主区域 clicked、倒三角 menuRequested；复用 Avatar/IconButton，不在页面覆盖 MouseArea |
| SelectionMenu | items、selectedId、emptyText、actionText、available | chosen(id)、actionRequested；独立中性浅色 palette，共用 Popup/ScrollView/ListRow/Avatar；空列表有管理入口时只显示入口，available=false 自动关闭 |
| ActionButton | text、iconName、variant、compact、cornerRadius | clicked；默认圆角 8，场景主操作可使用胶囊形 |
| NoticeBanner | text | 自动换行和高度 |
| PageLayout | spacing、maximumWidth、minimumHeight、centered | 默认内容插槽；默认最大宽 560、自然高度、顶端排列，按需在可用高度内居中 |
| ListRow | text、caption、value、iconName、selected、leadingComponent、leadingSize、showChevron、showSelectionMark | clicked；默认图标，可通过 leadingComponent 插入 Avatar/WorldMark；布局、选中和反馈仍只有一处实现 |
| FormField | label、text、placeholderText、echoMode、actionIcon | 复用 InputField；textEdited(value) 只转发用户编辑，actionRequested 为尾部动作 |
| TextAreaField | text、placeholderText | 多行反馈输入 |
| ProgressItem | title、state、caption、progress、showBar、titleSize、captionSize、titleWeight | 文件/阶段进度；progress 为 -1 时往返表示未知进度，showBar 可关闭进度条；不执行传输 |
| SubpageHeader | title、caption、titleSize | backRequested；两种布局共用的顶部返回与标题 |

基础组件不获取账号、不搜索、不下载、不读配置文件，只接收属性并发出信号。每个 QML 文件注册到 qmldir 与对应 CMake QML_FILES；业务页面不能访问组件内部 id。

本轮复用审计把 IconButton、NavItem、SettingRow、ChoiceCard、ListRow、ProfileButton、SummaryButton、BrandButton、DockHandle 的通用背景统一到 InteractiveSurface。ActionButton 的主操作/危险色仍由它自己负责，不能把含义不同的按钮强塞进普通列表背景。所有颜色由令牌传入，不在页面写悬停与按下实现。布局管理的子项统一使用 implicitWidth/implicitHeight，避免与 Layout 竞争尺寸。

SettingsPage、SearchPage、RoomsPage、FriendsPage 的公共内容宽度与顶部留白改用既有 PageLayout。好友使用 ListRow.leadingComponent 插入 Avatar，游戏列表插入 WorldMark；未新增“好友专用按钮”或“实例专用卡片”。页面只组合 GridLayout/ColumnLayout 等布局；这些不是通用控件的重复绘制。

ToolDeck.contentMaximumWidth 读取当前 PageLayout 的 maximumWidth，经 Main/FloatingShell 传给 ClassicShell 的同名属性。根页标题同样复用 PageLayout，与好友等宽内容保持同一左边线；壳层不按“好友”等业务标题硬编码宽度。

执行 `cmake -P cmake/check_qml_boundaries.cmake` 或 CTest 的 qml_component_boundaries，阻止 Pages/Main 内联原始按钮、输入、卡片背景及点击处理器，并检查组件两处注册。该检查用于明确的边界违规，不能代替按职责的语义查重与人工审阅。

## 页面用法

```qml
import Bugg.DesignSystem

Surface {
    width: 360
    height: 160
    padding: 16
    Column {
        spacing: 12
        InputField {
            width: 328
            leadingIcon: "compass"
            placeholderText: "搜索模组"
            onAccepted: viewModel.search(text)
        }
        ActionButton {
            text: "创建房间"
            iconName: "plus"
            onClicked: viewModel.createRoom()
        }
    }
}
```

示例中的 viewModel 指未来由 C++ 注入的呈现模型；组件本身不实现这些服务。主题切换使用 SettingsPage → ThemePicker → ChoiceCard 的信号向上提交，由 WindowController 执行，不让选项卡直接操作窗口。

## 两种布局

仅悬浮面板使用 Qt.Tool 隐藏任务栏、保持置顶，由 WindowController 的 Qt 原生托盘入口恢复同一窗口；没有系统托盘时回退为普通 Window，保留恢复入口。常规页面使用 Qt.Window，在任务栏显示且不置顶。两种布局支持上/左/右吸附与折叠。「悬浮面板」宽 410，按内容伸展；常规紧凑/标准/宽屏分别为 800/960/1180，小屏减少高度。ToolBar 只有一份，顶部排列「启动、广场、联机、好友、设置图标」。常规导航以短下划线标记选中项，取消底部菜单与独立底座。ClassicShell 是共用页面标题与滚动容器，不另建窗口。

收起只设置 WindowController.collapsed 临时状态，保留主题；不把主题改成面板，也不做系统最小化。收起时隐藏子页页头、恢复主工具条，重新打开原入口恢复当前子页和原主题。子页标题只有 activeTool>=0 时可见，收起的工具条不会被返回栈占用。

ToolBar.showWindowControls 在面板根页为 true、常规页面为 false。进入二级及更深路由后，FloatingShell 隐藏并禁用 ToolBar，在相同顶栏位置展示 SubpageHeader，使用既有返回栈逐级返回。两种主题复用同一个页头；ClassicShell 只在主入口根页显示内容标题，二级页不重复占用一行。右上角共用 WindowControls，常规页可收起/关闭，面板子页可关闭；收起回到工具条，关闭交给 Main。

切换主题不重启应用、不重新装载当前页面，保留实例选择和输入；面板点击当前主导航收回内容，常规页面保持展开。子页进入以 170 ms 轻移/淡入，主题切换 420 ms；不增加连续回弹。功能页共享中性文字与少量淡紫强调，启动根页使用场景背景与浅色文字，不放悬空菜单阴影。AppIcon 的矢量绘制使用独立图层，保证滚动裁剪时图标不会溢出内容区。

DesignTokens.comfortable 由窗口布局进度统一切换，控件据此调整字号、高度与间距，页面不自行维护第二套主题状态。常规 PageLayout 内容最大宽 560，左右居中、顶部留白 24，纵向间距 22；主按钮按内容宽度呈现，不铺满宽页面。ChoiceCard 共用横向图标、标题说明和选中标记；FormField 尾部动作复用 IconButton。

DesignTokens.scenic 由 Main 的单个绑定根据常规启动根页状态切换，统一提供图上文字、导航、悬停和按钮对比色；不在每个页面复制白字控件。WindowFrame 负责背景，底色与背景图透明度共用 180 ms OutCubic 过渡，避免图片尚未消失时四角先变白；轮播计时器只在 BackdropCarousel 一处，停止于非启动根页、收起或窗口隐藏。默认两张本地背景共约 349 KiB，来源记录位于 DesignSystem/assets；原生图形后端使用 Qt Quick Effects 单一圆角遮罩，自选图共用可读性渐变，图片异步解码。

Shell 负责可用高度，HomePage 组合游戏摘要、账号、启动按钮和原位状态区。面板空闲内容 72 px，整体 410×148：游戏在左、主操作在右，没有独立账号卡片或日志按钮；失败时按需展开，保留返回选择。HomePage.launchStatus 接收呈现模型快照，发送原有 launchRequested/cancelRequested/stopRequested，不用 QML Timer 假定启动完成。ListRow/ActionButton 的文字与普通反馈遵从 Qt palette，由 Main 注入当前主题、SelectionMenu 局部覆盖固定中性色，禁止再给角色菜单复制一套按钮或列表行。

## 后续修改规则

列表反馈统一由 ListRow → InteractiveSurface 维护：ListRow.animateFeedback 默认 false，悬停直接切换一种颜色，不渐变；其他控件可通过 InteractiveSurface.animateFeedback 保留短过渡。SelectField 使用同一背景并关闭渐变，已有 options 时不会因 busy 刷新而禁用/替换显示文字。后台状态变化不得重置下拉滚动或搜索。

ToolBar.tasksRequested 由 FloatingShell 转发，Main 仅展开已有窗口并 openPage("tasks")；任务不是新的主菜单索引。入口使用 IconButton，放设置左边；面板导航项宽 52，窗口仍 410。GameInstallPage.editingName 仅为当前页表单的展开状态，真实名称仍归 InstallCatalogSession，收起不丢编辑。

先搜索此目录的同职责组件，能复用就传属性/信号；新视觉规则先落到设计令牌或组件。页面禁止复制通用按钮、输入、设置行、导航或卡片的背景/焦点实现。专用组件如 ThemePicker 属于 Pages，不放进通用组件库。窗口几何规则只在 Shell，真实业务只在 C++ 呈现模型与模块服务。

主题选择通过 Main 转交 GameRuntime.set_preference，沿用便携缓存根目录内的串行原子保存；不得通过 QtCore.Settings 的默认路径写入用户目录。


## 真实任务进度与目录选择（2026-11-08）

`ProgressSurface` 是唯一进度表面；`ProgressItem` 和 `Shell.ToolBar` 都组合它，不各写进度条。active:bool 开关效果，progress:real 为 0–1 或 -1（未知），fluid:bool 开启水面/波纹，cornerRadius:real 控制裁切，fillColor/trackColor 取令牌。内部 phase 只驱动绘制，不推进业务；active=false 或不可见即停止循环动画。未知进度使用往返表示等待，不能伪造已下载字节。

`ToolBar.activity` 接收 C++ 快照 `{active, progress, label}`；整个菜单作为进度表面，任务图标仍复用 IconButton。`NavigationBar.toolIds` 与 items 对齐，selected(index) 返回稳定工具 ID。面板 items 仅启动/联机/好友，对应 [0,2,3]；常规主题保留广场，对应 [0,1,2,3]。页面不能按可见列表的位置重写菜单 ID。

`DirectoryPicker` 继承 Qt Quick Dialogs.FolderDialog，调用 open()，确认发 directoryChosen(path:string)，取消不发编辑事件。StoragePage 只发目录选择意图，GameRuntime 决定是否保存和扫描；选择目录不冒充移动文件。

实例管理页只管理当前实例，不放启动按钮；全局与实例游戏设置共用 InstanceSettingsPage/MemoryControl/ValueSlider；自动为默认，显示本次建议值，实际启动前由 C++ 重算；逐项即时保存，不放保存按钮。下载列表只消费真实 tasks，空列表显示空状态。

## 即时设置组件

`ValueSlider` 继承 Qt Slider，统一轨道、滑块、禁用和焦点，from/to/stepSize/value 使用标准属性；edited(real) 只发用户移动意图，轨道左右与控件边界对齐。`MemoryControl` 组合既有 InputField/CheckOption 和 ValueSlider，输入 automatic/memoryMB/automaticMemoryMB/totalMB/availableMB/maximumMB，只发 automaticEdited(bool)/memoryEdited(int)。自动模式显示建议值并隐藏手动编辑；手动模式只有一个分配滑块和数值输入，不绘制第二个用量条。组件不扫描系统、不持有业务配置、不保存文件。

`SelectField.searchPlaceholder` 可改语言搜索等提示，仍使用同一虚拟列表和悬停反馈。普通页面只组合上述控件，不能为语言/分辨率/并发复制 ComboBox。所有可见固定文案使用 qsTr，名称/路径不翻译；缺少译文遵从 LanguageService 的英语回退。

下拉细节修订（2026-11-09）：SelectField 的弹层挂在窗口 Overlay，按可用高度选择向上或向下展开；选项含说明时增加行高，8 项以内隐藏搜索。控件及弹层统一使用 controlBorder，不依赖背景色差表示边界。InputField 和 CheckOption 的可操作文字使用主文字颜色。固定列表页面由 ClassicShell/FloatingShell.fixedViewport 禁止外围滚动，内部 ListViewport 保留滚动，页脚不随列表移动。

FilePicker.saveMode 使用系统 SaveFile；suggestedName 在显示前绑定 selectedFile，不能在 visibleChanged 才赋值。已在 Windows 原生保存窗口验证建议名称、用户改名和不存在的新文件目标，取消不发 filesChosen。SubpageHeader 统一返回按钮、单行/双行标题的垂直中心，窗口控制按钮不随页面重排。SummaryButton.frosted/iconName 由首页传入，半透明底板与加载器符号仍复用公共组件，不增加页面私有卡片。

## 房间相关组件复用（2026-11-09）

RoomLobbyPage 仅组合 PageLayout、ListViewport/ListRow、Avatar、ActionButton、IconButton、Divider、ProgressItem 和既有输入/选择器，没有专设房间操作卡片。ListRow.trailingComponent 用于行尾操作，EmptyState 接收标题/说明/图标供大厅、成员、好友复用。AppIcon.copy 为统一复制图标路径，不在页面画图标。

SummaryButton.frosted/backdropTint 使用已有 InteractiveSurface 绘制平均背景色从左向右透明的渐变；feedbackEnabled=false 时不产生悬停白块。背景取色来自 BackdropCarousel.averageColor，仅传值，不在每页解码图片。

渐变唯一实现在 InteractiveSurface.faded/backdropTint；SummaryButton.frosted 和 ListRow.faded 都转交它。软件渲染时必须保留非透明基色，否则 Rectangle 可能跳过整个渐变；验收要比较实际像素的左侧遮罩和右侧淡出，不能只断言 Gradient 对象存在。

SubpageHeader.homeAsBack/worldIcon/actionIcon/actionName 组合既有 Home、WorldMark、页头和图标按钮；actionRequested 只发导航意图。ToolBar.friendsVisible 隐藏未登录好友，NavigationBar 仍使用稳定 toolIds。RoomChat 是 Pages 内的业务组合，不另画通用输入或列表；房间、好友继续复用 ListViewport/ListRow，不能为每页实现一套行反馈。

SelectionMenu 的 items.initials 为可选字段：身份项提供 initials 时使用 60 px 头像行，房间管理和好友操作省略 initials 时使用 44 px 普通操作行，不显示问号头像。所有调用方共用中性半透明 Surface、controlBorder 边框、8 px 窗口安全边距及 ListRow 的即时高亮；不能为房间菜单另写一套 Popup。头像属于身份信息，不能拿占位头像装饰普通命令。

好友布局补充（2026-11-10）：FriendsPage 的常规窗口使用 232 px 联系人栏，搜索在面板与常规均保留。常驻“联机通知”和“好友申请”两项与联系人按最近收到时间排序，相同时间保留来源顺序。常规点击服务项在右侧显示对应通知，点击联系人展示占满右栏的会话头、操作、消息区域和输入区；私聊明确显示“待实现”，输入/发送禁用。面板分别进入 notifications/friendConversation 子页，邀请选择仍复用单列。notificationMode/detailMode/notificationCategory 为呈现输入；selectedId/edited("selected",id) 归 PageStateStore；未读及时间归 MultiplayerService，不伪造聊天服务。自己的公开短码标为“我的好友码”，不重复展示用户名。

FriendActions 是 Pages 内业务组合，输入 service/status/person/mode/inviteMode，输出 noticeRequested(message)，复用 ActionButton/IconButton/SelectionMenu，列表与详情共用邀请/加入/申请/复制/删除命令，不建立私聊服务。RoomChat 在输入行下统一保留 16 px，页面边距继续由 PageLayout 提供。

Avatar.badgeCount 默认为 0，正数在既有状态位置显示未读数，超过 99 显示 99+；不另画页面角标。NavigationBar.iconNames 按位置提供可选图标，NavItem.iconName 保留原有 text 作为可访问名称；面板房间页采用图标页签和复制/邀请图标，常规窗口保留文字。ActionButton 无 text 时不为文字保留间距，仍须提供 Accessible.name。

Pagination 是共用呈现组件：输入 itemCount/pageSize/pageIndex，输出 chosen(index)，只夹紧派生 currentPage，不修改调用方草稿；默认每页 3 项，页数为 1 时由调用方隐藏。RoomsPage 的页码仍归 PageStateStore，列表继续使用 ListViewport/ListRow。

InteractiveSurface.faded 的左端使用背景平均色 backdropTint，经整个表面 fadeOpacity 控制，末端透明；不再额外压暗平均色。SummaryButton.fadeOpacity 默认 20%（按最新要求由 15% 增加 5 个百分点），ListRow 默认 10%；切页及软件/原生后端共用同一实现。窗口正文拖动只在 FloatingShell 的一个 DragHandler 装配，控件自身的输入、滑块及滚动交互保留；ListViewport 仅内容溢出时启用滚动。

底栏布局：FriendsPage 的常规左栏随同一行填满可用高度，ListViewport 分配剩余空间，好友码停在左栏底部；面板仍按有限列表自然高度显示，不扩成空白大面板。RoomsPage 的 ready 内容在一个 ColumnLayout 内按可用高度分配，常规列表伸缩，节点状态始终在其底部；面板沿用最多三项和分页的自然高度，不用固定减数猜测页脚位置。搜索、滚动和底栏不属于同一可滚动内容。

DesignTokens.sizeClass 由 Main 绑定 WindowController.theme；controlHeight（34/38/42/46）、iconButtonSize、rowHeight、detailedRowHeight、controlTextSize 是四种尺寸唯一密度输入。InputField/SelectField/ActionButton/IconButton/CheckOption/ListRow 复用这些令牌，页面不复制一套面板控件。ListRow 文本按控件 mirrored（界面方向）统一对齐，不按每项首字符切换左右；文字自身仍遵守双向排版。语言页面板预留选择器弹出空间，不能用缩小窗口把菜单压到标题上。

ListRow.showTrailing 默认 true；false 时不创建尾部命令插槽，不以创建后隐藏来占据行宽。空 value 不参与布局，避免两次空白间隔；好友窄栏和语言等共享行都使用同一实现。

RoomChat 的每条消息正文以 StaticText 无障碍节点公开 text，description 为发言者；属性附在实际 Text 上，不能给没有 text 属性的布局标注 StaticText。复用同一模型，不建立辅助消息副本，便于屏幕阅读器与原生界面验收确认实际消息内容。

2026-11-10 更新页：UpdatePage(service) 只消费 LauncherUpdateService.status，复用 Avatar、PageHeader、Divider、LoadingIndicator、ProgressItem、ActionButton 与 SettingRow；状态为检查、最新、可用、下载、待重启、错误。SettingsPage.updateStatus 显示同一服务的新版本/重启状态；Main 监听 update_available，只发原 notice。未接入时不能伪造版本或成功。NodeLogin 错误文字沿用 NoticeBanner 的 horizontalAlignment 参数居中，不新增错误组件。

SettingRow.compact 默认 false，紧凑目录页可使用 DesignTokens.controlHeight；文字/值/图标及反馈仍归原 SettingRow。SettingsPage 开启 compact 并减小上下 padding，使新增联机设置后常规窗口末项仍完整可见，不压缩所有设置子页。

2026-11-12：`LogRow` 是日志虚拟列表的呈现组件，继承 AbstractButton，组合 InteractiveSurface/UiText，按时间、级别、Tag、首行消息布局；完整事件保留在 LogsPage 选中详情，不逐行创建卡片或展开堆栈。`TextAreaField.flat` 只控制已有输入表面的透明/无圆角呈现，选择复制、焦点和滚动仍复用原 TextArea，不在日志页重写输入组件。页面不解析日志或持有文件句柄。
