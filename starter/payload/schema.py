"""Shared questionnaire and runtime configuration validation (stdlib only)."""

import copy
import re

CHOICES = {
    "profile": ("cli", "library", "header-only", "http", "numerical", "qt"),
    "build_system": ("cmake", "meson"),
    "cpp_standard": ("20", "17", "23"),
    "dependencies": ("native", "conan", "vcpkg"),
    "environment": ("docker", "local"),
    "compiler": ("clang", "gcc"),
    "test_runner": ("catch2", "gtest"),
    "quality": ("strict", "balanced", "minimal"),
    "library_type": ("static", "shared"),
    "format_style": ("LLVM", "Google"),
    "line_length": ("100", "80", "120"),
    "style": ("none", "google", "llvm"),
    "suppressions": ("none", "narrow", "unrestricted"),
    "coverage": ("90", "80", "100", "0"),
    "sanitizers": ("address,undefined", "none"),
    "clang_format": ("yes", "no"),
    "clang_tidy": ("yes", "no"),
    "cppcheck": ("yes", "no"),
    "warnings_as_errors": ("yes", "no"),
    "guard": ("seal", "config", "policy"),
    "test_approval": ("yes", "no"),
    "agent_git_add": ("no", "yes"),
    "agent_git_commit": ("no", "yes"),
    "agent_git_push": ("no", "yes"),
    "ci": ("github", "none"),
    "git_init": ("yes", "no"),
    "base_image": ("ubuntu:26.04", "debian:trixie", "custom"),
    "qt_source": ("provider", "installed", "source", "image"),
}

# Deliberately enumerated checks: a tool upgrade cannot silently add rules.
FAMILIES = {
    "core": ["cppcoreguidelines-avoid-c-arrays", "cppcoreguidelines-narrowing-conversions",
             "cppcoreguidelines-pro-type-cstyle-cast", "cppcoreguidelines-pro-type-reinterpret-cast",
             "cppcoreguidelines-slicing", "cppcoreguidelines-init-variables"],
    "cert": ["cert-err34-c", "cert-err52-cpp", "cert-err58-cpp", "cert-dcl50-cpp"],
    "bugprone": ["bugprone-use-after-move", "bugprone-sizeof-expression",
                 "bugprone-suspicious-semicolon", "bugprone-integer-division",
                 "bugprone-branch-clone", "bugprone-dangling-handle"],
    "modernize": ["modernize-use-nullptr", "modernize-use-override",
                  "modernize-use-equals-default", "modernize-use-using"],
    "readability": ["readability-braces-around-statements", "readability-container-size-empty",
                    "readability-redundant-string-init"],
    "performance": ["performance-for-range-copy", "performance-unnecessary-copy-initialization",
                    "performance-unnecessary-value-param", "performance-move-const-arg"],
    "portability": ["portability-simd-intrinsics", "portability-std-allocator-const"],
}
STYLES = {"none": [], "google": ["google-explicit-constructor", "google-runtime-int"],
          "llvm": ["llvm-qualified-auto", "llvm-namespace-comment"]}
ANALYZER = ["clang-analyzer-core.CallAndMessage", "clang-analyzer-core.NullDereference",
            "clang-analyzer-core.DivideZero", "clang-analyzer-cplusplus.NewDelete",
            "clang-analyzer-deadcode.DeadStores"]
CATEGORIES = ("warning", "style", "performance", "portability", "unusedFunction")
LIST_KEYS = {"guidelines", "tidy_add", "tidy_remove", "cppcheck_categories"}
FREE_KEYS = {"name", "container_image"}


class ConfigError(ValueError):
    """An unsupported or internally inconsistent selection."""


