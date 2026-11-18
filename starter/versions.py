"""Reviewed dependency and toolchain catalog; generation never resolves versions."""

DEPENDENCIES = {
    "catch2": {"version": "3.8.1", "url": "https://codeload.github.com/catchorg/Catch2/tar.gz/refs/tags/v3.8.1", "sha256": "18b3f70ac80fccc340d8c6ff0f339b2ae64944782f8d2fca2bd705cf47cadb79", "directory": "Catch2-3.8.1", "conan": "catch2/3.8.1", "port": "catch2"},
    "gtest": {"version": "1.16.0", "url": "https://codeload.github.com/google/googletest/tar.gz/refs/tags/v1.16.0", "sha256": "78c676fc63881529bf97bf9d45948d905a66833fbfa5318ea2cd7478cb98f399", "directory": "googletest-1.16.0", "conan": "gtest/1.16.0", "port": "gtest"},
    "eigen": {"version": "3.4.0", "url": "https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz", "sha256": "8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72", "directory": "eigen-3.4.0", "conan": "eigen/3.4.0", "port": "eigen3"},
    "httplib": {"version": "0.20.0", "url": "https://codeload.github.com/yhirose/cpp-httplib/tar.gz/refs/tags/v0.20.0", "sha256": "18064587e0cc6a0d5d56d619f4cbbcaba47aa5d84d86013abbd45d95c6653866", "directory": "cpp-httplib-0.20.0", "conan": "cpp-httplib/0.20.1", "port": "cpp-httplib"},
}
VCPKG_REVISION = "b02e341c927f16d991edbd915d8ea43eac52096c"
TOOLS = {"llvm_major": 21, "gcc_majors": [14, 15], "cmake_min": "3.28", "meson_min": "1.4", "cppcheck_min": "2.17", "gcovr": "8.6", "conan": "2.26.2"}

def selected(a):
    names = [a.test_runner]
    if a.profile == "http":
        names.append("httplib")
    if a.profile == "numerical":
        names.append("eigen")
    return {name: DEPENDENCIES[name] for name in names}
