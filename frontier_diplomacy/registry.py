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
    reasoning_effort: str | None = None
    service_tier: str = "standard"
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
            reasoning_effort=values.get("reasoning_effort"),
            service_tier=str(values.get("service_tier", "standard")),
            metadata=dict(values.get("metadata") or {}),
        )

    def upstream_model_id(self) -> str:
        """Return the explicit provider-prefixed ID understood by upstream clients."""
        provider = {"google": "gemini", "meta": "openrouter"}.get(self.provider, self.provider)
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
        # A lab may either be a single legacy profile or a catalog of pinned
        # model profiles. Catalog entries are flattened into independently
        # selectable competitors (for example, ``openai_gpt_6_astra``), while
        # retaining their parent lab in metadata for results grouping.
        profiles: list[LabConfig] = []
        for lab_id, raw_values in raw_labs.items():
            values = raw_values or {}
            models = values.get("models")
            if not models:
                profiles.append(LabConfig.from_mapping(lab_id, values))
                continue
            if not isinstance(models, dict):
                raise ValueError(f"Lab '{lab_id}' models must be a mapping")
            inherited = {key: value for key, value in values.items() if key not in {"models", "model", "display_name"}}
            for model_key, model_values in models.items():
                if not isinstance(model_values, dict):
                    raise ValueError(f"Model '{lab_id}.{model_key}' must be a mapping")
                merged = {**inherited, **model_values}
                metadata = dict(inherited.get("metadata") or {})
                metadata.update(model_values.get("metadata") or {})
                metadata.setdefault("lab_id", lab_id)
                merged["metadata"] = metadata
                merged.setdefault("display_name", f"{values.get('display_name', lab_id)} — {model_key}")
                profiles.append(LabConfig.from_mapping(f"{lab_id}_{model_key}", merged))
        return cls(profiles)

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
