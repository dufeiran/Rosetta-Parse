"""Dot-path get/set on nested dicts/lists."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, MutableMapping


def split_path(path: str) -> list[str]:
    return [p for p in path.split(".") if p]


def get(obj: Any, path: str, default: Any = None) -> Any:
    parts = split_path(path)
    cur = obj
    for p in parts:
        if isinstance(cur, Mapping) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur


def set_(obj: MutableMapping, path: str, value: Any) -> None:
    parts = split_path(path)
    if not parts:
        raise ValueError("empty path")
    cur = obj
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, MutableMapping):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def expand_dot_dict(flat: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert {'a.b': 1, 'a.c': 2, 'd': 3} into {'a': {'b': 1, 'c': 2}, 'd': 3}.

    A value that is itself a mapping is merged in (so callers can mix flat dot-keys
    with nested-dict overrides freely).
    """
    out: Dict[str, Any] = {}
    for k, v in flat.items():
        if "." in k:
            set_(out, k, v)
        else:
            existing = out.get(k)
            if isinstance(existing, Mapping) and isinstance(v, Mapping):
                out[k] = _deep_merge(dict(existing), v)
            else:
                out[k] = v
    return out


def _deep_merge(base: Dict[str, Any], extra: Mapping[str, Any]) -> Dict[str, Any]:
    for k, v in extra.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), Mapping):
            base[k] = _deep_merge(dict(base[k]), v)
        else:
            base[k] = v
    return base
