"""Immutable experiment configuration shared by the CLI, dashboard, and runner."""

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import hashlib
import json
from typing import Any, Literal

from .models import POWERS

PressMode = Literal["gunboat", "full_press"]
EndingMode = Literal["solo_only", "draws_allowed"]


@dataclass(frozen=True)
class ExperimentConfig:
    """All benchmark-affecting controls, frozen before paid work begins."""

    name: str
    model_ids: tuple[str, ...]
    games: int = 7
    seed: int = 42
    max_year: int = 20
    press_mode: PressMode = "full_press"
    ending_mode: EndingMode = "draws_allowed"
    negotiation_rounds: int = 3
    planning_phase: bool = False
    budget_usd: Decimal = Decimal("0")
    prompt_profile: str = "neutral-v1"
    memory_profile: str = "private-diary-v1"
    fixed_assignments: tuple[dict[str, str], ...] = ()
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.games < 1:
            raise ValueError("games must be positive")
        if not 1 <= self.max_year <= 99:
            raise ValueError("max_year must be between 1 and 99")
        if self.press_mode not in ("gunboat", "full_press"):
            raise ValueError("invalid press mode")
        if self.ending_mode not in ("solo_only", "draws_allowed"):
            raise ValueError("invalid ending mode")
        if self.press_mode == "gunboat" and self.negotiation_rounds:
            object.__setattr__(self, "negotiation_rounds", 0)
        if self.negotiation_rounds < 0:
            raise ValueError("negotiation_rounds cannot be negative")
        if self.budget_usd <= 0:
            raise ValueError("a positive USD budget is required before execution")
        if self.fixed_assignments:
            for assignment in self.fixed_assignments:
                if set(assignment) != set(POWERS):
                    raise ValueError("fixed assignments must contain exactly the seven powers")
                if len(set(assignment.values())) != len(POWERS):
                    raise ValueError("fixed assignments must use seven distinct models")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        value = dict(data)
        value["model_ids"] = tuple(value.get("model_ids", ()))
        value["fixed_assignments"] = tuple(value.get("fixed_assignments", ()))
        value["budget_usd"] = Decimal(str(value["budget_usd"]))
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["budget_usd"] = str(self.budget_usd)
        value["model_ids"] = list(self.model_ids)
        value["fixed_assignments"] = list(self.fixed_assignments)
        return value

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
