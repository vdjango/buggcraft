# Run in an x64 MSVC developer prompt. Dependencies must match /MT, Release.
cmake_minimum_required(VERSION 3.24)
if(NOT CMAKE_HOST_WIN32)
    message(FATAL_ERROR "This verified single-file profile currently supports Windows x64")
endif()
foreach(required QT_ROOT QT_SOURCE_ROOT OPENSSL_ROOT WORK_ROOT OUTPUT_ROOT)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "Pass -D${required}=<absolute path>")
    endif()
endforeach()
if(NOT DEFINED PARALLEL)
    set(PARALLEL 4)
endif()
get_filename_component(single_source "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
get_filename_component(single_native "${single_source}/../minecraft-tunnel-native" ABSOLUTE)
set(single_curl "${WORK_ROOT}/curl")
set(single_curl_prefix "${WORK_ROOT}/curl-static")
set(single_app "${WORK_ROOT}/launcher")
set(single_common -G Ninja -DCMAKE_BUILD_TYPE=Release
    -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded
    "-DOPENSSL_ROOT_DIR=${OPENSSL_ROOT}" -DOPENSSL_USE_STATIC_LIBS=ON
    -DOPENSSL_MSVC_STATIC_RT=ON)
set(single_app_options)
if(DEFINED Qt6LinguistTools_DIR)
    list(APPEND single_app_options "-DQt6LinguistTools_DIR=${Qt6LinguistTools_DIR}")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -S "${single_native}/packaging/bridge-curl"
    -B "${single_curl}" ${single_common} -DBUILD_SHARED_LIBS=OFF -DBUILD_STATIC_LIBS=ON
    "-DCMAKE_INSTALL_PREFIX=${single_curl_prefix}" COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" --build "${single_curl}" --parallel "${PARALLEL}"
    COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" --install "${single_curl}" COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" -S "${single_source}" -B "${single_app}"
    ${single_common} "-DCMAKE_TOOLCHAIN_FILE=${QT_ROOT}/lib/cmake/Qt6/qt.toolchain.cmake"
    "-DCMAKE_PREFIX_PATH=${QT_ROOT}" "-DBUGG_QT_SOURCE_ROOT=${QT_SOURCE_ROOT}"
    "-DCURL_DIR=${single_curl_prefix}/lib/cmake/CURL"
    -DBUILD_TESTING=OFF -DBUGG_SINGLE_FILE=ON -DBUGG_OPTIMIZE_SIZE=ON ${single_app_options}
    COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" --build "${single_app}" --target bugg
    --parallel "${PARALLEL}" COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" --install "${single_app}"
    --component launcher-single-file --prefix "${OUTPUT_ROOT}" COMMAND_ERROR_IS_FATAL ANY)
