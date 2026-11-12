set_source_files_properties(DesignTokens.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
qt_add_qml_module(bugg_designsystem STATIC
  URI Bugg.DesignSystem
  VERSION 1.0
  QML_FILES
    ContentImage.qml
    LoadingIndicator.qml
    RichDocument.qml
    ActionButton.qml
    AppIcon.qml
    Avatar.qml
    BackdropCarousel.qml
    BrandButton.qml
    CheckOption.qml
    ChoiceCard.qml
    DesignTokens.qml
    Divider.qml
    DockHandle.qml
    EmptyState.qml
    FormField.qml
    FilePicker.qml
    DirectoryPicker.qml
    IconButton.qml
    InputField.qml
    InteractiveSurface.qml
    ListRow.qml
    LogRow.qml
    NodeLogin.qml
    ListViewport.qml
    SwipeListRow.qml
    TaskCard.qml
    MemoryControl.qml
    NavItem.qml
    NavigationBar.qml
    NoticeBanner.qml
    PageHeader.qml
    PageLayout.qml
    Pagination.qml
    ProgressItem.qml
    ProgressSurface.qml
    ProfileButton.qml
    SelectionMenu.qml
    SelectField.qml
    SettingRow.qml
    SubpageHeader.qml
    SummaryButton.qml
    Surface.qml
    TextAreaField.qml
    UiText.qml
    ValueSlider.qml
    WindowControls.qml
    WindowFrame.qml
    WorldMark.qml
  RESOURCES
    assets/home-siege-1.webp
)
target_link_libraries(bugg_designsystem PRIVATE Qt6::Quick Qt6::QuickControls2)
