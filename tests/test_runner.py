import tempfile
import unittest
from pathlib import Path

from frontier_diplomacy.registry import LabConfig, LabRegistry
from frontier_diplomacy.runner import SeasonRunner
from frontier_diplomacy.scheduler import generate_schedule


class RunnerTests(unittest.TestCase):
    def setUp(self):
        registry = LabRegistry([LabConfig(f"lab-{i}", f"Lab {i}", "provider", f"model-{i}") for i in range(7)])
        self.schedule = generate_schedule(registry, 1, 9)
        self.registry = registry

    def test_command_uses_power_order_and_models(self):
        runner = SeasonRunner(self.registry, self.schedule, "/tmp/season", "/repo")
        command = runner.command_for(self.schedule.assignments[0])
        self.assertIn("--models", command)
        expected = ",".join(
            self.registry.get(self.schedule.assignments[0].assignments[power]).upstream_model_id()
            for power in ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY")
        )
        self.assertEqual(expected, command[command.index("--models") + 1])

    def test_dry_run_writes_metadata_without_calling_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = SeasonRunner(self.registry, self.schedule, directory, "/repo")
            result = runner.run_game("league-0001", dry_run=True)
            self.assertEqual("planned", result.status)
            self.assertTrue((Path(directory) / "games/league-0001/metadata.json").exists())


if __name__ == "__main__":
    unittest.main()
