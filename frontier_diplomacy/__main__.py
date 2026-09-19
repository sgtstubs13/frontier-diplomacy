"""Command line entrypoint for the league orchestration layer."""

import argparse
import json
from pathlib import Path

from .registry import LabRegistry
from .runner import SeasonRunner, load_schedule
from .analytics import analyze_season
from .scheduler import GameAssignment, SeasonSchedule, generate_schedule, validate_schedule


def main() -> None:
    parser = argparse.ArgumentParser(prog="frontier-diplomacy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    labs = subparsers.add_parser("labs", help="list configured labs")
    labs.add_argument("--config", default="config/labs.yaml")
    schedule = subparsers.add_parser("schedule", help="generate a balanced season schedule")
    schedule.add_argument("--config", default="config/labs.yaml")
    schedule.add_argument("--games", type=int, required=True)
    schedule.add_argument("--seed", type=int, required=True)
    schedule.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate-schedule", help="validate a saved schedule")
    validate.add_argument("schedule")
    validate.add_argument("--config", default="config/labs.yaml")

    run_game = subparsers.add_parser("run-game", help="run one scheduled game through the upstream engine")
    run_game.add_argument("--schedule", required=True)
    run_game.add_argument("--game", required=True)
    run_game.add_argument("--season-dir", required=True)
    run_game.add_argument("--repo-root", default=".")
    run_game.add_argument("--config", default="config/labs.yaml")
    run_game.add_argument("--dry-run", action="store_true")
    run_game.add_argument("--force", action="store_true")

    run_season = subparsers.add_parser("run-season", help="run or resume all scheduled games")
    run_season.add_argument("--schedule", required=True)
    run_season.add_argument("--season-dir", required=True)
    run_season.add_argument("--repo-root", default=".")
    run_season.add_argument("--config", default="config/labs.yaml")
    run_season.add_argument("--dry-run", action="store_true")
    run_season.add_argument("--force", action="store_true")

    analyze = subparsers.add_parser("analyze", help="calculate transparent standings from completed artifacts")
    analyze.add_argument("--season-dir", required=True)
    analyze.add_argument("--output")
    args = parser.parse_args()
    if args.command == "analyze":
        result = analyze_season(args.season_dir)
        rendered = json.dumps(result, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return

    registry = LabRegistry.from_file(args.config)
    if args.command == "labs":
        for lab in registry.all():
            state = "enabled" if lab.enabled else "disabled"
            print(f"{lab.id}\t{lab.display_name}\t{lab.provider}\t{lab.model}\t{state}")
    elif args.command == "schedule":
        generated = generate_schedule(registry, args.games, args.seed)
        generated.write(args.output)
        print(f"wrote {args.games} games to {args.output}")
    elif args.command == "validate-schedule":
        data = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
        loaded = SeasonSchedule(data["games"], data["scheduler_seed"], tuple(GameAssignment(**item) for item in data["assignments"]))
        errors = validate_schedule(loaded, (lab.id for lab in registry.all()))
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print(f"valid: {len(loaded.assignments)} games")
    else:
        schedule = load_schedule(args.schedule)
        runner = SeasonRunner(registry, schedule, args.season_dir, args.repo_root)
        if args.command == "run-game":
            result = runner.run_game(args.game, dry_run=args.dry_run, force=args.force)
            print(f"{result.game_id}: {result.status}")
        else:
            results = runner.run_season(dry_run=args.dry_run, force=args.force)
            print(f"season: {len(results)} games processed")


if __name__ == "__main__":
    main()
