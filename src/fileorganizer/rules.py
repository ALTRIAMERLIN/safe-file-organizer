"""Rename/classify rules (frozen data structure)."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .errors import RuleError

CLASSIFY_MODES = ("none", "extension", "month")
_KEYS = {"find", "replace", "prefix", "suffix", "numbering", "digits", "classify", "recursive", "extensions"}


@dataclass(frozen=True)
class Rules:
    find: str = ""            # literal, case-sensitive; applied to the stem only
    replace: str = ""
    prefix: str = ""
    suffix: str = ""
    numbering: bool = False   # appends '_' + number to the stem
    digits: int = 3
    classify: str = "none"    # none | extension | month (UTC)
    recursive: bool = False
    extensions: tuple[str, ...] = ()  # case-insensitive filter, without dot; empty = all

    def validate(self) -> "Rules":
        for name in ("find", "replace", "prefix", "suffix"):
            if not isinstance(getattr(self, name), str):
                raise RuleError(f"'{name}' must be text.")
        if self.find == "" and self.replace != "":
            raise RuleError("Find text must not be empty when Replace is set. Enter text to find or clear Replace.")
        if not isinstance(self.numbering, bool) or not isinstance(self.recursive, bool):
            raise RuleError("'numbering' and 'recursive' must be true or false.")
        if not isinstance(self.digits, int) or isinstance(self.digits, bool) or not 1 <= self.digits <= 10:
            raise RuleError("'digits' must be a whole number from 1 to 10.")
        if self.classify not in CLASSIFY_MODES:
            raise RuleError(f"'classify' must be one of {', '.join(CLASSIFY_MODES)}.")
        if not all(isinstance(e, str) for e in self.extensions):
            raise RuleError("'extensions' must be a list of text values.")
        return self

    @property
    def is_noop(self) -> bool:
        return (
            self.find == "" and self.prefix == "" and self.suffix == ""
            and not self.numbering and self.classify == "none"
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["extensions"] = list(self.extensions)
        return d

    @classmethod
    def from_dict(cls, data: Any) -> "Rules":
        if not isinstance(data, dict):
            raise RuleError("Rules must be a JSON object.")
        unknown = set(data) - _KEYS
        if unknown:
            raise RuleError(f"Unknown rule keys: {', '.join(sorted(unknown))}.")
        d = dict(data)
        exts = d.get("extensions", [])
        if not isinstance(exts, (list, tuple)):
            raise RuleError("'extensions' must be a list.")
        d["extensions"] = normalize_extensions(exts)
        return cls(**d).validate()


def normalize_extensions(exts) -> tuple[str, ...]:
    out = []
    for e in exts:
        if not isinstance(e, str):
            raise RuleError("'extensions' must be a list of text values.")
        e = e.strip().lstrip(".").lower()
        if e:
            out.append(e)
    return tuple(sorted(set(out)))
