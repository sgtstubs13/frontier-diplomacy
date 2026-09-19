import json
import tempfile
import unittest
from pathlib import Path

from frontier_diplomacy.analytics import analyze_season


class AnalyticsTests(unittest.TestCase):
    def test_standings_and_country_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory) / "games/league-0001"
            game.mkdir(parents=True)
            (game / "metadata.json").write_text(json.dumps({"game_id": "league-0001", "assignments": {
                "FRANCE": {"lab": "openai"}, "GERMANY": {"lab": "anthropic"}}}))
            (game / "summary.json").write_text(json.dumps({"final_supply_centers": {"FRANCE": 8, "GERMANY": 4}, "solo_winner": "FRANCE"}))
            result = analyze_season(directory)
            self.assertEqual(1, result["standings"]["openai"]["games"])
            self.assertEqual(8.0, result["country_bias"]["openai"]["FRANCE"]["avg_final_sc"])
            self.assertEqual(1, result["standings"]["openai"]["solo_wins"])


if __name__ == "__main__":
    unittest.main()
