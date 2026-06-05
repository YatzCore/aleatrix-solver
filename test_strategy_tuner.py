import unittest

from strategy_tuner import build_strategy_grid, config_from_strategy_name, rank_strategy_summaries


class StrategyTunerTests(unittest.TestCase):
    def test_rank_strategy_summaries_prefers_target_win_rate(self):
        comparison = {
            "risk1": {
                "games": 3,
                "target_score": 250,
                "scores": [260, 240, 245],
                "average_score": 248.33,
                "min_score": 240,
                "max_score": 260,
            },
            "risk2": {
                "games": 3,
                "target_score": 250,
                "scores": [251, 252, 220],
                "average_score": 241.0,
                "min_score": 220,
                "max_score": 252,
            },
        }

        ranked = rank_strategy_summaries(comparison, objective="target-win-rate")

        self.assertEqual(ranked[0]["name"], "risk2")
        self.assertEqual(ranked[0]["target_win_rate"], 2 / 3)

    def test_rank_strategy_summaries_prefers_opponent_win_rate_when_available(self):
        comparison = {
            "high_avg": {
                "games": 2,
                "target_score": 251,
                "scores": [300, 100],
                "average_score": 250.0,
                "min_score": 100,
                "max_score": 300,
                "match_summary": {"games": 2, "wins": 1, "losses": 1, "ties": 0, "win_rate": 0.5},
            },
            "wins_more": {
                "games": 2,
                "target_score": 251,
                "scores": [252, 252],
                "average_score": 252.0,
                "min_score": 252,
                "max_score": 252,
                "match_summary": {"games": 2, "wins": 2, "losses": 0, "ties": 0, "win_rate": 1.0},
            },
        }

        ranked = rank_strategy_summaries(comparison, objective="opponent-win-rate")

        self.assertEqual(ranked[0]["name"], "wins_more")
        self.assertEqual(ranked[0]["opponent_win_rate"], 1.0)

    def test_rank_strategy_summaries_can_prefer_average_score(self):
        comparison = {
            "steady": {
                "games": 2,
                "target_score": None,
                "scores": [240, 240],
                "average_score": 240.0,
                "min_score": 240,
                "max_score": 240,
            },
            "high_avg": {
                "games": 2,
                "target_score": None,
                "scores": [280, 230],
                "average_score": 255.0,
                "min_score": 230,
                "max_score": 280,
            },
        }

        ranked = rank_strategy_summaries(comparison, objective="average-score")

        self.assertEqual(ranked[0]["name"], "high_avg")

    def test_build_strategy_grid_names_depth_and_risk_settings(self):
        strategies = build_strategy_grid(depths=[(4, 5), (3, 4)], risks=[1.0, 2.0])

        self.assertEqual(
            [name for name, _ in strategies],
            [
                "dp4_lower5_risk1",
                "dp4_lower5_risk2",
                "dp3_lower4_risk1",
                "dp3_lower4_risk2",
            ],
        )

    def test_config_from_strategy_name_parses_tuned_settings(self):
        config = config_from_strategy_name("dp4_lower5_risk1.5")

        self.assertEqual(config["exact_category_limit"], 4)
        self.assertEqual(config["lower_only_exact_category_limit"], 5)
        self.assertEqual(config["risk_multiplier"], 1.5)


if __name__ == "__main__":
    unittest.main()
