"""Season-level reproducibility metadata."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from .registry import LabRegistry
from .scheduler import SeasonSchedule


def _git_commit(repo_root: Path) -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def create_manifest(season_dir: str | Path, registry: LabRegistry, schedule: SeasonSchedule, repo_root: str | Path, prompt_version: str = "v1") -> dict:
    target = Path(season_dir)
    target.mkdir(parents=True, exist_ok=True)
    labs = [lab.__dict__ for lab in registry.all()]
    labs_hash = hashlib.sha256(json.dumps(labs, sort_keys=True, default=str).encode()).hexdigest()
    manifest = {
        "season": target.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(Path(repo_root)),
        "scheduler_seed": schedule.scheduler_seed,
        "labs_config_hash": labs_hash,
        "prompt_version": prompt_version,
        "engine_version": "upstream-diplomacy",
        "games": schedule.games,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
