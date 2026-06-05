import unittest

from aleatrix_solver.yahtzee_ai import YahtzeeAI
from yahtzee_simulator import (
    compare_strategies_against_opponents,
    compare_strategies,
    estimate_simulated_opponent_score,
    parse_depth_specs,
    parse_risk_specs,
    play_solo_game,
    resolve_target_score,
    run_simulation,
    summarize_match_results,
)


class YahtzeeSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = YahtzeeAI()

    def test_play_solo_game_completes_scorecard(self):
        result = play_solo_game(self.ai, seed=11)

        self.assertEqual(len(result["turns"]), 13)
        self.assertEqual(len(result["scored_categories"]), 13)
        self.assertEqual(len(set(result["scored_categories"])), 13)
        self.assertEqual(result["final_score"], result["upper_score"] + result["lower_score"] + result["bonus_score"])

    def test_play_solo_game_uses_target_score_for_risk_pressure(self):
        result = play_solo_game(self.ai, seed=11, target_score=350)
        risk_levels = [
            decision["risk_level"]
            for turn in result["turns"]
            for decision in turn["decisions"]
        ]

        self.assertIn(1.0, risk_levels)

    def test_play_solo_game_uses_projected_opponent_pressure(self):
        result = play_solo_game(self.ai, seed=11, opponent_score=120, use_opponent_projection=True)
        risk_levels = [
            decision["risk_level"]
            for turn in result["turns"]
            for decision in turn["decisions"]
        ]

        self.assertIn(1.0, risk_levels)

    def test_estimate_simulated_opponent_score_scales_by_completed_turns(self):
        self.assertEqual(estimate_simulated_opponent_score(260, 13), 0)
        self.assertEqual(estimate_simulated_opponent_score(260, 7), 120)
        self.assertEqual(estimate_simulated_opponent_score(260, 0), 260)

    def test_play_solo_game_live_like_projection_uses_fixed_target_and_simulated_current_score(self):
        result = play_solo_game(
            self.ai,
            seed=11,
            target_score=267,
            simulated_opponent_final_score=260,
            use_opponent_projection=True,
        )
        first_decision = result["turns"][0]["decisions"][0]
        later_decisions = [
            decision
            for turn in result["turns"]
            for decision in turn["decisions"]
            if decision["opponent_score"] > 0
        ]

        self.assertEqual(first_decision["opponent_score"], 0)
        self.assertEqual(result["target_score"], 267)
        self.assertTrue(later_decisions)
        self.assertTrue(all(decision["projected_opponent_score"] is not None for decision in later_decisions))

    def test_play_solo_game_passes_match_target_and_total_to_tablebase_ai(self):
        class SpyTablebaseAI:
            is_tablebase_ai = True

            def __init__(self):
                self.calls = []

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                target_final_score=None,
                player_total_score=None,
                risk_level=None,
            ):
                self.calls.append({
                    "target_final_score": target_final_score,
                    "player_total_score": player_total_score,
                    "risk_level": risk_level,
                })
                category = "chance" if "chance" in open_categories else open_categories[0]
                return "score", category, 0.5, {}

        ai = SpyTablebaseAI()

        play_solo_game(ai, seed=11, target_score=240)

        self.assertTrue(ai.calls)
        self.assertTrue(all(call["target_final_score"] == 250 for call in ai.calls))
        self.assertTrue(all(call["risk_level"] is None for call in ai.calls))
        self.assertEqual(ai.calls[0]["player_total_score"], 0)
        self.assertTrue(any((call["player_total_score"] or 0) > 0 for call in ai.calls[1:]))

    def test_tablebase_simulation_stabilizes_projected_opponent_target(self):
        class SpyTablebaseAI:
            is_tablebase_ai = True

            def __init__(self):
                self.calls = []

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                target_final_score=None,
                player_total_score=None,
            ):
                self.calls.append({
                    "open_count": len(open_categories),
                    "target": target_final_score,
                })
                category = "chance" if "chance" in open_categories else open_categories[0]
                return "score", category, 0.5, {}

        ai = SpyTablebaseAI()

        play_solo_game(
            ai,
            seed=11,
            target_score=240,
            simulated_opponent_final_score=300,
            use_opponent_projection=True,
            projection_model={12: (280.2, 10.0), 11: (282.1, 10.0), 4: (460.0, 10.0)},
        )

        early_targets = [
            call["target"]
            for call in ai.calls
            if call["open_count"] > 4
        ]
        endgame_targets = [
            call["target"]
            for call in ai.calls
            if call["open_count"] <= 4
        ]

        self.assertTrue(early_targets)
        self.assertTrue(all(target == 250 for target in early_targets))
        self.assertIn(315, endgame_targets)

    def test_tablebase_simulation_uses_score_fallback_when_win_probability_is_zero(self):
        class ZeroWinTablebaseAI:
            is_tablebase_ai = True

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                target_final_score=None,
                player_total_score=None,
            ):
                return "score", "ones", 0.0, {"ones": 1}

        class ScoreFallbackAI:
            def __init__(self):
                self.calls = []
                self.fallback_solver_name = "Optuna Expectiminimax"

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                risk_level=0.0,
            ):
                self.calls.append({
                    "risk_level": risk_level,
                    "open_categories": list(open_categories),
                })
                category = "chance" if "chance" in open_categories else open_categories[0]
                return "score", category, 22.0, {category: 22}

        fallback_ai = ScoreFallbackAI()

        result = play_solo_game(
            ZeroWinTablebaseAI(),
            seed=11,
            target_score=315,
            score_fallback_ai=fallback_ai,
        )

        first_decision = result["turns"][0]["decisions"][0]
        self.assertEqual(first_decision["target"], "chance")
        self.assertTrue(first_decision["score_fallback_used"])
        self.assertEqual(first_decision["fallback_solver"], "Optuna Expectiminimax")
        self.assertEqual(first_decision["tablebase_win_probability"], 0.0)
        self.assertEqual(fallback_ai.calls[0]["risk_level"], 0.0)

    def test_tablebase_simulation_uses_score_fallback_when_endgame_target_is_high(self):
        class HighWinTablebaseAI:
            is_tablebase_ai = True

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                target_final_score=None,
                player_total_score=None,
            ):
                category = "chance" if "chance" in open_categories else open_categories[0]
                return "score", category, 0.8, {category: 22}

        class ScoreFallbackAI:
            def __init__(self):
                self.calls = []
                self.fallback_solver_name = "Optuna Expectiminimax"

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                risk_level=0.0,
            ):
                self.calls.append({
                    "risk_level": risk_level,
                    "open_count": len(open_categories),
                })
                category = "chance" if "chance" in open_categories else open_categories[0]
                return "score", category, 22.0, {category: 22}

        fallback_ai = ScoreFallbackAI()

        result = play_solo_game(
            HighWinTablebaseAI(),
            seed=11,
            target_score=315,
            score_fallback_ai=fallback_ai,
            tablebase_fallback_threshold=0.00001,
        )

        fallback_decisions = [
            decision
            for turn in result["turns"]
            for decision in turn["decisions"]
            if decision["score_fallback_used"]
        ]

        self.assertTrue(fallback_decisions)
        self.assertTrue(any(decision["tablebase_target_score"] >= 260 for decision in fallback_decisions))
        self.assertEqual(fallback_ai.calls[0]["risk_level"], 0.0)

    def test_tablebase_simulation_converts_keep_all_to_scoring_move(self):
        class KeepAllThenScoreAI:
            is_tablebase_ai = True

            def __init__(self):
                self.rolls_left_calls = []

            def get_optimal_move(
                self,
                open_categories,
                current_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored=False,
                target_final_score=None,
                player_total_score=None,
            ):
                self.rolls_left_calls.append(rolls_left)
                category = "chance" if "chance" in open_categories else open_categories[0]
                if rolls_left > 0:
                    return "keep", tuple(sorted(current_dice)), 0.5, {category: 22}
                return "score", category, 0.49, {category: 22}

        ai = KeepAllThenScoreAI()

        result = play_solo_game(ai, seed=11, target_score=250)

        first_decision = result["turns"][0]["decisions"][0]
        self.assertEqual(first_decision["action"], "score")
        self.assertTrue(first_decision["full_keep_converted"])
        self.assertEqual(ai.rolls_left_calls[:2], [2, 0])

    def test_seeded_simulation_is_repeatable(self):
        first = run_simulation(self.ai, games=2, seed=17, target_score=275)
        second = run_simulation(self.ai, games=2, seed=17, target_score=275)

        self.assertEqual(first["scores"], second["scores"])
        self.assertEqual(first["games"], 2)
        self.assertEqual(first["target_score"], 275)
        self.assertEqual(first["average_score"], sum(first["scores"]) / 2)

    def test_compare_strategies_reuses_same_game_seeds(self):
        limited_ai = YahtzeeAI(exact_category_limit=3, lower_only_exact_category_limit=4)
        comparison = compare_strategies(
            [("default", self.ai), ("limited", limited_ai)],
            games=1,
            seed=23,
        )
        default_run = run_simulation(self.ai, games=1, seed=23)

        self.assertEqual(set(comparison), {"default", "limited"})
        self.assertEqual(comparison["default"]["scores"], default_run["scores"])
        self.assertEqual(comparison["limited"]["games"], 1)

    def test_summarize_match_results_counts_wins_losses_and_ties(self):
        summary = summarize_match_results(
            scores=[240, 210, 230, 199],
            opponent_scores=[220, 220, 230, 200],
        )

        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["losses"], 2)
        self.assertEqual(summary["ties"], 1)
        self.assertEqual(summary["win_rate"], 0.25)
        self.assertEqual(summary["non_loss_rate"], 0.5)

    def test_parse_depth_specs_accepts_exact_and_lower_limits(self):
        self.assertEqual(parse_depth_specs("4:5,3:4"), [(4, 5), (3, 4)])

    def test_parse_risk_specs_accepts_float_values(self):
        self.assertEqual(parse_risk_specs("0.5,1,2.0"), [0.5, 1.0, 2.0])

    def test_compare_strategies_passes_target_score(self):
        comparison = compare_strategies(
            [("default", self.ai)],
            games=1,
            seed=31,
            target_score=260,
        )

        self.assertEqual(comparison["default"]["target_score"], 260)

    def test_compare_strategies_against_opponents_adds_match_summary(self):
        comparison = compare_strategies_against_opponents(
            [("default", self.ai)],
            opponent_scores=[200, 260],
            games=3,
            seed=31,
            validation_mode="oracle-target",
        )

        self.assertEqual(comparison["default"]["opponent_scores"], [200, 260, 200])
        self.assertIn("match_summary", comparison["default"])
        self.assertEqual(comparison["default"]["match_summary"]["games"], 3)

    def test_compare_strategies_against_opponents_supports_live_like_validation(self):
        comparison = compare_strategies_against_opponents(
            [("default", self.ai)],
            opponent_scores=[200, 260],
            games=2,
            seed=31,
            validation_mode="live-like",
            target_score=267,
            projection_model={13: (286.0, 36.0), 12: (264.0, 34.0)},
        )

        self.assertEqual(comparison["default"]["validation_mode"], "live-like")
        self.assertEqual(comparison["default"]["target_score"], 267)
        self.assertEqual(comparison["default"]["opponent_scores"], [200, 260])

    def test_resolve_target_score_prefers_explicit_value(self):
        self.assertEqual(resolve_target_score(240, "missing-history-file.jsonl"), 240)


if __name__ == "__main__":
    unittest.main()
