"""Command line entrypoint for the league orchestration layer."""

import argparse
import json
from pathlib import Path

from .registry import LabRegistry
from .runner import SeasonRunner, load_schedule
from .analytics import analyze_season
from .doctor import check_registry
from .scheduler import GameAssignment, SeasonSchedule, balance_report, generate_schedule, validate_schedule
from .server import serve
from .accounting import CostLedger, PriceSnapshot
from decimal import Decimal


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
    run_game.add_argument("--allow-placeholders", action="store_true", help="allow MODEL_ID placeholders (unsafe; normally use --dry-run)")

    run_season = subparsers.add_parser("run-season", help="run or resume all scheduled games")
    run_season.add_argument("--schedule", required=True)
    run_season.add_argument("--season-dir", required=True)
    run_season.add_argument("--repo-root", default=".")
    run_season.add_argument("--config", default="config/labs.yaml")
    run_season.add_argument("--dry-run", action="store_true")
    run_season.add_argument("--force", action="store_true")
    run_season.add_argument("--allow-placeholders", action="store_true", help="allow MODEL_ID placeholders (unsafe; normally use --dry-run)")

    analyze = subparsers.add_parser("analyze", help="calculate transparent standings from completed artifacts")
    analyze.add_argument("--season-dir", required=True)
    analyze.add_argument("--output")

    doctor = subparsers.add_parser("doctor", help="check lab models, providers, and optional API keys")
    doctor.add_argument("--config", default="config/labs.yaml")
    doctor.add_argument("--require-keys", action="store_true")
    dashboard = subparsers.add_parser("dashboard", help="start the local Frontier Diplomacy dashboard API")
    dashboard.add_argument("--config", default="config/labs.yaml")
    dashboard.add_argument("--port", type=int, default=8743)
    price = subparsers.add_parser("price", help="add a versioned USD-per-million-token price card")
    price.add_argument("--ledger", default="data/frontier_diplomacy_costs.sqlite")
    price.add_argument("--model", required=True)
    price.add_argument("--provider", required=True)
    price.add_argument("--input", type=Decimal, required=True, dest="input_rate")
    price.add_argument("--output", type=Decimal, required=True, dest="output_rate")
    price.add_argument("--cached-input", type=Decimal)
    price.add_argument("--cache-write", type=Decimal)
    price.add_argument("--source", default="manual")
    args = parser.parse_args()
    if args.command == "dashboard":
        serve(args.config, args.port)
        return
    if args.command == "price":
        stored = CostLedger(args.ledger).add_price(PriceSnapshot(
            args.model, args.provider, args.input_rate, args.output_rate,
            args.cached_input, args.cache_write, args.source,
        ))
        print(f"stored price snapshot {stored.id} for {stored.provider}:{stored.model_id}")
        return
    if args.command == "analyze":
        result = analyze_season(args.season_dir)
        rendered = json.dumps(result, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return

    registry = LabRegistry.from_file(args.config)
    if args.command == "doctor":
        issues = check_registry(registry, require_keys=args.require_keys)
        if issues:
            print("\n".join(issues))
            raise SystemExit(1)
        print("configuration passed preflight")
        return
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
        report = balance_report(loaded)
        print(f"lab appearances: {report['ranges']['lab_appearances'][0]}-{report['ranges']['lab_appearances'][1]}")
        print(f"lab/power cells: {report['ranges']['lab_power_assignments'][0]}-{report['ranges']['lab_power_assignments'][1]}")
        print(f"pairwise encounters: {report['pairwise_encounters']['min']}-{report['pairwise_encounters']['max']}")
    else:
        schedule = load_schedule(args.schedule)
        runner = SeasonRunner(registry, schedule, args.season_dir, args.repo_root)
        if args.command == "run-game":
            result = runner.run_game(args.game, dry_run=args.dry_run, force=args.force, allow_placeholders=args.allow_placeholders)
            print(f"{result.game_id}: {result.status}")
        else:
            results = runner.run_season(dry_run=args.dry_run, force=args.force, allow_placeholders=args.allow_placeholders)
            print(f"season: {len(results)} games processed")


if __name__ == "__main__":
    main()
