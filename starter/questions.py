"""Conditional interactive questionnaire, including advanced overrides."""
import json
from starter.answers import parse, AnswerError
from starter.payload.schema import CHOICES, FAMILIES, resolve

def choose(key, choices, read=input, write=print, default=True):
    write(f"\n{key.replace('_', ' ').capitalize()}: " + ", ".join(f"{i+1}) {x}" for i, x in enumerate(choices)))
    while True:
        reply = read(f"[{choices[0]}] > " if default else "> ").strip()
        if not reply and default:
            return choices[0]
        if reply in choices:
            return reply
        if reply.isdecimal() and 1 <= int(reply) <= len(choices):
            return choices[int(reply)-1]
        write("Choose a listed value or number.")

def ask(read=input, write=print):
    while True:
        name = read("Project name: ").strip()
        try:
            parse({"name": name})
            break
        except AnswerError as error:
            write(str(error))
    raw = {"name": name}
    for key in ("profile", "build_system", "cpp_standard", "dependencies", "environment", "compiler", "test_runner", "quality"):
        raw[key] = choose(key, CHOICES[key], read, write)
    if raw["profile"] == "library":
        raw["library_type"] = choose("library_type", CHOICES["library_type"], read, write)
    if raw["environment"] == "docker":
        raw["base_image"] = choose("base_image", CHOICES["base_image"], read, write)
        if raw["base_image"] == "custom":
            raw["container_image"] = read("Container image (tag or digest): ").strip()
    if raw["profile"] == "qt":
        options = ["installed", "source"]
        if raw["dependencies"] != "native":
            options.insert(0, "provider")
        if raw.get("container_image"):
            options.insert(0, "image")
        raw["qt_source"] = choose("qt_source", options, read, write, default=False)
    if choose("Override preset gates and guidelines?", ("no", "yes"), read, write) == "yes":
        defaults = resolve(raw)
        for key in ("clang_format", "clang_tidy", "cppcheck", "warnings_as_errors", "sanitizers", "coverage", "suppressions", "style", "format_style", "line_length"):
            choices = [defaults[key], *[x for x in CHOICES[key] if x != defaults[key]]]
            raw[key] = choose(key, choices, read, write)
        if raw["clang_tidy"] == "yes":
            write("Guideline families: " + ", ".join(FAMILIES))
            reply = read("Comma-separated families (empty = preset): ").strip()
            if reply:
                raw["guidelines"] = [x.strip() for x in reply.split(",") if x.strip()]
            for key in ("tidy_add", "tidy_remove"):
                reply = read(f"{key}: comma-separated exact checks (empty = none): ").strip()
                if reply:
                    raw[key] = [x.strip() for x in reply.split(",")]
            reply = read("Check options as JSON object (empty = none): ").strip()
            if reply:
                raw["tidy_options"] = json.loads(reply)
        if raw["cppcheck"] == "yes":
            reply = read("Cppcheck categories, comma-separated (empty = preset): ").strip()
            if reply:
                raw["cppcheck_categories"] = [x.strip() for x in reply.split(",")]
    for key in ("guard", "test_approval", "agent_git_add", "agent_git_commit", "agent_git_push", "ci", "git_init"):
        raw[key] = choose(key, CHOICES[key], read, write)
    return raw
