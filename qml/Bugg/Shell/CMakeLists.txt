qt_add_qml_module(bugg_shell STATIC
  URI Bugg.Shell
  VERSION 1.0
  QML_FILES FloatingShell.qml ClassicShell.qml WindowController.qml ToolBar.qml
  RESOURCES assets/bugg-tray.png
)

target_link_libraries(bugg_shell PRIVATE Qt6::Quick Qt6::QuickControls2 bugg_designsystemplugin)
