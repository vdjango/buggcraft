import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    color: "#17151f"
    property var state: onboarding.view
    Connections {
        target: onboarding
        function onChanged() {
            root.state = onboarding.view
            stepPanel.opacity = 0
            stepFade.restart()
        }
    }

    Rectangle { anchors.fill: parent; color: "#17151f" }
    Repeater {
        model: 18
        Rectangle {
            required property int index
            x: 26 + (index % 6) * 148
            y: 28 + Math.floor(index / 6) * 145
            width: 1; height: 470
            color: "#211f2b"
            opacity: 0.48
        }
    }
    Rectangle { x: 0; y: 0; width: 5; height: parent.height; color: "#8b85da" }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 34
        spacing: 32

        ColumnLayout {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            spacing: 18
            RowLayout {
                spacing: 9
                Rectangle { width: 10; height: 10; radius: 5; color: "#8b85da" }
                Text { text: "BUGGCRAFT"; color: "#d6d0e6"; font.pixelSize: 11; font.bold: true }
            }
            Item { Layout.preferredHeight: 20 }
            Repeater {
                model: ["建立你的空间", "选择游玩方式", "调校游戏偏好", "进入联机网络"]
                RowLayout {
                    required property int index
                    required property string modelData
                    spacing: 12
                    Rectangle {
                        width: 25; height: 25; radius: 13
                        color: index === root.state.step ? "#7859ff" : "#211f2b"
                        border.color: index <= root.state.step ? "#8b85da" : "#49415c"
                        Text { anchors.centerIn: parent; text: index < root.state.step ? "✓" : (index + 1); color: index === root.state.step ? "#ffffff" : "#aaaaaa"; font.pixelSize: 11; font.bold: true }
                    }
                    Text { text: modelData; color: index === root.state.step ? "#f2f7f6" : "#78878d"; font.pixelSize: 13 }
                }
            }
            Item { Layout.fillHeight: true }
            Text { text: "FIRST RUN  /  WIZARD"; color: "#756e8b"; font.pixelSize: 9; font.letterSpacing: 1 }
        }

        Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: "#26373c" }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Item {
                    id: stepPanel
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        spacing: 13
                        Text { text: root.state.step === 0 ? "欢迎进入新世界" : root.state.step === 1 ? "先选定你的语言" : root.state.step === 2 ? "你想怎样游玩？" : "下一站，和朋友联机"; color: "#ffffff"; font.pixelSize: 24; font.bold: true }
                        Text {
                            Layout.fillWidth: true
                            text: root.state.step === 0 ? "启动器已经准备就绪。花一分钟完成基础配置，之后每一步都可以在设置中调整。" : root.state.step === 1 ? "选择 Minecraft 游戏内的显示语言，并决定是否自动翻译资源介绍。" : root.state.step === 2 ? "告诉 Buggcraft 你感兴趣的玩法，我们会保存偏好，方便你整理自己的游戏空间。" : "你可以创建自己的房间邀请好友，也可以浏览大厅里正在开放的世界。"
                            color: "#aaaaaa"; font.pixelSize: 12; wrapMode: Text.Wrap; lineHeight: 1.35
                        }

                        Item { Layout.preferredHeight: 5 }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.state.step === 0
                            spacing: 12
                            Rectangle {
                                Layout.fillWidth: true; Layout.preferredHeight: 142; radius: 4
                                color: "#211f2b"; border.color: "#49415c"
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 20; spacing: 18
                                    Item {
                                        width: 94; height: 94
                                        Rectangle { anchors.centerIn: parent; width: 78; height: 78; radius: 39; color: "transparent"; border.color: "#49415c"; border.width: 1 }
                                        Rectangle { anchors.centerIn: parent; width: 58; height: 58; radius: 29; color: "transparent"; border.color: "#8b85da"; border.width: 1
                                            RotationAnimation on rotation { from: 0; to: 360; duration: 12000; loops: Animation.Infinite }
                                        }
                                        Rectangle { anchors.centerIn: parent; width: 8; height: 8; radius: 4; color: "#d8c878" }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 7
                                        Text { text: "YOUR WORLD, YOUR RULES"; color: "#aaa3e8"; font.pixelSize: 10; font.bold: true }
                                        Text { text: "游戏、内容与联机"; color: "#f3f5fb"; font.pixelSize: 16; font.bold: true }
                                        Text { text: "在一个地方管理实例，找到同频玩家。"; color: "#aaaaaa"; font.pixelSize: 11; wrapMode: Text.Wrap }
                                    }
                                }
                            }
                            Text { text: "初始化向导  /  约 1 分钟"; color: "#8d879d"; font.pixelSize: 10 }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true; visible: root.state.step === 1; spacing: 10
                            Repeater {
                                model: [{code:"zh_cn", title:"简体中文", caption:"Simplified Chinese"}, {code:"zh_tw", title:"繁體中文", caption:"Traditional Chinese"}, {code:"en_us", title:"English", caption:"English (US)"}]
                                Rectangle {
                                    required property var modelData
                                    objectName: "onboarding-language-" + modelData.code
                                    Layout.fillWidth: true; Layout.preferredHeight: 48; radius: 4
                                    color: root.state.language === modelData.code ? "#342f49" : "#211f2b"
                                    border.color: root.state.language === modelData.code ? "#8b85da" : "#49415c"
                                    RowLayout {
                                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                                        Text { Layout.fillWidth: true; text: modelData.title; color: "#f3f5fb"; font.pixelSize: 13; font.bold: true }
                                        Text { text: modelData.caption; color: "#aaaaaa"; font.pixelSize: 10 }
                                        Text { text: root.state.language === modelData.code ? "●" : "○"; color: "#aaa3e8"; font.pixelSize: 15 }
                                    }
                                    TapHandler { onTapped: onboarding.setLanguage(modelData.code) }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true; Layout.preferredHeight: 58; radius: 4
                                color: "#211f2b"; border.color: "#49415c"
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 12
                                    ColumnLayout { Layout.fillWidth: true; spacing: 3
                                        Text { text: "自动翻译资源介绍"; color: "#f3f5fb"; font.pixelSize: 12; font.bold: true }
                                        Text { text: "帮助阅读模组、整合包与资源说明"; color: "#aaaaaa"; font.pixelSize: 10 }
                                    }
                                    Switch { objectName: "onboarding-translation"; checked: root.state.translation; onToggled: onboarding.setTranslation(checked) }
                                }
                            }
                        }

                        Flow {
                            Layout.fillWidth: true; visible: root.state.step === 2; spacing: 9
                            Repeater {
                                model: [{id:"survival", title:"生存冒险"}, {id:"creative", title:"创造建造"}, {id:"modded", title:"模组整合"}, {id:"multiplayer", title:"和朋友联机"}]
                                Rectangle {
                                    required property var modelData
                                    objectName: "onboarding-preference-" + modelData.id
                                    width: 154; height: 76; radius: 4
                                    color: root.state.preferences.indexOf(modelData.id) >= 0 ? "#342f49" : "#211f2b"
                                    border.color: root.state.preferences.indexOf(modelData.id) >= 0 ? "#8b85da" : "#49415c"
                                    Column {
                                        anchors.left: parent.left; anchors.leftMargin: 13; anchors.verticalCenter: parent.verticalCenter; spacing: 7
                                        Text { text: root.state.preferences.indexOf(modelData.id) >= 0 ? "◆" : "◇"; color: "#aaa3e8"; font.pixelSize: 15 }
                                        Text { text: modelData.title; color: "#f3f5fb"; font.pixelSize: 12; font.bold: true }
                                    }
                                    TapHandler { onTapped: onboarding.togglePreference(modelData.id) }
                                }
                            }
                            Text { width: parent.width; text: "可多选，也可以暂时跳过。"; color: "#aaaaaa"; font.pixelSize: 10 }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true; visible: root.state.step === 3; spacing: 10
                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                Repeater {
                                    model: [{id:"create", title:"创建房间", detail:"分享自己的世界"}, {id:"discover", title:"发现房间", detail:"浏览大厅与好友邀请"}]
                                    Rectangle {
                                        required property var modelData
                                        objectName: "onboarding-route-" + modelData.id
                                        Layout.fillWidth: true; Layout.preferredHeight: 118; radius: 4
                                        color: root.state.route === modelData.id ? "#342f49" : "#211f2b"
                                        border.color: root.state.route === modelData.id ? "#8b85da" : "#49415c"
                                        ColumnLayout {
                                            anchors.fill: parent; anchors.margins: 14; spacing: 8
                                            Text { text: modelData.id === "create" ? "↗" : "⌕"; color: "#aaa3e8"; font.pixelSize: 18 }
                                            Text { text: modelData.title; color: "#f3f5fb"; font.pixelSize: 13; font.bold: true }
                                            Text { Layout.fillWidth: true; text: modelData.detail; color: "#aaaaaa"; font.pixelSize: 10; wrapMode: Text.Wrap }
                                        }
                                        TapHandler { onTapped: onboarding.setRoute(modelData.id) }
                                    }
                                }
                            }
                            Text { Layout.fillWidth: true; text: root.state.route === "create" ? "创建后，可开启单人世界的局域网并将世界关联到房间。" : "进入大厅后，可查看公开房间、搜索好友或使用邀请代码。"; color: "#aaaaaa"; font.pixelSize: 10; wrapMode: Text.Wrap }
                        }
                    }

                }
                NumberAnimation { id: stepFade; target: stepPanel; property: "opacity"; from: 0; to: 1; duration: 220; easing.type: Easing.OutCubic }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    spacing: 10
                    Text { text: "0" + (root.state.step + 1) + "  /  04"; color: "#8d879d"; font.pixelSize: 10; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Button { objectName: "onboarding-skip"; text: "稍后设置"; flat: true; onClicked: onboarding.skip(); contentItem: Text { text: parent.text; color: "#829398"; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                    Button {
                        objectName: "onboarding-back"
                        visible: root.state.step > 0
                        text: "Back"
                        padding: 14
                        onClicked: onboarding.back()
                        background: Rectangle { radius: 5; color: "#2f2e4b"; border.color: "#625277" }
                        contentItem: Text {
                            text: parent.text
                            color: "#f3f5fb"
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    Button {
                        objectName: root.state.step === 3 ? "onboarding-finish" : "onboarding-next"
                        text: root.state.step === 3 ? (root.state.route === "create" ? "Create a room" : "Discover rooms") : root.state.step === 0 ? "Get started" : "Continue"
                        onClicked: root.state.step === 3 ? onboarding.finish() : onboarding.next()
                        background: Rectangle { radius: 5; color: parent.down ? "#5e44d0" : "#7859ff"; border.color: "#9b85ff"; border.width: 1 }
                        padding: 14
                        contentItem: Text { text: parent.text; color: "#f3f5fb"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
        }
    }
}
