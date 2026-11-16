import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property string theme
    property var backgrounds: []
    property var preferences: ({})
    signal themeRequested(string theme)
    signal backgroundsEdited(var urls)
    signal folderChosen(string url)
    signal preferenceEdited(string key, var value)
    ThemePicker {
        Layout.fillWidth: true
        theme: root.theme
        onThemeRequested: theme => root.themeRequested(theme)
    }
    SettingRow {
        objectName: "backgroundPickerRow"
        Layout.fillWidth: true
        text: qsTr("启动背景")
        value: root.backgrounds.length ? root.backgrounds.length + qsTr(" 项 · 自动轮播") : qsTr("默认轮播 · 更换媒体")
        onClicked: imagePicker.open()
    }
    ActionButton {
        objectName: "backgroundFolderButton"
        Layout.fillWidth: true
        Layout.maximumWidth: Number.POSITIVE_INFINITY
        text: qsTr("选择背景文件夹（图片或视频）")
        iconName: "folder"
        variant: "outline"
        compact: true
        onClicked: folderPicker.open()
    }
    DirectoryPicker {
        id: folderPicker
        title: qsTr("选择背景文件夹（最多 100 项）")
        onDirectoryChosen: path => root.folderChosen(path)
    }
    SelectField {
        Layout.fillWidth: true
        label: qsTr("背景效果")
        selection: root.preferences.backgroundStyle || "edges"
        options: [
            {
                id: "none",
                name: qsTr("清晰原图")
            },
            {
                id: "top",
                name: qsTr("顶部柔焦 · 突出菜单")
            },
            {
                id: "edges",
                name: qsTr("上下柔焦 · 保留中间景色")
            },
            {
                id: "full",
                name: qsTr("全景柔焦")
            }
        ]
        onChosen: value => root.preferenceEdited("backgroundStyle", value)
    }
    CheckOption {
        objectName: "backgroundOnPagesOption"
        Layout.fillWidth: true
        text: qsTr("将背景应用到所有页面")
        checked: root.preferences.backgroundOnPages === true
        onToggled: root.preferenceEdited("backgroundOnPages", checked)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("其他页面白色蒙版透明度（仅启用跨页面背景时生效）")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    ValueSlider {
        objectName: "pageOverlayOpacitySlider"
        Layout.fillWidth: true
        enabled: root.preferences.backgroundOnPages === true
        from: 0
        to: 0.3
        stepSize: 0.01
        value: root.preferences.pageOverlayOpacity === undefined ? 0.10 : root.preferences.pageOverlayOpacity
        onEdited: value => root.preferenceEdited("pageOverlayOpacity", value)
    }
    SelectField {
        objectName: "pageTextColorField"
        Layout.fillWidth: true
        label: qsTr("其他页面文字颜色（仅启用跨页面背景时生效）")
        enabled: root.preferences.backgroundOnPages === true
        selection: root.preferences.pageTextColor || "light"
        options: [
            {
                id: "light",
                name: qsTr("白色")
            },
            {
                id: "dark",
                name: qsTr("深色")
            }
        ]
        onChosen: value => root.preferenceEdited("pageTextColor", value)
    }
    UiText {
        text: qsTr("模糊程度")
        color: DesignTokens.muted
    }
    ValueSlider {
        Layout.fillWidth: true
        from: 0
        to: 1
        stepSize: 0.05
        value: root.preferences.backgroundBlur === undefined ? 0.35 : root.preferences.backgroundBlur
        onEdited: value => root.preferenceEdited("backgroundBlur", value)
    }
    UiText {
        text: qsTr("暗角强度")
        color: DesignTokens.muted
    }
    ValueSlider {
        Layout.fillWidth: true
        from: 0
        to: 1
        stepSize: 0.05
        value: root.preferences.backgroundVignette === undefined ? 0.35 : root.preferences.backgroundVignette
        onEdited: value => root.preferenceEdited("backgroundVignette", value)
    }
    UiText {
        text: qsTr("图上控件不透明度")
        color: DesignTokens.muted
    }
    ValueSlider {
        Layout.fillWidth: true
        from: 0.05
        to: 0.65
        stepSize: 0.05
        value: root.preferences.surfaceOpacity === undefined ? 0.18 : root.preferences.surfaceOpacity
        onEdited: value => root.preferenceEdited("surfaceOpacity", value)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("背景仅用于页面外观，悬浮面板不播放。默认仅首页显示；其他页面使用 2 倍全屏模糊。视频默认静音，窗口隐藏或游戏运行时暂停。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    ActionButton {
        objectName: "resetBackgroundButton"
        visible: root.backgrounds.length > 0
        text: qsTr("恢复默认背景")
        variant: "ghost"
        compact: true
        onClicked: root.backgroundsEdited([])
    }
    FilePicker {
        id: imagePicker
        objectName: "backgroundFilePicker"
        title: qsTr("选择启动背景（可多选）")
        multiple: true
        nameFilters: [qsTr("图片或视频 (*.png *.jpg *.jpeg *.webp *.mp4 *.m4v *.mov *.webm *.mkv)")]
        onFilesChosen: urls => root.backgroundsEdited(urls)
    }
}
