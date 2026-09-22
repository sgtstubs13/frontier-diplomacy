"""Local experiment service used by both the dashboard and command line."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import threading
import uuid
from typing import Any

from .accounting import CostLedger, CostEstimate, PriceSnapshot
from .experiment import ExperimentConfig
from .persistence import create_manifest
from .registry import LabRegistry
from .runner import SeasonRunner
from .scheduler import GameAssignment, SeasonSchedule, generate_schedule


class ExperimentService:
    """Durable local coordinator. It deliberately runs one game at a time."""

    def __init__(self, root: str | Path = "results", ledger_path: str | Path = "data/frontier_diplomacy_costs.sqlite"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger = CostLedger(ledger_path)
        self._threads: dict[str, threading.Thread] = {}

    def _dir(self, experiment_id: str) -> Path:
        return self.root / experiment_id

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _event(self, experiment_id: str, event: str, **payload: Any) -> None:
        entry = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
        with (self._dir(experiment_id) / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")

    def sync_configured_prices(self, registry: LabRegistry) -> int:
        """Import pinned, source-linked price cards from the model catalog.

        This is idempotent for an unchanged card. Historical cards are never
        edited or deleted, preserving the ledger's audit trail.
        """
        imported = 0
        for profile in registry.all():
            card = profile.metadata.get("price")
            if not isinstance(card, dict):
                continue
            try:
                price = PriceSnapshot(
                    model_id=profile.model,
                    provider=profile.provider,
                    input_per_million=Decimal(str(card["input_per_million"])),
                    output_per_million=Decimal(str(card["output_per_million"])),
                    cached_input_per_million=(Decimal(str(card["cached_input_per_million"]))
                                              if card.get("cached_input_per_million") is not None else None),
                    cache_write_per_million=(Decimal(str(card["cache_write_per_million"]))
                                             if card.get("cache_write_per_million") is not None else None),
                    source=str(card["source"]),
                    effective_at=str(card.get("effective_at", "")),
                    service_tier=profile.service_tier,
                )
            except (KeyError, ArithmeticError, ValueError) as exc:
                raise ValueError(f"Invalid price card for {profile.id}: {exc}") from exc
            current = self.ledger.latest_price(profile.model, profile.provider)
            if current and all((current.input_per_million == price.input_per_million,
                                current.output_per_million == price.output_per_million,
                                current.cached_input_per_million == price.cached_input_per_million,
                                current.cache_write_per_million == price.cache_write_per_million,
                                current.source == price.source,
                                current.service_tier == price.service_tier)):
                continue
            self.ledger.add_price(price)
            imported += 1
        return imported

    def create(self, config: ExperimentConfig, registry: LabRegistry) -> dict[str, Any]:
        self.sync_configured_prices(registry)
        experiment_id = f"{config.name}-{uuid.uuid4().hex[:8]}"
        directory = self._dir(experiment_id)
        directory.mkdir(parents=True, exist_ok=False)
        if config.fixed_assignments:
            assignments = tuple(GameAssignment(f"league-{index:04d}", config.seed + index, assignment)
                                for index, assignment in enumerate(config.fixed_assignments, 1))
            schedule = SeasonSchedule(len(assignments), config.seed, assignments)
        else:
            selected = LabRegistry([registry.get(model_id) for model_id in config.model_ids])
            schedule = generate_schedule(selected, config.games, config.seed)
        self._write_json(directory / "experiment.json", config.to_dict())
        self._write_json(directory / "schedule.json", schedule.to_dict())
        self._write_json(directory / "status.json", {"status": "created", "experiment_id": experiment_id, "config_fingerprint": config.fingerprint})
        create_manifest(directory, registry, schedule, ".", prompt_version=config.prompt_profile)
        self.ledger.set_budget(experiment_id, config.budget_usd, "initial budget")
        self._event(experiment_id, "created", config=config.to_dict(), schedule=schedule.to_dict())
        return self.details(experiment_id)

    def details(self, experiment_id: str) -> dict[str, Any]:
        directory = self._dir(experiment_id)
        config = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
        status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        schedule = json.loads((directory / "schedule.json").read_text(encoding="utf-8"))
        return {"experiment_id": experiment_id, "config": config, "status": status, "schedule": schedule,
                "budget": {key: str(value) for key, value in self.ledger.budget_state(experiment_id).items()}}

    def list(self) -> list[dict[str, Any]]:
        return [self.details(path.name) for path in sorted(self.root.iterdir()) if (path / "experiment.json").exists()]

    def estimate(self, config: ExperimentConfig, registry: LabRegistry) -> CostEstimate:
        self.sync_configured_prices(registry)
        calls: dict[tuple[str, str, str], int] = {}
        movement_phases = config.max_year * 2
        for model_id in config.model_ids:
            model = registry.get(model_id)
            tasks = {"order": movement_phases * 3}
            if config.press_mode == "full_press":
                tasks["negotiation"] = movement_phases * config.negotiation_rounds
                tasks["negotiation_diary_raw"] = movement_phases
            if config.planning_phase:
                tasks["plan_generation"] = movement_phases
            tasks["diary_consolidation"] = max(0, config.max_year - 1)
            for task, count in tasks.items():
                calls[(model.model, model.provider, task)] = calls.get((model.model, model.provider, task), 0) + count * config.games
        return self.ledger.estimate([(registry.get(mid).model, registry.get(mid).provider) for mid in config.model_ids], calls)

    def raise_budget(self, experiment_id: str, budget: Decimal, note: str = "operator increase") -> dict[str, Any]:
        self.ledger.set_budget(experiment_id, budget, note)
        self._event(experiment_id, "budget_changed", budget_usd=str(budget), note=note)
        return self.details(experiment_id)

    def start(self, experiment_id: str, registry: LabRegistry, repo_root: str | Path = ".") -> dict[str, Any]:
        if experiment_id in self._threads and self._threads[experiment_id].is_alive():
            return self.details(experiment_id)
        directory = self._dir(experiment_id)
        config = ExperimentConfig.from_dict(json.loads((directory / "experiment.json").read_text(encoding="utf-8")))
        schedule_data = json.loads((directory / "schedule.json").read_text(encoding="utf-8"))
        schedule = SeasonSchedule(schedule_data["games"], schedule_data["scheduler_seed"], tuple(GameAssignment(**value) for value in schedule_data["assignments"]))

        def work() -> None:
            self._write_json(directory / "status.json", {"status": "running", "experiment_id": experiment_id})
            self._event(experiment_id, "started")
            runner = SeasonRunner(registry, schedule, directory, repo_root, config=config)
            for game in schedule.assignments:
                try:
                    result = runner.run_game(game.game_id)
                    self._event(experiment_id, "game_finished", game_id=game.game_id, status=result.status)
                    if result.status == "paused":
                        detail = "worker exited before completing the game"
                        worker_status = result.directory / "status.json"
                        worker_stderr = result.directory / "runner.stderr.log"
                        if worker_status.exists():
                            try:
                                returncode = json.loads(worker_status.read_text(encoding="utf-8")).get("returncode")
                                detail = f"worker exited with return code {returncode}"
                            except (OSError, ValueError, json.JSONDecodeError):
                                pass
                        if worker_stderr.exists():
                            lines = [line.strip() for line in worker_stderr.read_text(encoding="utf-8").splitlines() if line.strip()]
                            if lines:
                                detail = lines[-1]
                        self._write_json(directory / "status.json", {"status": "paused", "reason": detail, "experiment_id": experiment_id})
                        self._event(experiment_id, "paused", game_id=game.game_id, error=detail)
                        return
                except Exception as exc:
                    self._write_json(directory / "status.json", {"status": "paused", "reason": str(exc), "experiment_id": experiment_id})
                    self._event(experiment_id, "paused", error=str(exc))
                    return
            self._write_json(directory / "status.json", {"status": "completed", "experiment_id": experiment_id})
            self._event(experiment_id, "completed")

        thread = threading.Thread(target=work, name=f"frontier-{experiment_id}", daemon=True)
        self._threads[experiment_id] = thread
        thread.start()
        return self.details(experiment_id)