def resolve(raw):
    """Validate answers and expand presets. Explicit values always win."""
    if not isinstance(raw, dict):
        raise ConfigError("answers must be a JSON object")
    unknown = set(raw) - set(CHOICES) - LIST_KEYS - FREE_KEYS - {"tidy_options"}
    if unknown:
        raise ConfigError("unknown answers: " + ", ".join(sorted(unknown)))
    name = raw.get("name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 40:
        raise ConfigError("name must be lower-case words joined by '-', at most 40 characters")
    if name.replace("-", "_") in {"auto", "class", "namespace", "template", "tests", "src", "include", "scripts", "build", "std", "concept", "requires", "main", "int", "return", "new", "delete", "void", "enum", "struct", "union", "using", "operator", "export", "module", "import", "private", "public", "protected", "static", "const", "volatile", "register", "extern", "inline", "virtual", "explicit", "friend", "typename", "typedef", "bool", "char", "short", "long", "float", "double", "signed", "unsigned", "if", "else", "switch", "case", "default", "break", "continue", "for", "while", "do", "goto", "try", "catch", "throw", "this", "true", "false", "nullptr", "sizeof", "alignof", "alignas", "constexpr", "consteval", "constinit", "noexcept", "thread_local", "mutable", "and", "or", "not", "xor", "bitand", "bitor", "compl", "and_eq", "or_eq", "xor_eq", "not_eq", "co_await", "co_return", "co_yield", "static_assert", "dynamic_cast", "static_cast", "reinterpret_cast", "const_cast", "typeid", "wchar_t", "char8_t", "char16_t", "char32_t"}:
        raise ConfigError("name is reserved in C++ or the generated layout")
    if name.replace("-", "_") in {"app", "gui", "gui_smoke", "unit_tests", "consumer", "project", "catch2", "gtest", "eigen", "httplib", "qt6"}:
        raise ConfigError("name collides with a generated target or namespace alias")
    result = {key: choices[0] for key, choices in CHOICES.items()}
    quality = raw.get("quality", "strict")
    if quality != "strict":
        result.update(coverage="0", sanitizers="none")
    if quality == "minimal":
        result.update(clang_format="no", clang_tidy="no", cppcheck="no", warnings_as_errors="no")
    result.update(name=name, container_image="", guidelines=list(FAMILIES) if quality == "strict" else ["bugprone", "performance", "portability"],
                  tidy_add=[], tidy_remove=[], tidy_options={}, cppcheck_categories=list(CATEGORIES[:-1]))
    result.update(copy.deepcopy(raw))
    for key, choices in CHOICES.items():
        if not isinstance(result[key], str) or result[key] not in choices:
            raise ConfigError(f"{key} must be one of: {', '.join(choices)}")
    for key in LIST_KEYS:
        if not isinstance(result[key], list) or not all(isinstance(x, str) for x in result[key]):
            raise ConfigError(f"{key} must be an array of strings")
        if len(result[key]) != len(set(result[key])):
            raise ConfigError(f"{key} contains duplicates")
    if set(result["guidelines"]) - set(FAMILIES):
        raise ConfigError("unknown guideline family")
    if set(result["cppcheck_categories"]) - set(CATEGORIES):
        raise ConfigError("unknown cppcheck category")
    for key in ("tidy_add", "tidy_remove"):
        if any(not re.fullmatch(r"[a-z][A-Za-z0-9_.-]+", x) for x in result[key]):
            raise ConfigError(f"{key} requires exact diagnostic names, not globs")
    options = result["tidy_options"]
    if not isinstance(options, dict) or not all(isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", k) for k, v in options.items()):
        raise ConfigError("tidy_options must map option names to strings")
    image = result["container_image"]
    if not isinstance(image, str) or (image and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]*", image)):
        raise ConfigError("container_image must be an image reference")
    if result["environment"] == "local" and (raw.get("base_image", "ubuntu:26.04") != "ubuntu:26.04" or image):
        raise ConfigError("container settings require environment=docker")
    if result["base_image"] == "custom" and not image:
        raise ConfigError("base_image=custom requires container_image")
    if image and result["base_image"] != "custom":
        raise ConfigError("container_image requires base_image=custom")
    if result["profile"] == "qt":
        if "qt_source" not in raw:
            raise ConfigError("Qt projects require an explicit qt_source")
        if result["qt_source"] == "provider" and result["dependencies"] == "native":
            raise ConfigError("qt_source=provider requires Conan or vcpkg")
        if result["qt_source"] == "image" and (result["environment"] != "docker" or not image):
            raise ConfigError("qt_source=image requires a custom Docker image")
    elif "qt_source" in raw and raw["qt_source"] != "provider":
        raise ConfigError("qt_source is only applicable to Qt projects")
    if result["clang_tidy"] == "no" and any(key in raw and raw[key] for key in ("guidelines", "tidy_add", "tidy_remove", "tidy_options")):
        raise ConfigError("explicit clang-tidy rules require clang_tidy=yes")
    if result["clang_tidy"] == "no":
        result["guidelines"] = []
    return result


def checks(settings):
    """Resolve the stable catalog; explicit exclusions take precedence."""
    names = ANALYZER + STYLES[settings["style"]]
    for family in settings["guidelines"]:
        names += FAMILIES[family]
    return sorted((set(names) | set(settings["tidy_add"])) - set(settings["tidy_remove"]))
