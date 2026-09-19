"""Transparent first-pass standings and country-bias aggregation."""

from collections import defaultdict
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summary_for(game_dir: Path) -> dict:
    path = game_dir / "summary.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _centers(summary: dict) -> dict[str, float]:
    value = summary.get("final_supply_centers", summary.get("final_sc", {}))
    if not isinstance(value, dict):
        return {}
    return {str(power): _number(count) for power, count in value.items()}


def analyze_season(season_dir: str | Path) -> dict:
    root = Path(season_dir)
    standings: dict[str, dict[str, Any]] = defaultdict(lambda: {"games": 0, "final_sc": [], "solo_wins": 0, "draws": 0, "survivals": 0, "eliminations": 0, "cost": []})
    country: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"games": 0, "final_sc": []}))
    games = []
    for game_dir in sorted((root / "games").glob("*/")) if (root / "games").exists() else []:
        metadata_path = game_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        summary = _summary_for(game_dir)
        centers = _centers(summary)
        assignments = metadata.get("assignments", {})
        for power, details in assignments.items():
            if not isinstance(details, dict):
                continue
            lab = details.get("lab", power)
            stats = standings[lab]
            stats["games"] += 1
            stats["final_sc"].append(centers.get(power, 0.0))
            cell = country[lab][power]
            cell["games"] += 1
            cell["final_sc"].append(centers.get(power, 0.0))
            if summary.get("solo_winner") == power:
                stats["solo_wins"] += 1
            if summary.get("draw") is True or summary.get("termination_reason") == "draw":
                stats["draws"] += 1
            if power in set(summary.get("survivors", [])):
                stats["survivals"] += 1
            elif power in set(summary.get("eliminated", [])):
                stats["eliminations"] += 1
        games.append({"game_id": metadata.get("game_id", game_dir.name), "summary": summary})

    def compact(stats):
        return {
            **{key: value for key, value in stats.items() if key not in ("final_sc", "cost")},
            "avg_final_sc": mean(stats["final_sc"]) if stats["final_sc"] else 0.0,
            "avg_cost": mean(stats["cost"]) if stats["cost"] else None,
        }

    return {
        "games_with_artifacts": len(games),
        "standings": {lab: compact(stats) for lab, stats in sorted(standings.items())},
        "country_bias": {
            lab: {power: {"games": cell["games"], "avg_final_sc": mean(cell["final_sc"]) if cell["final_sc"] else 0.0} for power, cell in sorted(cells.items())}
            for lab, cells in sorted(country.items())
        },
    }
