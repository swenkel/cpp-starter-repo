"""Validated generator answers."""
import json
from dataclasses import dataclass
from pathlib import Path
from starter.payload.schema import CHOICES, ConfigError, resolve

AnswerError = ConfigError

@dataclass(frozen=True)
class Answers:
    values: dict

    def __getattr__(self, name):
        if name in self.values:
            return self.values[name]
        raise AttributeError(name)

    @property
    def package(self):
        return self.name.replace("-", "_")

    @property
    def docker(self):
        return self.environment == "docker"

    @property
    def denied_git(self):
        return tuple(x for x in ("add", "commit", "push") if self.values[f"agent_git_{x}"] == "no")

def parse(raw):
    return Answers(resolve(raw))

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
