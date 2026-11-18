"""Fail-closed checks shared by developer, hook, and CI entrypoints."""
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from . import common as c, deps, build

SEAL = "scripts/gates.sha256"
PATTERNS = ("gates.toml", "dependencies.json", ".clang*", "AGENTS.md", "CLAUDE.md", "GEMINI.md",
            "scripts/*.py", "scripts/*.sh", "scripts/lib/*.py", ".githooks/*", ".github/workflows/*",
            ".claude/settings.json", "CMakeLists.txt", "CMakePresets.json", "cmake/*", "meson.build", "meson.options",
            "subprojects/*.wrap", "subprojects/packagefiles/*/meson.build", "Dockerfile", "compose.yaml")
PATTERNS += tuple(f"{directory}/**/{name}" for directory in ("src", "include", "tests", "cmake")
                  for name in ("CMakeLists.txt", "*.cmake", "meson.build", "meson.options"))

def seal_text(root=None):
    root = root or c.ROOT
    files = sorted({p for pattern in PATTERNS for p in root.glob(pattern) if p.is_file()})
    return "".join(f"{c.digest(p)}  {p.relative_to(root).as_posix()}\n" for p in files)

def seal():
    (c.ROOT / SEAL).write_text(seal_text())

def integrity(cfg):
    path = c.ROOT / SEAL
    if cfg["guard"] == "seal" or path.exists():
        if not path.exists() or path.read_text() != seal_text():
            raise c.Failure("gate seal differs; a human must review changes and run scripts/project.py seal")

def toolchain(cfg, optional=True):
    tools = c.catalog()["tools"]
    c.executable("ninja")
    c.version_at_least("cmake", tools["cmake_min"])
    if cfg["build_system"] == "meson":
        c.version_at_least("meson", tools["meson_min"])
    for variant in c.variants(cfg):
        family, cc, cxx = c.compiler(cfg, variant)
        version = c.version_at_least(cxx, "1")[0]
        expected = [tools["llvm_major"]] if family == "clang" else tools["gcc_majors"]
        if version not in expected:
            raise c.Failure(f"{family} major must be one of {expected}, found {version}")
    if not optional:
        return
    for key, binary in (("clang_tidy", "clang-tidy"), ("clang_format", "clang-format")):
        if cfg[key] == "yes" and c.version_at_least(c.llvm(binary), "1")[0] != tools["llvm_major"]:
            raise c.Failure(f"{binary} must match LLVM {tools['llvm_major']}")
    if cfg["cppcheck"] == "yes":
        c.version_at_least("cppcheck", tools["cppcheck_min"])
    if cfg["coverage"] != "0":
        c.version_at_least("gcovr", tools["gcovr"])
    if cfg["dependencies"] == "conan":
        if c.version_at_least("conan", tools["conan"])[0] != 2:
            raise c.Failure("Conan 2 is required")

def comments(text):
    """Yield C++ comments with line numbers; skip escaped and raw literals."""
    i, line = 0, 1
    while i < len(text):
        start, origin = i, line
        raw = re.match(r'(?:u8|u|U|L)?R"([^ ()\\\t\r\n]{0,16})\(', text[i:])
        if raw:
            end = text.find(")" + raw[1] + '"', i + raw.end())
            i = len(text) if end < 0 else end + len(raw[1]) + 2
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            yield origin, text[start:i]
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            yield origin, text[start:i]
        elif text[i] == "'" and re.search(r"\b[0-9][A-Za-z0-9.']*$", text[:i]) and i + 1 < len(text) and text[i + 1].isalnum():
            # A numeric separator is not the beginning of a character literal.
            i += 1
        elif text[i] in {'"', "'"}:
            quote = text[i]
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
        else:
            i += 1
        line += text[start:i].count("\n")

def suppression_problems(text, policy):
    if policy == "unrestricted":
        return []
    text = text.replace("\\\r\n", "").replace("\\\n", "")
    result = []
    for line, comment in comments(text):
        if not re.search(r"NOLINT|cppcheck-suppress|clang-format\s+off|GCOVR?_EXCL|LCOV_EXCL", comment):
            continue
        narrow = re.search(r"(?:NOLINT(?:NEXTLINE)?\(([a-zA-Z0-9_.,-]+)\)|cppcheck-suppress\s+([a-zA-Z][a-zA-Z0-9]+))\s+(?://\s*|--\s*)?reason:\s*\S", comment)
        if policy == "none" or narrow is None:
            result.append(f"line {line}: disallowed or unexplained suppression")
    # Compiler diagnostics pragmas can suppress errors before analyzers see them.
    stripped = list(text)
    for match in re.finditer(r'R"([^ ()\\\t\r\n]{0,16})\([\s\S]*?\)\1"|"(?:\\.|[^"\\])*"', text):
        # Preserve pragma strings because their diagnostic name is significant.
        prefix = text[text.rfind("\n", 0, match.start())+1:match.start()]
        if "#pragma" not in prefix:
            stripped[match.start():match.end()] = " " * (match.end()-match.start())
    if re.search(r"^\s*#\s*pragma\s+(?:GCC|clang)\s+(?:diagnostic\s+ignored|system_header)", "".join(stripped), re.MULTILINE):
        result.append("compiler diagnostic suppression pragma requires unrestricted policy")
    return result

