import json
import tempfile
import unittest
from pathlib import Path

from match_strategy import choose_risk_level
from opponent_history import build_opponent_profile, extract_match_scores, fit_opponent_projection_model


class OpponentHistoryTests(unittest.TestCase):
    def test_extract_match_scores_uses_best_opponent_score(self):
        records = [
            {"player_id": "0", "final_scores": {"0": 240, "1": 225}},
            {"player_id": "1", "final_scores": {"0": 260, "1": 210, "2": 205}},
        ]

        scores = extract_match_scores(records)

        self.assertEqual(scores["player_scores"], [240, 210])
        self.assertEqual(scores["opponent_scores"], [225, 260])

    def test_extract_match_scores_filters_conceded_or_dirty_games(self):
        records = [
            {"player_id": "0", "final_scores": {"0": 240, "1": 225}},
            {"player_id": "0", "final_scores": {"0": 270, "1": 55}},
            {"player_id": "0", "final_scores": {"0": 0, "1": 260}},
        ]

        scores = extract_match_scores(records)

        self.assertEqual(scores["player_scores"], [240])
        self.assertEqual(scores["opponent_scores"], [225])
        self.assertEqual(scores["skipped_games"], 2)

    def test_projection_model_ignores_legacy_projected_opponent_scores(self):
        records = [
            {
                "player_id": "0",
                "final_scores": {"0": 240, "1": 260},
                "turns": [
                    {
                        "open_categories": ["ones"] * 5,
                        "projected_opponent_score": 999,
                    }
                ],
            }
        ]

        model = fit_opponent_projection_model(records)

        self.assertEqual(model[5], (110.0, 10.0 * (5 ** 0.5)))

    def test_projection_model_uses_raw_opponent_score_samples(self):
        records = [
            {
                "player_id": "0",
                "final_scores": {"0": 240, "1": 260},
                "turns": [
                    {
                        "open_categories": ["ones"] * 5,
                        "opponent_score": 150,
                    }
                ],
            }
        ]

        model = fit_opponent_projection_model(records)

        self.assertAlmostEqual(model[5][0], 110.0)

    def test_projection_model_ignores_zero_live_opponent_score_samples(self):
        records = [
            {
                "player_id": "0",
                "final_scores": {"0": 240, "1": 260},
                "turns": [
                    {
                        "open_categories": ["fives", "threeofakind"],
                        "opponent_score": 0,
                    },
                    {
                        "open_categories": ["fives", "threeofakind"],
                        "opponent_score": 220,
                    },
                ],
            }
        ]

        model = fit_opponent_projection_model(records)

        self.assertAlmostEqual(model[2][0], 42.0)

    def test_build_opponent_profile_tolerates_dirty_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "game_history.jsonl"
            path.write_text(
                "\n".join([
                    json.dumps({"player_id": "0", "final_scores": {"0": 240, "1": 225}}),
                    "not json",
                    json.dumps({"player_id": "1", "final_scores": {"0": 260, "1": 210}}),
                ]),
                encoding="utf-8",
            )

            profile = build_opponent_profile(path)

        self.assertEqual(profile["games"], 2)
        self.assertEqual(profile["skipped_games"], 0)
        self.assertEqual(profile["opponent_scores"], [225, 260])
        self.assertEqual(profile["target_score"], 261)

    def test_build_opponent_profile_handles_missing_history(self):
        profile = build_opponent_profile("missing-history-file.jsonl")

        self.assertEqual(profile["games"], 0)
        self.assertIsNone(profile["target_score"])

    def test_build_opponent_profile_exposes_train_holdout_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "game_history.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps({"player_id": "0", "final_scores": {"0": 240, "1": score}})
                    for score in [200, 210, 220, 230, 240]
                ),
                encoding="utf-8",
            )

            profile = build_opponent_profile(path, holdout_fraction=0.4)

        self.assertEqual(profile["training_opponent_scores"], [200, 210, 220])
        self.assertEqual(profile["holdout_opponent_scores"], [230, 240])

    def test_choose_risk_level_uses_target_score_when_live_score_is_low(self):
        risk = choose_risk_level(
            player_score=140,
            opponent_score=0,
            open_category_count=4,
            target_score=250,
        )

        self.assertEqual(risk, 1.0)


if __name__ == "__main__":
    unittest.main()
