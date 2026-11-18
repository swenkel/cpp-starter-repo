"""Equivalent CMake and Meson targets and dependency integrations."""
import json
from starter.versions import selected, VCPKG_REVISION

def cmake(a):
    ns = a.package
    text = f'''cmake_minimum_required(VERSION 3.28)
project({ns} VERSION 0.1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD {a.cpp_standard})
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
include(CTest)
include(GNUInstallDirs)
include(cmake/Quality.cmake)
include(cmake/Dependencies.cmake)
'''
    if a.profile == "header-only":
        text += f"add_library({ns} INTERFACE)\ntarget_include_directories({ns} INTERFACE $<BUILD_INTERFACE:${{PROJECT_SOURCE_DIR}}/include> $<INSTALL_INTERFACE:include>)\ntarget_compile_features({ns} INTERFACE cxx_std_{a.cpp_standard})\n"
    else:
        kind = a.library_type.upper() if a.profile == "library" else "STATIC"
        text += f"add_library({ns} {kind} src/core.cpp)\ntarget_include_directories({ns} PUBLIC $<BUILD_INTERFACE:${{PROJECT_SOURCE_DIR}}/include> $<INSTALL_INTERFACE:include>)\ntarget_compile_features({ns} PUBLIC cxx_std_{a.cpp_standard})\nstarter_quality({ns})\n"
    text += f"add_library({ns}::{ns} ALIAS {ns})\n"
    if a.profile == "numerical":
        text += f"target_link_libraries({ns} PRIVATE Eigen3::Eigen)\n"
    if a.profile not in {"library", "header-only"}:
        text += f"add_executable(app src/main.cpp)\ntarget_link_libraries(app PRIVATE {ns})\nstarter_quality(app)\n"
        if a.profile == "http":
            text += "target_link_libraries(app PRIVATE httplib::httplib)\n"
        if a.profile == "qt":
            text += "add_library(gui STATIC src/gui.cpp)\ntarget_include_directories(gui PUBLIC src)\ntarget_link_libraries(gui PUBLIC Qt6::Widgets)\nstarter_quality(gui)\ntarget_link_libraries(app PRIVATE gui)\nadd_executable(gui_smoke tests/gui_smoke.cpp)\ntarget_link_libraries(gui_smoke PRIVATE gui)\nstarter_quality(gui_smoke)\n"
    target = "Catch2::Catch2WithMain" if a.test_runner == "catch2" else "GTest::gtest_main"
    text += f'''if(BUILD_TESTING)
  add_executable(unit_tests tests/core_test.cpp tests/header_test.cpp)
  target_link_libraries(unit_tests PRIVATE {ns} {target})
  starter_quality(unit_tests)
  add_test(NAME unit COMMAND unit_tests)
endif()
install(TARGETS {ns} EXPORT {ns}Targets)
install(DIRECTORY include/ DESTINATION include)
install(EXPORT {ns}Targets NAMESPACE {ns}:: DESTINATION ${{CMAKE_INSTALL_LIBDIR}}/cmake/{ns})
include(CMakePackageConfigHelpers)
configure_package_config_file(cmake/Config.cmake.in ${{CMAKE_CURRENT_BINARY_DIR}}/{ns}Config.cmake INSTALL_DESTINATION ${{CMAKE_INSTALL_LIBDIR}}/cmake/{ns})
write_basic_package_version_file(${{CMAKE_CURRENT_BINARY_DIR}}/{ns}ConfigVersion.cmake VERSION ${{PROJECT_VERSION}} COMPATIBILITY SameMajorVersion)
install(FILES ${{CMAKE_CURRENT_BINARY_DIR}}/{ns}Config.cmake ${{CMAKE_CURRENT_BINARY_DIR}}/{ns}ConfigVersion.cmake DESTINATION ${{CMAKE_INSTALL_LIBDIR}}/cmake/{ns})
'''
    return text

