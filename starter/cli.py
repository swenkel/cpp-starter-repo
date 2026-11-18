"""Command-line interface for offline C++ project generation."""
import argparse
import sys
from pathlib import Path
from starter import answers, apply, plan, questions
from starter.cleanup import StarterError

def main(root, arguments=None):
    parser = argparse.ArgumentParser(description="Generate a configurable C++ project. Without --output, safely replace the starter and its Git history.")
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--check-images", action="store_true", help="opt-in network check for newer built-in image tags")
    options = parser.parse_args(arguments)
    try:
        if options.check_images:
            from starter.images import check
            return check()
        if options.show and not options.dry_run:
            raise ValueError("--show requires --dry-run")
        raw = answers.load(options.answers) if options.answers else questions.ask()
        chosen = answers.parse(raw)
        files = plan.build(chosen)
        if options.dry_run:
            for file in files:
                print(f"{file.mode:o} {len(file.content.encode()):6d} {file.path}")
                if options.show:
                    print(file.content)
            return 0
        if options.output is None and options.answers is None:
            if input(f"Replace {root}, including starter Git history? [y/N] ").strip().lower() not in {"y", "yes"}:
                print("Nothing changed.")
                return 1
        target = apply.generate(root, files, chosen, options.output)
        if chosen.git_init == "yes":
            print(apply.init_git(target))
        print(f"Created {len(files)} files in {target}.\nNext: python3 scripts/project.py lock\n      python3 scripts/project.py setup\n      scripts/check.sh")
        return 0
    except (OSError, ValueError, StarterError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("Aborted.", file=sys.stderr)
        return 130
