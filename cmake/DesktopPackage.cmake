# Keep the normal development and Windows single-EXE profiles unchanged.
if(WIN32 OR BUGG_SINGLE_FILE)
    message(FATAL_ERROR "BUGG_DESKTOP_PACKAGE is the macOS/Linux deployment profile")
endif()
if(APPLE)
    set_target_properties(bugg PROPERTIES MACOSX_BUNDLE TRUE
        MACOSX_BUNDLE_BUNDLE_NAME Bugg
        MACOSX_BUNDLE_GUI_IDENTIFIER icu.bugg.launcher
        MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"
        MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}")
else()
    # The portable updater and UI use the program directory as their root.
    set(CMAKE_INSTALL_BINDIR ".")
    set_target_properties(bugg PROPERTIES INSTALL_RPATH "$ORIGIN/lib")
endif()
install(TARGETS bugg BUNDLE DESTINATION . RUNTIME DESTINATION .)
qt_generate_deploy_qml_app_script(TARGET bugg OUTPUT_SCRIPT bugg_desktop_deploy
    NO_TRANSLATIONS)
install(SCRIPT "${bugg_desktop_deploy}")
