"""Command line entrypoint for the league orchestration layer."""

import argparse
import json
from pathlib import Path

from .registry import LabRegistry
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
    args = parser.parse_args()
    registry = LabRegistry.from_file(args.config)
    if args.command == "labs":
        for lab in registry.all():
            state = "enabled" if lab.enabled else "disabled"
            print(f"{lab.id}\t{lab.display_name}\t{lab.provider}\t{lab.model}\t{state}")
    elif args.command == "schedule":
        generated = generate_schedule(registry, args.games, args.seed)
        generated.write(args.output)
        print(f"wrote {args.games} games to {args.output}")
    else:
        data = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
        loaded = SeasonSchedule(data["games"], data["scheduler_seed"], tuple(GameAssignment(**item) for item in data["assignments"]))
        errors = validate_schedule(loaded, (lab.id for lab in registry.all()))
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print(f"valid: {len(loaded.assignments)} games")


if __name__ == "__main__":
    main()