def suppressions(cfg):
    problems = [f"{p.relative_to(c.ROOT)}: {problem}" for p in c.source_files() for problem in suppression_problems(p.read_text(), cfg["suppressions"])]
    if problems:
        raise c.Failure("\n".join(problems))

def formatting(cfg):
    if c.version_at_least(c.llvm("clang-format"), "1")[0] != c.catalog()["tools"]["llvm_major"]:
        raise c.Failure("clang-format version differs from the reviewed catalog")
    files = c.source_files()
    if not files:
        raise c.Failure("no maintained C++ sources")
    for offset in range(0, len(files), 50):
        c.run([c.llvm("clang-format"), "--dry-run", "--Werror", f"--style=file:{c.ROOT / '.clang-format'}", *files[offset:offset+50]])

def analysis_db(cfg, variant):
    directory, entries = build.compilation_database(cfg, variant)
    folder = directory / "gate-analysis"
    folder.mkdir(exist_ok=True)
    # Independently parse every public header with the project's compile flags.
    reference = next((e for e in entries if Path(e["file"]).name == "header_test.cpp"), entries[0])
    original = reference.get("arguments") or shlex.split(reference["command"])
    headers = sorted(p for p in (c.ROOT / "include").rglob("*") if p.suffix in {".h", ".hpp", ".hh", ".hxx"})
    for number, header in enumerate(headers):
        probe = folder / f"header_{number}.cpp"
        probe.write_text(f'#include "{header.as_posix()}"\n')
        args = []
        skip = False
        for index, arg in enumerate(original):
            if skip:
                skip = False
                continue
            if arg in {"-o", "-MF", "-MT", "-MQ"}:
                skip = True
                continue
            if arg in {"-MD", "-MMD"}:
                continue
            candidate = (Path(reference["directory"]) / arg).resolve() if not arg.startswith("-") else None
            args.append(str(probe) if candidate == Path(reference["file"]) else arg)
        entries.append({"directory": reference["directory"], "file": str(probe), "arguments": args})
    c.write_json(folder / "compile_commands.json", entries)
    return folder, entries

def tidy(cfg):
    folder, entries = analysis_db(cfg, "analysis")
    binary = c.llvm("clang-tidy")
    if c.version_at_least(binary, "1")[0] != c.catalog()["tools"]["llvm_major"]:
        raise c.Failure("clang-tidy version differs from the reviewed catalog")
    config = c.ROOT / ".clang-tidy"
    c.run([binary, "--verify-config", f"--config-file={config}"])
    for file in sorted({e["file"] for e in entries}):
        c.run([binary, file, "-p", folder, f"--config-file={config}", "--warnings-as-errors=*"])

def cppcheck(cfg):
    c.version_at_least("cppcheck", c.catalog()["tools"]["cppcheck_min"])
    variant = "analysis" if cfg["clang_tidy"] == "yes" else "debug"
    folder, entries = analysis_db(cfg, variant)
    (folder / "cppcheck").mkdir(exist_ok=True)
    args = ["cppcheck", f"--project={folder / 'compile_commands.json'}", f"--cppcheck-build-dir={folder / 'cppcheck'}", "--error-exitcode=1", f"--std=c++{cfg['cpp_standard']}", "--inline-suppr"]
    if cfg["cppcheck_categories"]:
        args += ["--enable=" + ",".join(cfg["cppcheck_categories"])]
    c.run(args)

