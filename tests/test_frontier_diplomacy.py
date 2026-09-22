import json
import tempfile
import unittest
from pathlib import Path

from frontier_diplomacy.registry import LabConfig, LabRegistry
from frontier_diplomacy.scheduler import balance_report, generate_schedule, validate_schedule


def registry(count=10):
    return LabRegistry([LabConfig(f"lab-{i}", f"Lab {i}", "openrouter", f"model-{i}") for i in range(count)])


class RegistryTests(unittest.TestCase):
    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            LabRegistry([LabConfig("same", "A", "x", "a"), LabConfig("same", "B", "x", "b")])

    def test_enabled_filter(self):
        labs = LabRegistry([LabConfig("on", "On", "x", "a"), LabConfig("off", "Off", "x", "b", False)])
        self.assertEqual(["on"], [lab.id for lab in labs.all(enabled_only=True)])

    def test_provider_routing_id(self):
        self.assertEqual("gemini:flash", LabConfig("google", "Google", "google", "flash").upstream_model_id())
        self.assertEqual("xai:grok-4", LabConfig("xai", "xAI", "xai", "grok-4").upstream_model_id())
        self.assertEqual("openrouter:llama:free", LabConfig("meta", "Meta", "openrouter", "llama:free").upstream_model_id())


class SchedulerTests(unittest.TestCase):
    def test_shape_and_determinism(self):
        first = generate_schedule(registry(), 20, 42)
        second = generate_schedule(registry(), 20, 42)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual([], validate_schedule(first, [lab.id for lab in registry().all()]))
        for game in first.assignments:
            self.assertEqual(7, len(game.assignments))
            self.assertEqual(7, len(set(game.assignments.values())))
        report = balance_report(first)
        appearance_range = report["ranges"]["lab_appearances"]
        self.assertLessEqual(appearance_range[1] - appearance_range[0], 2)

    def test_different_seed_changes_schedule(self):
        self.assertNotEqual(generate_schedule(registry(), 4, 1).to_dict(), generate_schedule(registry(), 4, 2).to_dict())

    def test_schedule_writes_json(self):
        schedule = generate_schedule(registry(), 2, 7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            schedule.write(path)
            self.assertEqual(2, json.loads(path.read_text())["games"])

    def test_complete_seven_game_block_rotates_every_power(self):
        seven = registry(7)
        schedule = generate_schedule(seven, 7, 5)
        report = balance_report(schedule)
        for model in (lab.id for lab in seven.all()):
            self.assertEqual(7, report["appearances_by_lab"][model])
            self.assertEqual(1, len(set(report["power_assignments_by_lab"][model].values())))


if __name__ == "__main__":
    unittest.main()
