"""Small examples with useful boundary tests; no template dependencies at generation."""

def files(a):
    ns = a.package
    declaration = "[[nodiscard]] int sign(int value) noexcept;"
    body = """[[nodiscard]] int sign(int value) noexcept {
  if (value < 0) {
    return -1;
  }
  if (value > 0) {
    return 1;
  }
  return 0;
}
"""
    header = f"#pragma once\n\nnamespace {ns} {{\n{declaration}\n}} // namespace {ns}\n"
    source = f'#include "{ns}/core.hpp"\n\nnamespace {ns} {{\n{body}}} // namespace {ns}\n'
    if a.profile == "header-only":
        header = f"#pragma once\n\nnamespace {ns} {{\n{body.replace('int sign', 'inline int sign')}}} // namespace {ns}\n"
    if a.profile == "numerical":
        header += f"\nnamespace {ns} {{\n[[nodiscard]] double squared_norm(double x, double y);\n}} // namespace {ns}\n"
        source += f"\n#include <Eigen/Core>\n\nnamespace {ns} {{\ndouble squared_norm(double x, double y) {{\n  const Eigen::Vector2d point{{x, y}};\n  return point.squaredNorm();\n}}\n}} // namespace {ns}\n"
    result = {f"include/{ns}/core.hpp": header}
    if a.profile != "header-only":
        result["src/core.cpp"] = source
    test = f'#include "{ns}/core.hpp"\n\n#include <limits>\n'
    if a.test_runner == "catch2":
        test += '#include <catch2/catch_test_macros.hpp>\n\nTEST_CASE("sign handles boundaries") {\n'
        assertion = "REQUIRE"
    else:
        test += '#include <gtest/gtest.h>\n\nTEST(Project, SignHandlesBoundaries) {\n'
        assertion = "EXPECT_EQ"
    for value, expected in [("-1", "-1"), ("0", "0"), ("1", "1"), ("std::numeric_limits<int>::min()", "-1"), ("std::numeric_limits<int>::max()", "1")]:
        if a.test_runner == "catch2":
            test += f"  expect_sign({value}, {expected});\n"
        else:
            test += f"  {assertion}(project::sign({value}), {expected});\n"
    if a.profile == "numerical":
        separator = " == " if a.test_runner == "catch2" else ", "
        test += f"  {assertion}(project::squared_norm(3.0, 4.0){separator}25.0);\n  {assertion}(project::squared_norm(0.0, 0.0){separator}0.0);\n"
    test += "}\n"
    marker = "TEST_CASE" if a.test_runner == "catch2" else "TEST("
    test = test.replace(marker, f"namespace project = {ns};\n\n" + marker, 1)
    if a.test_runner == "catch2":
        test = test.replace(marker, "namespace {\nvoid expect_sign(int value, int expected) {\n  REQUIRE(project::sign(value) == expected);\n}\n} // namespace\n\n" + marker, 1)
    result["tests/core_test.cpp"] = test
    result["tests/header_test.cpp"] = f'#include "{ns}/core.hpp"\n'
    if a.profile in {"cli", "numerical"}:
        expression = "project::squared_norm(3.0, 4.0)" if a.profile == "numerical" else "project::sign(-7)"
        result["src/main.cpp"] = f'#include "{ns}/core.hpp"\n\n#include <iostream>\n\nnamespace project = {ns};\n\nint main() {{\n  std::cout << {expression} << \'\\n\';\n  return 0;\n}}\n'
    if a.profile == "http":
        result["src/main.cpp"] = '''#include <httplib.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <thread>

namespace {
volatile std::sig_atomic_t stopped = 0;
void stop(int) {
  stopped = 1;
}
void health(const httplib::Request &, httplib::Response &response) {
  response.set_content("ok", "text/plain");
}
} // namespace

int main() {
  std::signal(SIGTERM, stop);
  std::signal(SIGINT, stop);
  httplib::Server server;
  server.Get("/health", health);
  const char *host = std::getenv("HOST");
  if (host == nullptr) {
    host = "127.0.0.1";
  }
  const int port = server.bind_to_any_port(host);
  if (port < 0) {
    return 1;
  }
  std::cout << port << std::endl;
  std::thread listener([&server] { server.listen_after_bind(); });
  while (stopped == 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds{10});
  }
  server.stop();
  listener.join();
  return 0;
}
'''
    if a.profile == "qt":
        result["src/gui.hpp"] = '''#pragma once

class QApplication;
int run_gui(QApplication &application);
'''
        result["src/gui.cpp"] = '''#include "gui.hpp"

#include <QApplication>
#include <QWidget>

int run_gui(QApplication &application) {
  QWidget window;
  window.setWindowTitle(QStringLiteral("Starter application"));
  window.resize(480, 320);
  window.show();
  return application.exec();
}
'''
        result["src/main.cpp"] = '''#include "gui.hpp"

#include <QApplication>

int main(int argc, char **argv) {
  QApplication application(argc, argv);
  return run_gui(application);
}
'''
        result["tests/gui_smoke.cpp"] = '''#include "gui.hpp"

#include <QApplication>
#include <QTimer>
#include <QWidget>

int main(int argc, char **argv) {
  QApplication application(argc, argv);
  bool verified = false;
  QTimer::singleShot(0, &application, [&verified] {
    const auto windows = QApplication::topLevelWidgets();
    for (QWidget *window : windows) {
      const QString title = QStringLiteral("Starter application");
      const bool matching_title = window->windowTitle() == title;
      verified = matching_title && window->size() == QSize(480, 320);
      window->close();
    }
  });
  const int status = run_gui(application);
  return verified ? status : 1;
}
'''
    result["tests/consumer.cpp"] = f'#include <{ns}/core.hpp>\n\nint main() {{\n  return {ns}::sign(0);\n}}\n'
    return result
