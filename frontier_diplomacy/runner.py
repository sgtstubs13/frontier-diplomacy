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
import os
from datetime import datetime, timezone

from .registry import LabRegistry
from .persistence import create_manifest
from .scheduler import GameAssignment, SeasonSchedule
from .experiment import ExperimentConfig


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
    def __init__(self, registry: LabRegistry, schedule: SeasonSchedule, season_dir: str | Path, repo_root: str | Path, config: ExperimentConfig | None = None):
        self.registry = registry
        self.schedule = schedule
        self.season_dir = Path(season_dir)
        self.repo_root = Path(repo_root)
        self.games_dir = self.season_dir / "games"
        self.config = config
        schedule_path = self.season_dir / "schedule.json"
        if not schedule_path.exists():
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(json.dumps(schedule.to_dict(), indent=2) + "\n", encoding="utf-8")
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
            "experiment_config": self.config.to_dict() if self.config else None,
        }

    def command_for(self, game: GameAssignment, max_year: int = 1910, negotiation_rounds: int = 2) -> list[str]:
        if self.config:
            # ``ExperimentConfig.max_year`` is a duration selected by the
            # operator (1--99 game years).  The legacy engine, however,
            # expects an absolute Diplomacy calendar year (e.g. 1920), and
            # stops before a phase whose year is greater than that value.
            # Passing the duration directly made every experiment stop at
            # S1901M because 1901 > 20.
            max_year = 1900 + self.config.max_year
            negotiation_rounds = self.config.negotiation_rounds
        models = ",".join(self.registry.get(game.assignments[power]).upstream_model_id() for power in game.assignments)
        command = [
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
        if self.config:
            command.extend(["--prompt_profile", self.config.prompt_profile])
            if self.config.planning_phase:
                command.append("--planning_phase")
            if self.config.press_mode == "gunboat":
                command.extend(["--num_negotiation_rounds", "0"])
            if self.config.ending_mode == "solo_only":
                command.append("--solo_only")
        return command

    def run_game(self, game_id: str, *, force: bool = False, dry_run: bool = False, allow_placeholders: bool = False, max_year: int = 1910, negotiation_rounds: int = 2) -> GameRun:
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
        if not allow_placeholders and any(self.registry.get(lab).model.strip().upper() == "MODEL_ID" for lab in game.assignments.values()):
            raise ValueError("Refusing to start a paid game while a lab still uses model placeholder MODEL_ID")
        started = datetime.now(timezone.utc).isoformat()
        environment = os.environ.copy()
        if self.config:
            # The game runs in a child process. Pass the ledger context so its
            # provider calls can reserve and reconcile actual charges.
            environment.update({
                "FRONTIER_LEDGER_PATH": str(self.repo_root / "data" / "frontier_diplomacy_costs.sqlite"),
                "FRONTIER_EXPERIMENT_ID": self.season_dir.name,
                "FRONTIER_GAME_ID": game.game_id,
                "FRONTIER_TRACE_PATH": str((directory / "calls.jsonl").resolve()),
            })
        completed = subprocess.run(command, cwd=self.repo_root, env=environment, capture_output=True, text=True, check=False)
        (directory / "runner.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (directory / "runner.stderr.log").write_text(completed.stderr, encoding="utf-8")
        status = "completed" if completed.returncode == 0 else "paused"
        if status == "completed":
            self._write_summary(directory)
        status_path.write_text(
            json.dumps({"status": status, "returncode": completed.returncode, "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
            encoding="utf-8",
        )
        return GameRun(game.game_id, directory, status, completed.returncode)

    @staticmethod
    def _write_summary(directory: Path) -> None:
        """Derive transparent terminal facts from the engine save, not logs."""
        game_path = directory / "lmvsgame.json"
        if not game_path.exists():
            return
        saved = json.loads(game_path.read_text(encoding="utf-8"))
        phases = saved.get("phases", [])
        state = phases[-1].get("state", {}) if phases else {}
        centers = state.get("centers", {})
        outcome = saved.get("outcome", [])
        winners = outcome[1:] if isinstance(outcome, list) else []
        summary = {
            "final_supply_centers": {power: len(value) if isinstance(value, list) else value for power, value in centers.items()},
            "solo_winner": winners[0] if len(winners) == 1 else None,
            "draw": len(winners) > 1,
            "survivors": [power for power, value in centers.items() if value],
            "termination_reason": "solo" if len(winners) == 1 else "draw" if len(winners) > 1 else "year_limit",
        }
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    def run_season(self, **kwargs) -> list[GameRun]:
        return [self.run_game(game.game_id, **kwargs) for game in self.schedule.assignments]
