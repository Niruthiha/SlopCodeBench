"""Low-level readers for the raw SDE files (bz2-compressed CSVs and YAML)."""

import bz2
import csv
import io
from pathlib import Path
from typing import Dict, Iterator

import yaml


class SDEFileError(Exception):
    """Raised when a required SDE file is missing or unreadable."""


def iter_csv(sde_dir: Path, filename: str) -> Iterator[Dict[str, str]]:
    """Yield each row of a bz2-compressed CSV file as a dict."""
    path = sde_dir / filename
    if not path.is_file():
        raise SDEFileError(f"Missing SDE file: {path}")
    with bz2.open(path, "rb") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        yield from csv.DictReader(text)


def load_yaml(sde_dir: Path, filename: str):
    """Load a plain YAML file."""
    path = sde_dir / filename
    if not path.is_file():
        raise SDEFileError(f"Missing SDE file: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_int(value: str):
    """Parse an integer field, returning None for empty / 'None' values."""
    if value is None:
        return None
    value = value.strip()
    if value == "" or value == "None":
        return None
    return int(float(value))


def parse_float(value: str, default: float = 0.0) -> float:
    """Parse a float field, returning ``default`` for empty / 'None' values."""
    if value is None:
        return default
    value = value.strip()
    if value == "" or value == "None":
        return default
    return float(value)
