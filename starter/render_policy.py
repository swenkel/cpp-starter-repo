"""Agent policies express the actual generated selections."""
import json
from starter.payload.schema import checks

def agents(a):
    git = "\n".join(f"- Agents {'may' if a.values['agent_git_'+op] == 'yes' else 'must not'} run git {op}." for op in ("add", "commit", "push"))
    return f'''# Project instructions

Apply these instructions throughout the repository.

## Development

- Use C++{a.cpp_standard}, {a.build_system}, and the selected {a.dependencies} dependencies.
- {'Run all builds, tests, tools, and dependency operations in Docker through scripts/compose.sh. Do not fall back to host execution or install host dependencies.' if a.docker else 'Use scripts/project.py for setup, builds, tests, and checks.'}
- Use RAII, explicit ownership, const-correct APIs, and bounded operations.
- Keep application entrypoints thin and business logic testable.
- Keep external input validation at the boundary. Do not introduce undefined behavior.
- Public API changes require an explicit request. Explain new dependencies.
- Profile before optimizing and report measurements actually obtained.

## Git

{git}
- Never bypass hooks, force-push, rewrite history, or discard unrelated changes.
- Read-only Git inspection is permitted.

## Tests and quality

- Add meaningful regression tests for behavior changes. Never weaken tests to hide failures.
{'- Obtain human approval before changing existing tests or fixtures. New tests may be added and refined within their creation task.' if a.test_approval == 'yes' else '- Existing tests may be updated for authorized behavior changes.'}
- Quality preset: {a.quality}; coverage: {a.coverage}%; sanitizers: {a.sanitizers}.
- Suppression policy: {a.suppressions}. Narrow suppressions name the exact diagnostic and include `reason: ...`.
- Enabled guideline families: {', '.join(a.guidelines)}; style: {a.style}.
- The exact analyzer checks are recorded in .clang-tidy. These are selected automated rules, not full standards compliance.
- Do not disable rules, lower thresholds, exclude sources, or skip gates to obtain a pass.
- Changes to gate configuration, analyzer settings, build enforcement, scripts, hooks, container setup, or CI require an explicit human request for that change.
{'- Gate files are sealed. Only a human may run `scripts/project.py seal` after reviewing changes.' if a.guard == 'seal' else ''}
- Run `scripts/check.sh` before declaring readiness. Report failures and unavailable checks truthfully.
'''

def settings(a):
    deny = [f"Bash(git {op} *)" for op in a.denied_git]
    deny += ["Bash(git -c *)", "Bash(git * --no-verify*)", "Bash(git commit -n*)", "Bash(git config *hooksPath*)", "Bash(git push * --force*)", "Bash(*project.py seal*)", "Bash(*check.sh --seal*)"]
    deny += [f"Edit(/{path})" for path in ("AGENTS.md", "gates.toml", ".clang*", "scripts/**", ".githooks/**", ".github/**", ".claude/settings.json", "CMakeLists.txt", "cmake/**", "meson.build", "meson.options")]
    return json.dumps({"permissions": {"deny": deny}}, indent=2) + "\n"
