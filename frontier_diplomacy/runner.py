"""Season orchestration around the upstream ``lm_game.py`` runner.

This module does not reimplement game logic. It translates a league assignment
into the upstream runner's existing ``--models`` interface and records a
season-level completion marker around that process.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from .registry import LabRegistry
from .persistence import create_manifest
from .scheduler import GameAssignment, SeasonSchedule


@dataclass(frozen=True)
class GameRun:
    game_id: str
    directory: Path
    status: str
    returncode: int | None


def load_schedule(path: str | Path) -> SeasonSchedule:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SeasonSchedule(
        games=int(data["games"]),
        scheduler_seed=int(data["scheduler_seed"]),
        assignments=tuple(GameAssignment(**item) for item in data["assignments"]),
    )


class SeasonRunner:
    def __init__(self, registry: LabRegistry, schedule: SeasonSchedule, season_dir: str | Path, repo_root: str | Path):
        self.registry = registry
        self.schedule = schedule
        self.season_dir = Path(season_dir)
        self.repo_root = Path(repo_root)
        self.games_dir = self.season_dir / "games"
        if not (self.season_dir / "manifest.json").exists():
            create_manifest(self.season_dir, registry, schedule, self.repo_root)

    def _metadata(self, game: GameAssignment) -> dict:
        return {
            "game_id": game.game_id,
            "game_seed": game.seed,
            "scheduler_seed": self.schedule.scheduler_seed,
            "assignments": {
                power: {
                    "lab": lab_id,
                    "display_name": self.registry.get(lab_id).display_name,
                    "provider": self.registry.get(lab_id).provider,
                    "model": self.registry.get(lab_id).model,
                }
                for power, lab_id in game.assignments.items()
            },
        }

    def command_for(self, game: GameAssignment, max_year: int = 1910, negotiation_rounds: int = 2) -> list[str]:
        models = ",".join(self.registry.get(game.assignments[power]).upstream_model_id() for power in game.assignments)
        return [
            sys.executable,
            "lm_game.py",
            "--run_dir",
            str(self.games_dir / game.game_id),
            "--max_year",
            str(max_year),
            "--num_negotiation_rounds",
            str(negotiation_rounds),
            "--models",
            models,
            "--seed_base",
            str(game.seed),
        ]

    def run_game(self, game_id: str, *, force: bool = False, dry_run: bool = False, max_year: int = 1910, negotiation_rounds: int = 2) -> GameRun:
        game = next((item for item in self.schedule.assignments if item.game_id == game_id), None)
        if game is None:
            raise KeyError(f"Unknown game: {game_id}")
        directory = self.games_dir / game.game_id
        status_path = directory / "status.json"
        if status_path.exists() and not force:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") == "completed":
                return GameRun(game.game_id, directory, "completed", 0)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "metadata.json").write_text(json.dumps(self._metadata(game), indent=2) + "\n", encoding="utf-8")
        command = self.command_for(game, max_year, negotiation_rounds)
        if dry_run:
            return GameRun(game.game_id, directory, "planned", None)
        started = datetime.now(timezone.utc).isoformat()
        completed = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, check=False)
        (directory / "runner.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (directory / "runner.stderr.log").write_text(completed.stderr, encoding="utf-8")
        status = "completed" if completed.returncode == 0 else "failed"
        status_path.write_text(
            json.dumps({"status": status, "returncode": completed.returncode, "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
            encoding="utf-8",
        )
        return GameRun(game.game_id, directory, status, completed.returncode)

    def run_season(self, **kwargs) -> list[GameRun]:
        return [self.run_game(game.game_id, **kwargs) for game in self.schedule.assignments]
