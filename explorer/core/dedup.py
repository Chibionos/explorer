from __future__ import annotations
import re
from dataclasses import dataclass, field

_STOPWORDS = {"the", "a", "an", "on", "in", "to", "for", "with", "is", "are"}
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    s = _PUNCT_RE.sub(" ", title.lower())
    tokens = [t for t in _WS_RE.sub(" ", s).strip().split(" ") if t and t not in _STOPWORDS]
    return " ".join(tokens)


@dataclass
class DedupIndex:
    _by_sig: dict[str, str] = field(default_factory=dict)
    _by_key: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, str]]) -> "DedupIndex":
        idx = cls()
        for title, key in pairs:
            idx.record(title, key)
        return idx

    def record(self, title: str, jira_key: str) -> None:
        self._by_sig[normalize_title(title)] = jira_key
        self._by_key[jira_key] = title

    def lookup(self, title: str) -> str | None:
        return self._by_sig.get(normalize_title(title))

    def titles_for_prompt(self) -> list[tuple[str, str]]:
        return [(k, t) for k, t in self._by_key.items()]