def cmake_deps(a):
    lines = ["# Downloads occur only in `project.py setup`; checks use verified local archives."]
    native = a.dependencies == "native"
    if native:
        lines += ["include(FetchContent)", 'set(FETCHCONTENT_UPDATES_DISCONNECTED ON)', 'set(CATCH_BUILD_TESTING OFF CACHE BOOL "" FORCE)', 'set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)', 'set(gtest_build_tests OFF CACHE BOOL "" FORCE)', 'set(EIGEN_BUILD_TESTING OFF CACHE BOOL "" FORCE)', 'set(EIGEN_BUILD_DOC OFF CACHE BOOL "" FORCE)', 'set(HTTPLIB_USE_OPENSSL_IF_AVAILABLE OFF CACHE BOOL "" FORCE)', 'set(HTTPLIB_USE_ZLIB_IF_AVAILABLE OFF CACHE BOOL "" FORCE)', 'set(HTTPLIB_USE_BROTLI_IF_AVAILABLE OFF CACHE BOOL "" FORCE)', 'set(HTTPLIB_USE_ZSTD_IF_AVAILABLE OFF CACHE BOOL "" FORCE)']
        for name, pin in selected(a).items():
            lines.append(f'FetchContent_Declare({name} URL "${{PROJECT_SOURCE_DIR}}/.cache/sources/{name}.tar.gz" URL_HASH SHA256={pin["sha256"]} SYSTEM)')
            if name == "eigen":
                # Eigen 3.4 uses the parent's BUILD_TESTING variable for its own suite.
                lines += ["set(_starter_testing ${BUILD_TESTING})", "set(BUILD_TESTING OFF)",
                          f"FetchContent_MakeAvailable({name})", "set(BUILD_TESTING ${_starter_testing})"]
            else:
                lines.append(f"FetchContent_MakeAvailable({name})")
    else:
        lines.append("find_package(Catch2 3 CONFIG REQUIRED)" if a.test_runner == "catch2" else "find_package(GTest CONFIG REQUIRED)")
        if a.profile == "numerical":
            lines.append("find_package(Eigen3 CONFIG REQUIRED)")
        if a.profile == "http":
            lines.append("find_package(httplib CONFIG REQUIRED)")
    if a.profile == "qt":
        lines.append("find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets)")
    return "\n".join(lines) + "\n"

QUALITY = '''# Applied privately: consumers and downloaded libraries do not inherit gates.
option(STARTER_WERROR "Treat project warnings as errors" ON)
option(STARTER_COVERAGE "Instrument project coverage" OFF)
option(STARTER_SANITIZERS "Instrument address and undefined behavior" OFF)
function(starter_quality target)
  target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow)
  if(STARTER_WERROR)
    target_compile_options(${target} PRIVATE -Werror)
  endif()
  if(STARTER_COVERAGE)
    if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
      target_compile_options(${target} PRIVATE -fprofile-instr-generate -fcoverage-mapping -O0 -g)
      target_link_options(${target} PRIVATE -fprofile-instr-generate)
    else()
      target_compile_options(${target} PRIVATE --coverage -O0 -g)
      target_link_options(${target} PRIVATE --coverage)
    endif()
  endif()
  if(STARTER_SANITIZERS)
    target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer -g)
    target_link_options(${target} PRIVATE -fsanitize=address,undefined)
  endif()
endfunction()
'''

