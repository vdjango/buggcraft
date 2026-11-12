# Preserve the compiler's actual bytes. CMake's ENCODING AUTO can decode a
# UTF-8 Chinese /showIncludes prefix as the Windows ANSI code page, leaving
# Ninja unable to discover headers and silently reusing incompatible objects.
if(MSVC AND CMAKE_GENERATOR MATCHES "Ninja")
    set(bugg_dep_probe "${CMAKE_BINARY_DIR}/CMakeFiles/BuggDependencies")
    file(MAKE_DIRECTORY "${bugg_dep_probe}")
    file(WRITE "${bugg_dep_probe}/probe.h" "\n")
    file(WRITE "${bugg_dep_probe}/probe.cpp" "#include \"probe.h\"\n")
    execute_process(COMMAND "${CMAKE_CXX_COMPILER}" /nologo /showIncludes /Zs probe.cpp
        WORKING_DIRECTORY "${bugg_dep_probe}"
        OUTPUT_VARIABLE bugg_dep_output ERROR_VARIABLE bugg_dep_error
        RESULT_VARIABLE bugg_dep_result ENCODING NONE)
    string(APPEND bugg_dep_output "\n${bugg_dep_error}")
    if(NOT bugg_dep_result EQUAL 0 OR NOT bugg_dep_output MATCHES
        "(^|\n)([^:\n][^:\n]+:[^:\n]*[^: \n][^: \n]:?[ \t]+)([A-Za-z]:\\\\|\\./|\\.\\\\|/)")
        message(FATAL_ERROR "Cannot identify MSVC header dependency prefix")
    endif()
    set(bugg_dep_prefix "${CMAKE_MATCH_2}")
    if(NOT CMAKE_CL_SHOWINCLUDES_PREFIX STREQUAL bugg_dep_prefix)
        message(WARNING "Correcting MSVC dependency prefix; rebuild existing application objects once")
    endif()
    set(CMAKE_CL_SHOWINCLUDES_PREFIX "${bugg_dep_prefix}")
    set(CMAKE_C_CL_SHOWINCLUDES_PREFIX "${bugg_dep_prefix}")
    set(CMAKE_CXX_CL_SHOWINCLUDES_PREFIX "${bugg_dep_prefix}")
endif()
