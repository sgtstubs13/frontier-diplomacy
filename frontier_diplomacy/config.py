"""Configuration loading for the league layer."""

from pathlib import Path
import re
from typing import Any


def _minimal_yaml(path: str | Path) -> dict[str, Any]:
    """Parse the small, human-edited mapping subset used by bundled configs.

    This keeps the smoke CLI usable in a bare Python checkout; PyYAML remains
    the normal parser and is declared as a project dependency.
    """
    root: dict[str, Any] = {}
    section: dict[str, Any] | None = None
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if not line.startswith(" ") and stripped.endswith(":"):
            section = {}
            root[stripped[:-1]] = section
            continue
        if section is None or ":" not in stripped:
            continue
        key, value = (part.strip() for part in stripped.split(":", 1))
        if value.startswith("{") and value.endswith("}"):
            fields = {}
            for field in re.split(r",\s*", value[1:-1]):
                field_key, field_value = (part.strip() for part in field.split(":", 1))
                fields[field_key] = _scalar(field_value)
            section[key] = fields
        else:
            section[key] = _scalar(value)
    return root


def _scalar(value: str) -> Any:
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.lower() in ("null", "~"):
        return None
    if value.startswith(("'", '"')) and value.endswith(value[0]):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        return _minimal_yaml(path)
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at the root of {path}")
    return data
