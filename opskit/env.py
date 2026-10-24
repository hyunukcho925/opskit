"""Minimal .env reader (KEY=VALUE lines). Stdlib only."""
import os
from pathlib import Path


def read(path) -> dict:
    """Parse one .env file without touching os.environ. Missing file -> {}."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load(*paths, override=False) -> dict:
    """Read the files (earlier paths win) and copy their keys into os.environ.

    Keys already in os.environ are left alone unless override=True.
    Returns the merged file values.
    """
    merged = {}
    for p in paths:
        for k, v in read(p).items():
            merged.setdefault(k, v)
    for k, v in merged.items():
        if override or k not in os.environ:
            os.environ[k] = v
    return merged


def get(key, default=None, paths=()):
    """os.environ[key], after loading `paths` for keys not already set."""
    if paths:
        load(*paths)
    return os.environ.get(key, default)
