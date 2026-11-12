# Link the existing bridge entry/engine; keep networking in a child process of
# this same executable. The distributable contains no extracted DLL or helper.
set(BUGG_NATIVE_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/../minecraft-tunnel-native" CACHE PATH "Native bridge source tree")
if(NOT EXISTS "${BUGG_NATIVE_SOURCE}/bridge/cli.hpp")
    message(FATAL_ERROR "BUGG_SINGLE_FILE needs the shared native CLI source")
endif()
set(BUGGCRAFT_BRIDGE ON CACHE BOOL "" FORCE)
set(BUGGCRAFT_STANDALONE_BRIDGE ON CACHE BOOL "" FORCE)
# Qt's autogen applies only to our QObject targets, not native dependencies.
set(CMAKE_AUTOMOC OFF)
set(CMAKE_AUTORCC OFF)
set(CMAKE_AUTOUIC OFF)
add_subdirectory("${BUGG_NATIVE_SOURCE}" "native-engine" EXCLUDE_FROM_ALL)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)
target_link_libraries(bugg PRIVATE buggcraft-bridge-cli)
target_compile_definitions(bugg PRIVATE BUGG_SINGLE_FILE)
set_target_properties(bugg PROPERTIES QT_TARGET_VERSION "${PROJECT_VERSION}"
    QT_TARGET_COMPANY_NAME "Buggcraft" QT_TARGET_PRODUCT_NAME "Bugg"
    QT_TARGET_DESCRIPTION "Bugg C++ launcher with native multiplayer")
set(BUGG_QT_SOURCE_ROOT "" CACHE PATH "Exact Qt source root, for single-file license notices")
if(NOT EXISTS "${BUGG_QT_SOURCE_ROOT}/qtbase/LICENSES/LGPL-3.0-only.txt")
    message(FATAL_ERROR "BUGG_SINGLE_FILE needs BUGG_QT_SOURCE_ROOT with the exact Qt sources")
endif()
set(single_file_notices "Bugg single-file launcher\nQt and third-party notices follow.\n")
foreach(module qtbase qtshadertools qtdeclarative qtsvg qtimageformats)
    file(GLOB_RECURSE module_notices CONFIGURE_DEPENDS
        "${BUGG_QT_SOURCE_ROOT}/${module}/LICENSES/*.txt"
        "${BUGG_QT_SOURCE_ROOT}/${module}/src/3rdparty/*LICENSE*"
        "${BUGG_QT_SOURCE_ROOT}/${module}/src/3rdparty/*COPYING*"
        "${BUGG_QT_SOURCE_ROOT}/${module}/src/3rdparty/*NOTICE*"
        "${BUGG_QT_SOURCE_ROOT}/${module}/src/3rdparty/*copyright*")
    list(APPEND single_file_notice_files ${module_notices})
endforeach()
list(APPEND single_file_notice_files "${CMAKE_CURRENT_SOURCE_DIR}/third_party/miniz/LICENSE")
list(APPEND single_file_notice_files
    "${BUGG_DEPENDENCY_CORE_DIR}/NOTICE"
    "${BUGG_DEPENDENCY_CORE_DIR}/LICENSE-APACHE-2.0.txt"
    "${BUGG_DEPENDENCY_CORE_DIR}/third_party/LICENSE-json.txt"
    "${BUGG_DEPENDENCY_CORE_DIR}/third_party/LICENSE-toml.txt")
list(SORT single_file_notice_files)
foreach(notice IN LISTS single_file_notice_files)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${notice}")
    file(READ "${notice}" notice_text)
    file(RELATIVE_PATH notice_name "${BUGG_QT_SOURCE_ROOT}" "${notice}")
    string(APPEND single_file_notices "\n===== ${notice_name} =====\n${notice_text}\n")
endforeach()
set(single_file_notice_path "${CMAKE_CURRENT_BINARY_DIR}/generated/single-file-notices.txt")
file(WRITE "${single_file_notice_path}" "${single_file_notices}")
set_source_files_properties("${single_file_notice_path}" PROPERTIES QT_RESOURCE_ALIAS "licenses.txt")
qt_add_resources(bugg single_file_notices PREFIX "/bugg" FILES "${single_file_notice_path}")
add_custom_command(TARGET bugg POST_BUILD
    COMMAND ${CMAKE_COMMAND} "-DBRIDGE_FILE=$<TARGET_FILE:bugg>"
        -P "${BUGG_NATIVE_SOURCE}/cmake/VerifyStandaloneBridge.cmake"
    VERBATIM)
install(TARGETS bugg RUNTIME DESTINATION . COMPONENT launcher-single-file)
