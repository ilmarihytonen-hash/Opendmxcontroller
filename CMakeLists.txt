cmake_minimum_required(VERSION 3.16)
project(LumenDeskNative LANGUAGES CXX)

add_library(lumendesk_core SHARED native/dmx_core.cpp)
target_compile_features(lumendesk_core PRIVATE cxx_std_17)
set_target_properties(lumendesk_core PROPERTIES CXX_VISIBILITY_PRESET hidden)
target_compile_definitions(lumendesk_core PRIVATE LUMENDESK_BUILD)

if(MSVC)
    target_compile_options(lumendesk_core PRIVATE /W4 /permissive-)
else()
    target_compile_options(lumendesk_core PRIVATE -Wall -Wextra -Wpedantic)
endif()