def coverage(cfg):
    c.version_at_least("gcovr", c.catalog()["tools"]["gcovr"])
    directory = c.build_dir(cfg, "coverage")
    for p in directory.rglob("*.gcda"):
        p.unlink()
    for p in (directory / "profiles").glob("*.profraw"):
        p.unlink()
    build.build(cfg, "coverage")
    build.test(cfg, "coverage")
    reports = c.ROOT / "reports"
    reports.mkdir(exist_ok=True)
    family = c.compiler(cfg, "coverage")[0]
    if family == "clang":
        raw = sorted((directory / "profiles").glob("*.profraw"))
        if not raw:
            raise c.Failure("no LLVM coverage profiles were produced")
        merged = directory / "coverage.profdata"
        c.run([c.llvm("llvm-profdata"), "merge", "-sparse", *raw, "-o", merged])
        binaries = [directory / "unit_tests"]
        if (directory / "app").exists():
            binaries.append(directory / "app")
        if (directory / "gui_smoke").exists():
            binaries.append(directory / "gui_smoke")
        binaries += list(directory.glob("*.so")) + list(directory.glob("*.dylib"))
        args = [str(binaries[0]), *[arg for p in binaries[1:] for arg in ("-object", str(p))], f"-instr-profile={merged}"]
        data = json.loads(c.run([c.llvm("llvm-cov"), "export", *args], capture=True))
        files = [f for unit in data["data"] for f in unit["files"] if any(Path(f["filename"]).is_relative_to(c.ROOT / d) for d in ("src", "include"))]
        totals = {"line_total": 0, "line_covered": 0, "branch_total": 0, "branch_covered": 0}
        for file in files:
            for prefix, metric in (("line", "lines"), ("branch", "branches")):
                totals[prefix + "_total"] += file["summary"][metric]["count"]
                totals[prefix + "_covered"] += file["summary"][metric]["covered"]
        totals["files"] = [{"filename": f["filename"], "summary": f["summary"]} for f in files]
        c.write_json(reports / "coverage.json", totals)
        c.run([c.llvm("llvm-cov"), "show", *args, "-format=html", f"-output-dir={reports / 'html'}", *[f["filename"] for f in files]])
        percent = 100.0 * totals["branch_covered"] / totals["branch_total"] if totals["branch_total"] else 100.0
        print(f"First-party branch coverage: {percent:.2f}%")
        if not totals["line_total"] or percent < int(cfg["coverage"]):
            raise c.Failure("missing first-party coverage or branch threshold not met")
        return
    gcov = c.llvm("llvm-cov") + " gcov" if family == "clang" else c.executable("gcov")
    c.run(["gcovr", "--root", c.ROOT, "--filter", re.escape(str(c.ROOT / "src")) + "/", "--filter", re.escape(str(c.ROOT / "include")) + "/",
           "--gcov-executable", gcov, "--exclude-unreachable-branches", "--exclude-throw-branches",
           "--fail-under-branch", cfg["coverage"], "--json-summary", reports / "coverage.json", "--xml", reports / "coverage.xml", "--html-details", reports / "coverage.html", directory])
    report = json.loads((reports / "coverage.json").read_text())
    if not report.get("line_total"):
        raise c.Failure("coverage measured no first-party executable lines")

def file_guard():
    if not (c.ROOT / ".git").exists():
        return
    out = c.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], capture=True)
    forbidden = (".env", ".env.*", "*.pem", "*.key", "*.p12", "id_rsa*", "id_ed25519*", "credentials*.json")
    for name in out.split("\0"):
        if not name:
            continue
        p = c.ROOT / name
        if p.name != ".env.example" and any(fnmatch.fnmatch(p.name, pattern) for pattern in forbidden):
            raise c.Failure(f"potential secret file: {name}")
        if p.is_file() and p.stat().st_size > 512 * 1024:
            raise c.Failure(f"tracked/untracked file exceeds 512 KiB: {name}")

def staged():
    if not (c.ROOT / ".git").exists():
        raise c.Failure("staged checks require Git")
    c.run(["git", "diff", "--quiet"])
    if c.run(["git", "ls-files", "--others", "--exclude-standard"], capture=True).strip():
        raise c.Failure("unstaged/untracked files would make checks differ from the commit; stage or stash them")

def check(cfg):
    results = []
    def gate(name, action, needs=()):
        failed = [x for x in needs if dict(results).get(x) != "PASS"]
        if failed:
            print(f"BLOCKED {name}: {', '.join(failed)}", flush=True)
            results.append((name, "BLOCKED"))
            return
        try:
            action()
        except (c.Failure, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            print(f"FAIL {name}: {error}", flush=True)
            results.append((name, "FAIL"))
        else:
            results.append((name, "PASS"))
    gate("seal", lambda: integrity(cfg))
    gate("tools", lambda: toolchain(cfg, optional=False))
    gate("lock", lambda: deps.verify_lock(cfg))
    gate("files", file_guard)
    gate("suppressions", lambda: suppressions(cfg))
    if cfg["clang_format"] == "yes":
        gate("format", lambda: formatting(cfg))
    gate("build", lambda: build.build(cfg), ("tools", "lock"))
    gate("tests", lambda: build.test(cfg), ("build",))
    if cfg["profile"] in {"library", "header-only"}:
        gate("consumer", lambda: build.consumer(cfg), ("build",))
    if cfg["clang_tidy"] == "yes":
        gate("analysis-build", lambda: build.build(cfg, "analysis"), ("tools", "lock"))
        gate("clang-tidy", lambda: tidy(cfg), ("analysis-build",))
    if cfg["cppcheck"] == "yes":
        gate("cppcheck", lambda: cppcheck(cfg), ("analysis-build" if cfg["clang_tidy"] == "yes" else "build",))
    if cfg["sanitizers"] != "none":
        def sanitizer():
            build.build(cfg, "sanitizer")
            build.test(cfg, "sanitizer")
        gate("sanitizers", sanitizer, ("tools", "lock"))
    if cfg["coverage"] != "0":
        gate("coverage", lambda: coverage(cfg), ("tools", "lock"))
    print("\n" + "\n".join(f"{status:7} {name}" for name, status in results))
    return 0 if all(status == "PASS" for name, status in results) else 1
