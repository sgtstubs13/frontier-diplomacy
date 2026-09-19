import json
import tempfile
import unittest
from pathlib import Path

from frontier_diplomacy.registry import LabConfig, LabRegistry
from frontier_diplomacy.scheduler import generate_schedule, validate_schedule


def registry(count=10):
    return LabRegistry([LabConfig(f"lab-{i}", f"Lab {i}", "openrouter", f"model-{i}") for i in range(count)])


class RegistryTests(unittest.TestCase):
    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            LabRegistry([LabConfig("same", "A", "x", "a"), LabConfig("same", "B", "x", "b")])

    def test_enabled_filter(self):
        labs = LabRegistry([LabConfig("on", "On", "x", "a"), LabConfig("off", "Off", "x", "b", False)])
        self.assertEqual(["on"], [lab.id for lab in labs.all(enabled_only=True)])


class SchedulerTests(unittest.TestCase):
    def test_shape_and_determinism(self):
        first = generate_schedule(registry(), 20, 42)
        second = generate_schedule(registry(), 20, 42)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual([], validate_schedule(first, [lab.id for lab in registry().all()]))
        for game in first.assignments:
            self.assertEqual(7, len(game.assignments))
            self.assertEqual(7, len(set(game.assignments.values())))

    def test_different_seed_changes_schedule(self):
        self.assertNotEqual(generate_schedule(registry(), 4, 1).to_dict(), generate_schedule(registry(), 4, 2).to_dict())

    def test_schedule_writes_json(self):
        schedule = generate_schedule(registry(), 2, 7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            schedule.write(path)
            self.assertEqual(2, json.loads(path.read_text())["games"])


if __name__ == "__main__":
    unittest.main()
