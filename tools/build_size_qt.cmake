# Run from an MSVC developer prompt on Windows. This creates a separate Qt kit.
cmake_minimum_required(VERSION 3.24)
if(NOT DEFINED WORK_ROOT)
    get_filename_component(WORK_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.build-envs/qt-size-6.8.1" ABSOLUTE)
endif()
if(NOT DEFINED PARALLEL)
    set(PARALLEL 6)
endif()
if(NOT DEFINED STATIC_RUNTIME)
    set(STATIC_RUNTIME OFF)
endif()
set(size_qt_runtime_options)
if(STATIC_RUNTIME)
    list(APPEND size_qt_runtime_options -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded)
endif()
if(NOT CMAKE_HOST_WIN32)
    message(FATAL_ERROR "This measured profile is for Windows x64; other platform feature sets require their own validation")
endif()
find_program(SIZE_QT_NINJA ninja REQUIRED)
set(size_qt_prefix "${WORK_ROOT}/static")
set(size_qt_modules qtbase qtshadertools qtdeclarative qtsvg qtimageformats)
set(size_qt_hashes
    40b14562ef3bd779bc0e0418ea2ae08fa28235f8ea6e8c0cb3bce1d6ad58dcaf
    55b70cd632473a8043c74ba89310f7ba9c5041d253bc60e7ae1fa789169c4846
    95d15d5c1b6adcedb1df6485219ad13b8dc1bb5168b5151f2f1f7246a4c039fc
    3d0de73596e36b2daa7c48d77c4426bb091752856912fba720215f756c560dd0
    138cc2909aa98f5ff7283e36eb3936eb5e625d3ca3b4febae2ca21d8903dd237)
set(size_qt_qtbase_options
    -DBUILD_SHARED_LIBS=OFF -DFEATURE_optimize_size=ON
    "-DFEATURE_static_runtime=${STATIC_RUNTIME}"
    -DFEATURE_widgets=OFF -DFEATURE_printsupport=OFF -DFEATURE_sql=OFF
    -DFEATURE_dbus=OFF -DINPUT_opengl=no -DFEATURE_opengl=OFF -DFEATURE_vulkan=OFF
    -DFEATURE_openssl=OFF -DFEATURE_schannel=ON)
set(size_qt_qtdeclarative_options
    -DFEATURE_qml_debug=OFF -DFEATURE_qml_profiler=OFF
    -DFEATURE_quick_designer=OFF -DFEATURE_quick_particles=OFF
    -DFEATURE_quickcontrols2_fusion=OFF -DFEATURE_quickcontrols2_imagine=OFF
    -DFEATURE_quickcontrols2_material=OFF -DFEATURE_quickcontrols2_universal=OFF
    -DFEATURE_quickcontrols2_windows=OFF -DFEATURE_quickcontrols2_macos=OFF
    -DFEATURE_quickcontrols2_ios=OFF -DFEATURE_quickcontrols2_fluentwinui3=OFF)
set(size_qt_qtimageformats_options
    -DFEATURE_tiff=OFF -DFEATURE_mng=OFF -DFEATURE_jasper=OFF)
file(MAKE_DIRECTORY "${WORK_ROOT}/archives" "${WORK_ROOT}/src")
list(LENGTH size_qt_modules size_qt_count)
math(EXPR size_qt_last "${size_qt_count} - 1")
foreach(size_qt_index RANGE ${size_qt_last})
    list(GET size_qt_modules ${size_qt_index} size_qt_module)
    list(GET size_qt_hashes ${size_qt_index} size_qt_hash)
    set(size_qt_archive "${size_qt_module}-everywhere-src-6.8.1.tar.xz")
    set(size_qt_archive_path "${WORK_ROOT}/archives/${size_qt_archive}")
    if(NOT EXISTS "${size_qt_archive_path}")
        file(DOWNLOAD "https://download.qt.io/archive/qt/6.8/6.8.1/submodules/${size_qt_archive}"
            "${size_qt_archive_path}" EXPECTED_HASH "SHA256=${size_qt_hash}" TLS_VERIFY ON SHOW_PROGRESS)
    endif()
    file(SHA256 "${size_qt_archive_path}" size_qt_actual)
    if(NOT size_qt_actual STREQUAL size_qt_hash)
        message(FATAL_ERROR "SHA256 mismatch for ${size_qt_archive}")
    endif()
    set(size_qt_source "${WORK_ROOT}/src/${size_qt_module}")
    if(NOT EXISTS "${size_qt_source}/CMakeLists.txt")
        file(ARCHIVE_EXTRACT INPUT "${size_qt_archive_path}" DESTINATION "${WORK_ROOT}/src")
        file(RENAME "${WORK_ROOT}/src/${size_qt_module}-everywhere-src-6.8.1" "${size_qt_source}")
    endif()
    set(size_qt_build "${WORK_ROOT}/build-static/${size_qt_module}")
    set(size_qt_options ${size_qt_${size_qt_module}_options})
    if(NOT size_qt_module STREQUAL "qtbase")
        list(APPEND size_qt_options "-DCMAKE_TOOLCHAIN_FILE=${size_qt_prefix}/lib/cmake/Qt6/qt.toolchain.cmake")
    endif()
    execute_process(COMMAND "${CMAKE_COMMAND}" -S "${size_qt_source}" -B "${size_qt_build}" -G Ninja
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE=ON
        "-DCMAKE_INSTALL_PREFIX=${size_qt_prefix}" "-DCMAKE_PREFIX_PATH=${size_qt_prefix}"
        "-DCMAKE_MAKE_PROGRAM=${SIZE_QT_NINJA}" -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF
        -DQT_BUILD_BENCHMARKS=OFF ${size_qt_options} ${size_qt_runtime_options} COMMAND_ERROR_IS_FATAL ANY)
    execute_process(COMMAND "${CMAKE_COMMAND}" --build "${size_qt_build}" --parallel "${PARALLEL}"
        COMMAND_ERROR_IS_FATAL ANY)
    execute_process(COMMAND "${CMAKE_COMMAND}" --install "${size_qt_build}" COMMAND_ERROR_IS_FATAL ANY)
endforeach()
message(STATUS "Isolated size-focused Qt installed at ${size_qt_prefix}")
