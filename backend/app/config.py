from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return repo_root() / "data"


def wikipedia_it_dir() -> Path:
    return data_dir() / "wikipedia_it"
