"""Configuration-driven lab registry."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_yaml


@dataclass(frozen=True)
class LabConfig:
    id: str
    display_name: str
    provider: str
    model: str
    enabled: bool = True
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, lab_id: str, values: dict[str, Any]) -> "LabConfig":
        required = ("display_name", "provider", "model")
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise ValueError(f"Lab '{lab_id}' is missing required fields: {', '.join(missing)}")
        return cls(
            id=lab_id,
            display_name=str(values["display_name"]),
            provider=str(values["provider"]),
            model=str(values["model"]),
            enabled=bool(values.get("enabled", True)),
            temperature=values.get("temperature"),
            max_output_tokens=values.get("max_output_tokens"),
            metadata=dict(values.get("metadata") or {}),
        )

    def upstream_model_id(self) -> str:
        """Return the explicit provider-prefixed ID understood by upstream clients."""
        provider = {"google": "gemini", "xai": "openrouter", "meta": "openrouter"}.get(self.provider, self.provider)
        if self.model.lower().startswith(provider.lower() + ":"):
            return self.model
        return f"{provider}:{self.model}"


class LabRegistry:
    def __init__(self, labs: list[LabConfig]):
        ids = [lab.id for lab in labs]
        if len(ids) != len(set(ids)):
            raise ValueError("Lab IDs must be unique")
        if not labs:
            raise ValueError("At least one lab is required")
        self._labs = {lab.id: lab for lab in labs}

    @classmethod
    def from_file(cls, path: str | Path) -> "LabRegistry":
        data = load_yaml(path)
        raw_labs = data.get("labs")
        if not isinstance(raw_labs, dict):
            raise ValueError("Configuration must contain a 'labs' mapping")
        return cls([LabConfig.from_mapping(lab_id, values or {}) for lab_id, values in raw_labs.items()])

    def get(self, lab_id: str) -> LabConfig:
        try:
            return self._labs[lab_id]
        except KeyError as exc:
            raise KeyError(f"Unknown lab: {lab_id}") from exc

    def all(self, enabled_only: bool = False) -> list[LabConfig]:
        labs = list(self._labs.values())
        return [lab for lab in labs if lab.enabled] if enabled_only else labs

    def __len__(self) -> int:
        return len(self._labs)