def meson(a):
    ns = a.package
    text = f"project('{ns}', 'cpp', version: '0.1.0', meson_version: '>=1.4', default_options: ['cpp_std=c++{a.cpp_standard}', 'warning_level=0', 'default_library={a.library_type}'])\n"
    text += "inc = include_directories('include')\ncpp = meson.get_compiler('cpp')\nquality_args = ['-Wall', '-Wextra', '-Wpedantic', '-Wconversion', '-Wsign-conversion', '-Wshadow']\nif get_option('gate_werror')\n  quality_args += ['-Werror']\nendif\nquality_link = []\nif get_option('gate_coverage')\n  if cpp.get_id() == 'clang'\n    quality_args += ['-fprofile-instr-generate', '-fcoverage-mapping', '-O0', '-g']\n    quality_link += ['-fprofile-instr-generate']\n  else\n    quality_args += ['--coverage', '-O0', '-g']\n    quality_link += ['--coverage']\n  endif\nendif\nif get_option('gate_sanitizers')\n  quality_args += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g']\n  quality_link += ['-fsanitize=address,undefined']\nendif\n"
    if a.dependencies == "native":
        text += "cmake = import('cmake')\n"
        options = "['-DCATCH_BUILD_TESTING=OFF']" if a.test_runner == "catch2" else "['-Dgtest_build_tests=OFF', '-DINSTALL_GTEST=OFF']"
        target = "Catch2WithMain" if a.test_runner == "catch2" else "gtest_main"
        text += f"test_project = cmake.subproject('{a.test_runner}', cmake_options: {options})\ntest_dep = test_project.dependency('{target}').as_system()\n"
        if a.profile in {"numerical", "http"}:
            dep = "eigen" if a.profile == "numerical" else "httplib"
            text += f"extra_dep = subproject('{dep}').get_variable('project_dep').as_system()\n"
    else:
        name = "catch2-with-main" if a.test_runner == "catch2" else "gtest_main"
        text += f"test_dep = dependency('{name}', method: 'pkg-config', required: true).as_system()\n"
        if a.profile in {"numerical", "http"}:
            name = "eigen3" if a.profile == "numerical" else "cpp-httplib"
            text += f"extra_dep = dependency('{name}', method: 'pkg-config', required: true).as_system()\n"
    if a.profile == "qt":
        text += "qt6 = import('qt6')\nqt_dep = dependency('qt6', modules: ['Widgets'], version: '>=6.8', method: 'pkg-config', include_type: 'system')\n"
        text += "gui = static_library('gui', 'src/gui.cpp', dependencies: qt_dep, cpp_args: quality_args, link_args: quality_link)\ngui_dep = declare_dependency(link_with: gui, dependencies: qt_dep, include_directories: include_directories('src'))\nexecutable('gui_smoke', 'tests/gui_smoke.cpp', dependencies: gui_dep, cpp_args: quality_args, link_args: quality_link)\n"
    if a.profile == "header-only":
        text += "core_dep = declare_dependency(include_directories: inc)\n"
    else:
        extra = ", dependencies: extra_dep" if a.profile == "numerical" else ""
        text += f"core = library('{ns}', 'src/core.cpp', include_directories: inc, cpp_args: quality_args, link_args: quality_link, install: true{extra})\ncore_dep = declare_dependency(link_with: core, include_directories: inc)\n"
    if a.profile not in {"library", "header-only"}:
        extra = ", extra_dep" if a.profile == "http" else ", gui_dep" if a.profile == "qt" else ""
        text += f"app = executable('app', 'src/main.cpp', dependencies: [core_dep{extra}], cpp_args: quality_args, link_args: quality_link)\n"
    text += "unit = executable('unit_tests', ['tests/core_test.cpp', 'tests/header_test.cpp'], dependencies: [core_dep, test_dep], cpp_args: quality_args, link_args: quality_link)\ntest('unit', unit)\n"
    text += f"install_subdir('include/{ns}', install_dir: get_option('includedir'))\npkg = import('pkgconfig')\n"
    lib = "core, " if a.profile != "header-only" else ""
    text += f"pkg.generate({lib}name: '{ns}', filebase: '{ns}', description: 'Generated C++ library', version: meson.project_version(), subdirs: '.')\n"
    return text

def files(a):
    result = {}
    if a.build_system == "cmake":
        result.update({"CMakeLists.txt": cmake(a), "cmake/Quality.cmake": QUALITY,
                       "cmake/Dependencies.cmake": cmake_deps(a), "cmake/Config.cmake.in": f'@PACKAGE_INIT@\ninclude("${{CMAKE_CURRENT_LIST_DIR}}/{a.package}Targets.cmake")\n'})
        result["CMakePresets.json"] = json.dumps({"version": 6, "configurePresets": [{"name": "dev", "generator": "Ninja", "binaryDir": "${sourceDir}/build/manual", "cacheVariables": {"CMAKE_BUILD_TYPE": "Debug", "STARTER_WERROR": a.warnings_as_errors == "yes"}}]}, indent=2) + "\n"
    else:
        result["meson.build"] = meson(a)
        result["meson.options"] = "option('gate_werror', type: 'boolean', value: " + str(a.warnings_as_errors == "yes").lower() + ")\noption('gate_coverage', type: 'boolean', value: false)\noption('gate_sanitizers', type: 'boolean', value: false)\n"
        if a.dependencies == "native":
            for name, pin in selected(a).items():
                patch = f"patch_directory = {name}\n" if name in {"eigen", "httplib"} else ""
                result[f"subprojects/{name}.wrap"] = f"[wrap-file]\ndirectory = {pin['directory']}\nsource_url = {pin['url']}\nsource_filename = {name}.tar.gz\nsource_hash = {pin['sha256']}\n{patch}"
                if patch:
                    thread = "\nthreads = dependency('threads')" if name == "httplib" else ""
                    deps = ", dependencies: threads" if thread else ""
                    result[f"subprojects/packagefiles/{name}/meson.build"] = f"project('{name}', 'cpp'){thread}\nproject_dep = declare_dependency(include_directories: include_directories('.'){deps})\n"
    return result
