import unittest

from frontier_diplomacy.doctor import check_registry
from frontier_diplomacy.registry import LabConfig, LabRegistry


class DoctorTests(unittest.TestCase):
    def test_placeholder_is_reported(self):
        registry = LabRegistry([LabConfig("openai", "OpenAI", "openai", "MODEL_ID")])
        self.assertTrue(any("placeholder" in issue for issue in check_registry(registry)))

    def test_unknown_provider_is_reported(self):
        registry = LabRegistry([LabConfig("other", "Other", "madeup", "model")])
        self.assertTrue(any("unsupported provider" in issue for issue in check_registry(registry)))


if __name__ == "__main__":
    unittest.main()
