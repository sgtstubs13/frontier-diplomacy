"""Deterministic, randomized, balance-aware season scheduling."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
from typing import Iterable

from .models import POWERS
from .registry import LabRegistry


@dataclass(frozen=True)
class GameAssignment:
    game_id: str
    seed: int
    assignments: dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SeasonSchedule:
    games: int
    scheduler_seed: int
    assignments: tuple[GameAssignment, ...]

    def to_dict(self) -> dict:
        return {"games": self.games, "scheduler_seed": self.scheduler_seed, "assignments": [game.to_dict() for game in self.assignments]}

    def write(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def _assignment_score(order: tuple[str, ...], labs: tuple[str, ...], power_counts, lab_counts, pair_counts) -> float:
    score = 0.0
    for power, lab in zip(POWERS, order):
        score += power_counts[lab][power] * 8
        score += lab_counts[lab] * 2
    for index, left in enumerate(labs):
        for right in labs[index + 1 :]:
            score += pair_counts[tuple(sorted((left, right)))]
    return score


def generate_schedule(registry: LabRegistry, games: int, seed: int) -> SeasonSchedule:
    if games < 1:
        raise ValueError("games must be positive")
    labs = tuple(lab.id for lab in registry.all(enabled_only=True))
    if len(labs) < len(POWERS):
        raise ValueError(f"At least {len(POWERS)} enabled labs are required")
    rng = random.Random(seed)
    lab_counts = Counter()
    power_counts = defaultdict(Counter)
    pair_counts = Counter()
    result: list[GameAssignment] = []
    for game_number in range(1, games + 1):
        candidates = []
        for _ in range(max(32, len(labs) * 4)):
            selected = tuple(rng.sample(labs, len(POWERS)))
            order = list(selected)
            rng.shuffle(order)
            score = _assignment_score(tuple(order), selected, power_counts, lab_counts, pair_counts)
            candidates.append((score, rng.random(), tuple(order)))
        _, _, chosen = min(candidates)
        game_seed = rng.randrange(0, 2**63)
        assignments = dict(zip(POWERS, chosen))
        result.append(GameAssignment(f"league-{game_number:04d}", game_seed, assignments))
        for power, lab in assignments.items():
            lab_counts[lab] += 1
            power_counts[lab][power] += 1
        for index, left in enumerate(chosen):
            for right in chosen[index + 1 :]:
                pair_counts[tuple(sorted((left, right)))] += 1
    return SeasonSchedule(games, seed, tuple(result))


def validate_schedule(schedule: SeasonSchedule, expected_labs: Iterable[str] = ()) -> list[str]:
    errors = []
    expected = set(expected_labs)
    for game in schedule.assignments:
        if set(game.assignments) != set(POWERS):
            errors.append(f"{game.game_id}: powers are not exactly the standard seven")
        labs = list(game.assignments.values())
        if len(labs) != len(set(labs)):
            errors.append(f"{game.game_id}: duplicate lab assignment")
        if expected and not set(labs).issubset(expected):
            errors.append(f"{game.game_id}: unknown lab assignment")
    return errors


def balance_report(schedule: SeasonSchedule) -> dict:
    """Return inspectable balance diagnostics for a generated schedule."""
    appearances = Counter()
    power_counts = defaultdict(Counter)
    pair_counts = Counter()
    for game in schedule.assignments:
        selected = list(game.assignments.values())
        for power, lab in game.assignments.items():
            appearances[lab] += 1
            power_counts[lab][power] += 1
        for index, left in enumerate(selected):
            for right in selected[index + 1 :]:
                pair_counts[tuple(sorted((left, right)))] += 1
    appearance_values = list(appearances.values())
    power_values = [value for counts in power_counts.values() for value in counts.values()]
    pair_values = list(pair_counts.values())
    return {
        "games": len(schedule.assignments),
        "appearances_by_lab": dict(sorted(appearances.items())),
        "power_assignments_by_lab": {lab: dict(sorted(counts.items())) for lab, counts in sorted(power_counts.items())},
        "pairwise_encounters": {"min": min(pair_values, default=0), "max": max(pair_values, default=0)},
        "ranges": {
            "lab_appearances": [min(appearance_values, default=0), max(appearance_values, default=0)],
            "lab_power_assignments": [min(power_values, default=0), max(power_values, default=0)],
        },
    }
