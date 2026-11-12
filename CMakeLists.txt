cmake_minimum_required(VERSION 3.24)
project(Bugg VERSION 2.0.1 LANGUAGES C CXX)
include(cmake/MsvcDependencies.cmake)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
option(BUGG_SINGLE_FILE "Build the complete Windows launcher and native bridge into one EXE" OFF)
if(BUGG_SINGLE_FILE)
    if(NOT WIN32 OR NOT MSVC)
        message(FATAL_ERROR "The complete single-file profile currently requires Windows/MSVC")
    endif()
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
include(cmake/SizeOptimization.cmake)
find_package(Qt6 6.8 REQUIRED COMPONENTS Quick QuickControls2 Network Concurrent LinguistTools)
if(BUGG_SINGLE_FILE AND (QT6_IS_SHARED_LIBS_BUILD OR NOT QT_FEATURE_static_runtime))
    message(FATAL_ERROR "BUGG_SINGLE_FILE requires Qt built with -static -static-runtime")
endif()
qt_standard_project_setup(REQUIRES 6.8)
if(MSVC)
    add_compile_options(/utf-8)
endif()

set(QT_QML_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/qml")
include(GenerateExportHeader)
qt_add_library(bugg_contracts
    src/contracts/game_catalog.h
    src/contracts/content_catalog.h
    src/contracts/game_runtime.h
    src/contracts/download_sources.h src/contracts/download_sources.cpp)
generate_export_header(bugg_contracts)
target_include_directories(bugg_contracts PUBLIC src "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(bugg_contracts PUBLIC Qt6::Core)
qt_add_library(bugg_http STATIC src/platform/http/http_client.h src/platform/http/http_client.cpp)
target_sources(bugg_http PRIVATE src/platform/diagnostics/diagnostic_log.h
    src/platform/diagnostics/diagnostic_log.cpp)
target_include_directories(bugg_http PUBLIC src)
target_link_libraries(bugg_http PUBLIC Qt6::Network)
target_compile_definitions(bugg_http PRIVATE BUGG_VERSION="${PROJECT_VERSION}")
qt_add_library(bugg_catalog STATIC
    src/modules/catalog/infrastructure/content_description.h
    src/modules/catalog/infrastructure/content_description.cpp
    src/modules/catalog/infrastructure/content_provider.h
    src/modules/catalog/infrastructure/content_provider.cpp
    src/modules/catalog/application/content_catalog_service.h
    src/modules/catalog/application/content_catalog_service.cpp
    src/modules/catalog/infrastructure/catalog_cache.h
    src/modules/catalog/infrastructure/catalog_cache.cpp
    src/modules/catalog/infrastructure/game_catalog_provider.h
    src/modules/catalog/infrastructure/game_catalog_provider.cpp
    src/modules/catalog/application/game_catalog_service.h
    src/modules/catalog/application/game_catalog_service.cpp)
target_link_libraries(bugg_catalog PUBLIC bugg_contracts bugg_http Qt6::Concurrent Qt6::Gui)
add_library(bugg_zip STATIC third_party/miniz/miniz.c third_party/miniz/miniz_tdef.c
    third_party/miniz/miniz_tinfl.c third_party/miniz/miniz_zip.c)
target_include_directories(bugg_zip PUBLIC third_party/miniz)
target_compile_definitions(bugg_zip PUBLIC MINIZ_NO_ZLIB_COMPATIBLE_NAMES)
set(bugg_dependency_default "${CMAKE_CURRENT_SOURCE_DIR}/third_party/dependency_core")
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../bugg-source/native/dependency_core/CMakeLists.txt")
    set(bugg_dependency_default "${CMAKE_CURRENT_SOURCE_DIR}/../bugg-source/native/dependency_core")
endif()
set(BUGG_DEPENDENCY_CORE_DIR "${bugg_dependency_default}"
    CACHE PATH "Source-owned standalone dependency facts/constraint kernel")
add_subdirectory("${BUGG_DEPENDENCY_CORE_DIR}" "dependency-core")
set(BUGG_SHADER_RUNTIME_MANIFEST "${BUGG_DEPENDENCY_CORE_DIR}/../../src/mc_translate/contracts/shader-runtimes.json")
if(NOT EXISTS "${BUGG_SHADER_RUNTIME_MANIFEST}")
    set(BUGG_SHADER_RUNTIME_MANIFEST "${BUGG_DEPENDENCY_CORE_DIR}/shader-runtimes.json")
endif()
set_source_files_properties("${BUGG_SHADER_RUNTIME_MANIFEST}" PROPERTIES QT_RESOURCE_ALIAS "shader-runtimes.json")
qt_add_resources(bugg_catalog bugg_shader_catalog PREFIX "/bugg" FILES "${BUGG_SHADER_RUNTIME_MANIFEST}")
qt_add_library(bugg_runtime STATIC
    src/modules/game_install/infrastructure/dependency_facts.h
    src/modules/game_install/infrastructure/dependency_facts.cpp
    src/modules/game_install/application/dependency_installation.cpp
    src/platform/security/device_key.h src/platform/security/device_key.cpp
    src/modules/multiplayer/infrastructure/native_bridge.h src/modules/multiplayer/infrastructure/native_bridge.cpp
    src/modules/multiplayer/application/multiplayer_service.h src/modules/multiplayer/application/multiplayer_service.cpp
    src/modules/room_sync/application/room_content_cache.h src/modules/room_sync/application/room_content_cache.cpp
    src/modules/game_install/application/modpack_plan.h src/modules/game_install/application/modpack_operations.cpp
    src/modules/game_install/application/runtime_files.cpp
    src/modules/game_install/application/runtime_diagnostics.cpp
    src/modules/game_install/application/content_installation.cpp
    src/platform/files/game_files.h src/platform/files/game_files.cpp
    src/platform/runtime/runtime_environment.h src/platform/runtime/runtime_environment.cpp
    src/platform/runtime/game_process.h src/platform/runtime/game_process.cpp
    src/modules/account/infrastructure/credential_store.h src/modules/account/infrastructure/credential_store.cpp
    src/modules/account/application/microsoft_account.h src/modules/account/application/microsoft_account.cpp
    src/modules/launch/domain/minecraft_metadata.h src/modules/launch/domain/minecraft_metadata.cpp
    src/modules/game_install/infrastructure/resource_client.h src/modules/game_install/infrastructure/resource_client.cpp
    src/modules/game_install/application/game_operations.h src/modules/game_install/application/game_operations.cpp
    src/modules/game_install/application/game_runtime.h src/modules/game_install/application/game_runtime.cpp)
target_sources(bugg_runtime PRIVATE src/modules/settings/application/language_service.h src/modules/settings/application/language_service.cpp)
target_sources(bugg_runtime PRIVATE src/modules/update/application/launcher_update_service.h src/modules/update/application/launcher_update_service.cpp)
target_compile_definitions(bugg_runtime PUBLIC BUGG_VERSION="${PROJECT_VERSION}")
qt_add_resources(bugg_runtime bugg_control_trust PREFIX "/bugg" BASE "${CMAKE_CURRENT_SOURCE_DIR}" FILES assets/control/beijing-test-ca.pem)
file(GLOB BUGG_TRANSLATIONS CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/assets/i18n/ts/*.ts")
set_source_files_properties(${BUGG_TRANSLATIONS} PROPERTIES OUTPUT_LOCATION "${CMAKE_CURRENT_BINARY_DIR}/language-input")
qt_add_lrelease(TS_FILES ${BUGG_TRANSLATIONS} EXCLUDE_FROM_ALL
    LRELEASE_TARGET bugg_language_qm QM_FILES_OUTPUT_VARIABLE BUGG_QM_FILES
    OPTIONS -compress -nounfinished)
set(BUGG_LANGUAGE_MANIFEST "${CMAKE_CURRENT_BINARY_DIR}/generated/i18n/packs.json")
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated/i18n")
string(JOIN "\n" BUGG_LANGUAGE_CATALOGS ${BUGG_TRANSLATIONS})
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/generated/i18n/catalogs.txt" CONTENT "${BUGG_LANGUAGE_CATALOGS}\n")
add_custom_command(OUTPUT "${BUGG_LANGUAGE_MANIFEST}"
    COMMAND ${CMAKE_COMMAND}
        "-DCATALOGS=${CMAKE_CURRENT_BINARY_DIR}/generated/i18n/catalogs.txt"
        "-DINPUT_DIR=${CMAKE_CURRENT_BINARY_DIR}/language-input"
        "-DOUTPUT_DIR=${CMAKE_CURRENT_BINARY_DIR}/language-assets"
        "-DMANIFEST=${BUGG_LANGUAGE_MANIFEST}" "-DVERSION=${PROJECT_VERSION}"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/BuildLanguagePacks.cmake"
    DEPENDS ${BUGG_QM_FILES} "${CMAKE_CURRENT_BINARY_DIR}/generated/i18n/catalogs.txt"
        cmake/BuildLanguagePacks.cmake VERBATIM)
add_custom_target(bugg_language_assets DEPENDS "${BUGG_LANGUAGE_MANIFEST}")
add_dependencies(bugg_language_assets bugg_language_qm)
add_dependencies(bugg_runtime bugg_language_assets)
set_source_files_properties("${BUGG_LANGUAGE_MANIFEST}" PROPERTIES
    GENERATED TRUE QT_RESOURCE_ALIAS assets/i18n/packs.json)
qt_add_resources(bugg_runtime bugg_languages PREFIX "/bugg" BASE "${CMAKE_CURRENT_SOURCE_DIR}"
    FILES assets/i18n/languages.json "${BUGG_LANGUAGE_MANIFEST}")
target_link_libraries(bugg_runtime PUBLIC bugg_contracts bugg_http Qt6::Concurrent Qt6::Gui PRIVATE bugg_zip bugg_dependency_core Qt6::Qml)
if(WIN32)
    target_link_libraries(bugg_runtime PRIVATE crypt32 user32 bcrypt)
else()
    find_package(OpenSSL REQUIRED COMPONENTS Crypto)
    target_link_libraries(bugg_runtime PRIVATE OpenSSL::Crypto)
    if(APPLE)
        target_link_libraries(bugg_runtime PRIVATE "-framework Security")
    endif()
endif()
qt_add_qml_module(bugg_presentation
    URI Bugg.Presentation
    VERSION 1.0
    DEPENDENCIES QtQuick
    OUTPUT_DIRECTORY "${QT_QML_OUTPUT_DIRECTORY}/Bugg/Presentation"
    SOURCES
        src/modules/account/ui/identity_session.h
        src/modules/account/ui/identity_session.cpp
        src/modules/launch/ui/launch_session.h
        src/modules/launch/ui/launch_session.cpp
        src/shell/page_state_store.h
        src/shell/page_state_store.cpp
        src/shell/backdrop_palette.h
        src/shell/backdrop_palette.cpp
        src/modules/game_install/ui/install_catalog_session.h
        src/modules/game_install/ui/install_catalog_session.cpp
        src/modules/catalog/ui/content_catalog_session.h
        src/modules/catalog/ui/content_catalog_session.cpp
        src/modules/catalog/ui/content_list_model.h
        src/modules/catalog/ui/content_list_model.cpp
        src/modules/settings/ui/source_settings.h
        src/modules/settings/ui/source_settings.cpp
)
generate_export_header(bugg_presentation)
target_include_directories(bugg_presentation PUBLIC src "${CMAKE_CURRENT_BINARY_DIR}"
    PRIVATE src/modules/account/ui src/modules/launch/ui src/modules/game_install/ui src/modules/catalog/ui src/modules/settings/ui src/shell)
target_link_libraries(bugg_presentation PUBLIC bugg_contracts PRIVATE Qt6::Qml Qt6::Gui Qt6::Concurrent)
add_subdirectory(qml/Bugg/DesignSystem)
add_subdirectory(qml/Bugg/Pages)
add_subdirectory(qml/Bugg/Shell)
qt_add_executable(bugg WIN32
    src/app/main.cpp
    src/app/application_lifecycle.h src/app/application_lifecycle.cpp
    src/shell/desktop_environment.h
    src/shell/desktop_environment.cpp
)
target_include_directories(bugg PRIVATE src)
set_source_files_properties(qml/Main.qml PROPERTIES QT_RESOURCE_ALIAS Main.qml)
set_source_files_properties(qml/EdgeDock.qml PROPERTIES QT_RESOURCE_ALIAS EdgeDock.qml)
qt_add_qml_module(bugg URI Bugg VERSION 1.0 QML_FILES qml/Main.qml qml/EdgeDock.qml)
target_link_libraries(bugg PRIVATE Qt6::Quick Qt6::QuickControls2 bugg_catalog bugg_runtime bugg_presentation bugg_designsystemplugin bugg_pagesplugin bugg_shellplugin)
if(NOT QT6_IS_SHARED_LIBS_BUILD)
    target_link_libraries(bugg PRIVATE bugg_presentationplugin)
    if(WIN32 AND BUGG_OPTIMIZE_SIZE)
        qt_import_plugins(bugg INCLUDE_BY_TYPE platforms Qt6::QWindowsIntegrationPlugin
            EXCLUDE Qt6::QTgaPlugin Qt6::QWbmpPlugin Qt6::QICNSPlugin)
    endif()
endif()
if(WIN32)
    target_link_libraries(bugg PRIVATE user32)
endif()
if(BUGG_SINGLE_FILE)
    include(cmake/SingleFile.cmake)
endif()

# 原生引擎作为独立可替换的运行依赖；打包不引入旧 Python。
set(BUGG_NATIVE_RUNTIME "${CMAKE_CURRENT_SOURCE_DIR}/../minecraft-tunnel-native/runtime" CACHE PATH "Installed native multiplayer runtime")
if(NOT BUGG_SINGLE_FILE AND EXISTS "${BUGG_NATIVE_RUNTIME}/bin/buggcraft-bridge.exe")
    get_filename_component(BUGG_LINKER_DIR "${CMAKE_LINKER}" DIRECTORY)
    # 引擎单独更新后也刷新依赖，不依赖启动器是否重新链接。
    add_custom_target(bugg_native_runtime
        COMMAND ${CMAKE_COMMAND} "-DSOURCE_BIN=${BUGG_NATIVE_RUNTIME}/bin"
            "-DDESTINATION=$<TARGET_FILE_DIR:bugg>/native/bin" "-DLINKER_DIR=${BUGG_LINKER_DIR}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/StageWindowsBridge.cmake"
        VERBATIM)
    add_dependencies(bugg bugg_native_runtime)
endif()
include(CTest)
if(BUILD_TESTING)
    find_package(Qt6 REQUIRED COMPONENTS Test)
    if(TARGET bugg_native_runtime)
        add_test(NAME native_bridge_runtime COMMAND "$<TARGET_FILE_DIR:bugg>/native/bin/buggcraft-bridge.exe" --version)
        set_tests_properties(native_bridge_runtime PROPERTIES PASS_REGULAR_EXPRESSION "protocol=1")
    endif()
    qt_add_executable(session_test tests/unit/session_test.cpp)
    target_link_libraries(session_test PRIVATE Qt6::Test Qt6::Qml Qt6::Gui bugg_presentation)
    add_test(NAME sessions COMMAND session_test)
    qt_add_executable(catalog_test tests/unit/catalog_test.cpp)
    target_link_libraries(catalog_test PRIVATE Qt6::Test bugg_presentation bugg_catalog)
    add_test(NAME catalogs COMMAND catalog_test)
    qt_add_executable(content_test tests/unit/content_test.cpp
        src/shell/desktop_environment.h src/shell/desktop_environment.cpp)
    target_link_libraries(content_test PRIVATE Qt6::Test Qt6::Quick Qt6::QuickControls2
        bugg_catalog bugg_runtime bugg_presentation bugg_designsystemplugin bugg_pagesplugin bugg_shellplugin)
    if(NOT QT6_IS_SHARED_LIBS_BUILD)
        target_link_libraries(content_test PRIVATE bugg_presentationplugin)
    endif()
    add_test(NAME content COMMAND content_test)
    qt_add_executable(runtime_test tests/unit/runtime_test.cpp
        src/app/application_lifecycle.h src/app/application_lifecycle.cpp)
    target_link_libraries(runtime_test PRIVATE Qt6::Test Qt6::Qml bugg_runtime bugg_presentation bugg_zip bugg_catalog)
    # The fixture-heavy test translation unit does not measure performance.
    # Keep Release production libraries optimized without spending minutes
    # optimizing Qt assertion expansions on each focused regression build.
    target_compile_options(runtime_test PRIVATE "$<$<CXX_COMPILER_ID:MSVC>:/Od>" "$<$<CXX_COMPILER_ID:MSVC>:/GL->" "$<$<CXX_COMPILER_ID:MSVC>:/Zi>")
    target_link_options(runtime_test PRIVATE "$<$<CXX_COMPILER_ID:MSVC>:/DEBUG>")
    add_dependencies(runtime_test bugg)
    if(BUGG_SINGLE_FILE)
        target_compile_definitions(runtime_test PRIVATE BUGG_TEST_SINGLE_FILE_EXE="$<TARGET_FILE:bugg>")
    endif()
    add_test(NAME runtime COMMAND runtime_test)
    qt_add_executable(file_digest_test tests/performance/file_digest_test.cpp)
    target_link_libraries(file_digest_test PRIVATE Qt6::Test bugg_runtime)
    add_test(NAME file_digests COMMAND file_digest_test)
    qt_add_executable(instance_scan_test tests/performance/instance_scan_test.cpp)
    target_link_libraries(instance_scan_test PRIVATE Qt6::Test bugg_runtime)
    add_test(NAME instance_scan COMMAND instance_scan_test)
    qt_add_executable(workload_test tests/performance/workload_test.cpp)
    target_link_libraries(workload_test PRIVATE Qt6::Test bugg_runtime)
    add_test(NAME workloads COMMAND workload_test)
    add_test(NAME qml_component_boundaries COMMAND ${CMAKE_COMMAND}
        -DSOURCE_ROOT=${CMAKE_CURRENT_SOURCE_DIR}
        -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/check_qml_boundaries.cmake)
endif()
