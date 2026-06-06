import unittest
import os
from unittest.mock import patch
from aleatrix_solver.yahtzee_ai import YahtzeeAI, CATEGORIES
from yahtzee_bot import TablebaseAI, is_tablebase_ready
from yahtzee_simulator import play_solo_game


class UnifiedLivePathUnitTests(unittest.TestCase):
    class FakeTablebaseAI:
        def __init__(self, move_batches):
            self.move_batches = list(move_batches)

        def get_ranked_moves(self, **kwargs):
            return [dict(move) for move in self.move_batches.pop(0)]

    class FakeScoreAI:
        def __init__(self, values):
            self.values = values

        def evaluate_action_ev(self, action_type, target_idx, **kwargs):
            return self.values.get((action_type, target_idx), 1.0)

    def test_unified_is_default_solver_mode(self):
        from yahtzee_bot import parse_args

        with patch("sys.argv", ["yahtzee_bot.py"]):
            args = parse_args()

        self.assertEqual(args.solver_mode, "unified")

    def test_live_unified_move_separates_wp_ev_score_and_latency(self):
        from yahtzee_bot import choose_unified_move

        tablebase_ai = self.FakeTablebaseAI([[
            {"action_type": 0, "target_idx": 12, "wp": 0.8},
            {"action_type": 0, "target_idx": 0, "wp": 0.79},
        ]])
        score_ai = self.FakeScoreAI({
            (0, 12): 30.0,
            (0, 0): 5.0,
        })

        move = choose_unified_move(
            tablebase_ai=tablebase_ai,
            score_fallback_ai=score_ai,
            open_categories=["ones", "chance"],
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=0,
            upper_sum=0,
            yahtzee_scored=False,
            target_final_score=260,
            player_total_score=0,
            epsilon="0.01",
        )

        self.assertEqual(move["action"], "score")
        self.assertEqual(move["target"], "chance")
        self.assertEqual(move["utility"], 0.8)
        self.assertEqual(move["chosen_action_ev"], 30.0)
        self.assertEqual(move["evs"]["chance"], 21)
        self.assertGreater(move["decision_latency_seconds"], 0.0)
        self.assertGreaterEqual(move["t_lookup"], 0.0)
        self.assertLessEqual(move["t_lookup"], move["decision_latency_seconds"])
        self.assertNotEqual(move["t_lookup"], 1)
        self.assertFalse(move["score_fallback_used"])
        self.assertFalse(move["wp_changed"])
        self.assertIsNone(move["fallback_solver"])

    def test_keep_all_conversion_preserves_original_epsilon_budget(self):
        from yahtzee_bot import choose_unified_move

        tablebase_ai = self.FakeTablebaseAI([
            [
                {"action_type": 1, "target_idx": 1, "wp": 0.9},
                {"action_type": 1, "target_idx": 31, "wp": 0.895},
            ],
            [
                {"action_type": 0, "target_idx": 12, "wp": 0.895},
                {"action_type": 0, "target_idx": 0, "wp": 0.887},
            ],
        ])
        score_ai = self.FakeScoreAI({
            (1, 1): 1.0,
            (1, 31): 100.0,
            (0, 12): 10.0,
            (0, 0): 100.0,
        })

        move = choose_unified_move(
            tablebase_ai=tablebase_ai,
            score_fallback_ai=score_ai,
            open_categories=["ones", "chance"],
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            target_final_score=260,
            player_total_score=0,
            epsilon="0.01",
        )

        self.assertEqual(move["action"], "score")
        self.assertEqual(move["target"], "chance")
        self.assertEqual(move["utility"], 0.895)
        self.assertAlmostEqual(move["wp_drop"], 0.005)
        self.assertLessEqual(move["wp_drop"], 0.01)

    def test_simulator_keep_all_conversion_preserves_original_epsilon_budget(self):
        class FakeSimulationTablebaseAI:
            is_tablebase_ai = True

            def __init__(self):
                self.calls = 0

            def get_ranked_moves(self, open_categories, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return [
                        {"action_type": 1, "target_idx": 1, "wp": 0.9},
                        {"action_type": 1, "target_idx": 31, "wp": 0.895},
                    ]
                if self.calls == 2:
                    return [
                        {"action_type": 0, "target_idx": 12, "wp": 0.895},
                        {"action_type": 0, "target_idx": 0, "wp": 0.887},
                    ]
                category_idx = CATEGORIES.index(open_categories[0])
                return [{"action_type": 0, "target_idx": category_idx, "wp": 0.5}]

        score_ai = self.FakeScoreAI({
            (1, 1): 1.0,
            (1, 31): 100.0,
            (0, 12): 10.0,
            (0, 0): 100.0,
        })

        result = play_solo_game(
            FakeSimulationTablebaseAI(),
            seed=1,
            target_score=260,
            score_fallback_ai=score_ai,
            epsilon="0.01",
            unified_mode=True,
        )

        first_decision = result["turns"][0]["decisions"][0]
        self.assertEqual(first_decision["target"], "chance")
        self.assertAlmostEqual(first_decision["wp_drop"], 0.005)
        self.assertLessEqual(first_decision["wp_drop"], 0.01)

    def test_simulator_keeps_full_hold_when_no_score_conversion_fits_epsilon(self):
        class FakeSimulationTablebaseAI:
            is_tablebase_ai = True

            def __init__(self):
                self.calls = 0

            def get_ranked_moves(self, open_categories, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return [
                        {"action_type": 1, "target_idx": 31, "wp": 0.9},
                        {"action_type": 1, "target_idx": 1, "wp": 0.89},
                    ]
                if self.calls == 2:
                    return [
                        {"action_type": 0, "target_idx": 12, "wp": 0.88},
                        {"action_type": 0, "target_idx": 0, "wp": 0.87},
                    ]
                category_idx = CATEGORIES.index(open_categories[0])
                return [{"action_type": 0, "target_idx": category_idx, "wp": 0.5}]

        score_ai = self.FakeScoreAI({
            (1, 31): 100.0,
            (1, 1): 1.0,
        })

        result = play_solo_game(
            FakeSimulationTablebaseAI(),
            seed=1,
            target_score=260,
            score_fallback_ai=score_ai,
            epsilon="0.01",
            unified_mode=True,
        )

        first_decision = result["turns"][0]["decisions"][0]
        self.assertEqual(first_decision["action"], "keep")
        self.assertEqual(len(first_decision["target"]), 5)
        self.assertFalse(first_decision["full_keep_converted"])
        self.assertAlmostEqual(first_decision["wp_drop"], 0.0)


class UnifiedEvaluatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dll_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "build", "Release", "yahtzee_core.dll"))
        cls.bin_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "tablebase.bin"))

        if not is_tablebase_ready(cls.dll_path, cls.bin_path):
            raise unittest.SkipTest("C++ tablebase is not ready")

        cls.tablebase_ai = TablebaseAI(cls.dll_path, cls.bin_path)
        cls.optuna_ai = YahtzeeAI(verbose=False)

    def test_get_ranked_moves_returns_legal_moves(self):
        moves = self.tablebase_ai.get_ranked_moves(
            open_categories=["ones", "chance"],
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            target_final_score=260,
            player_total_score=0,
        )
        self.assertTrue(len(moves) > 0)
        wps = [m["wp"] for m in moves]
        self.assertEqual(wps, sorted(wps, reverse=True))

    def test_evaluate_action_ev_returns_correct_ev(self):
        ev_score = self.optuna_ai.evaluate_action_ev(
            open_categories=["ones", "chance"],
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            action_type=0, # score
            target_idx=12, # chance
        )
        self.assertTrue(ev_score > 0)

        ev_invalid = self.optuna_ai.evaluate_action_ev(
            open_categories=["ones", "chance"],
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            action_type=0,
            target_idx=11, # yahtzee (not open)
        )
        self.assertEqual(ev_invalid, -999999.0)

    def test_unified_filters_moves_within_epsilon(self):
        result = play_solo_game(
            self.tablebase_ai,
            seed=42,
            target_score=260,
            score_fallback_ai=self.optuna_ai,
            epsilon=0.005,
            unified_mode=True,
        )
        for turn in result["turns"]:
            for decision in turn["decisions"]:
                if decision["num_candidates"] is not None:
                    self.assertTrue(decision["num_candidates"] >= 1)

    def test_unified_uses_ev_tiebreak_inside_epsilon(self):
        # With epsilon = 1.0, the unified evaluator should choose the same move as the pure Optuna fallback AI
        res_optuna = play_solo_game(
            self.optuna_ai,
            seed=400,
            target_score=260,
        )
        res_unified = play_solo_game(
            self.tablebase_ai,
            seed=400,
            target_score=260,
            score_fallback_ai=self.optuna_ai,
            epsilon=1.0,
            unified_mode=True,
        )
        self.assertEqual(res_unified["final_score"], res_optuna["final_score"])

    def test_unified_never_selects_move_outside_epsilon(self):
        result = play_solo_game(
            self.tablebase_ai,
            seed=100,
            target_score=270,
            score_fallback_ai=self.optuna_ai,
            epsilon=0.005,
            unified_mode=True,
        )
        for turn in result["turns"]:
            for decision in turn["decisions"]:
                if decision["num_candidates"] is not None:
                    wp = decision["utility"]
                    best_wp = decision["tablebase_win_probability"]
                    self.assertTrue(best_wp - wp <= 0.005 + 1e-9)

    def test_invalid_actions_never_selected(self):
        result = play_solo_game(
            self.tablebase_ai,
            seed=200,
            target_score=260,
            score_fallback_ai=self.optuna_ai,
            epsilon=0.01,
            unified_mode=True,
        )
        self.assertEqual(len(result["scored_categories"]), 13)
        self.assertEqual(len(set(result["scored_categories"])), 13)

    def test_dynamic_epsilon_boundaries(self):
        result = play_solo_game(
            self.tablebase_ai,
            seed=300,
            target_score=260,
            score_fallback_ai=self.optuna_ai,
            epsilon="dynamic",
            unified_mode=True,
        )
        self.assertEqual(len(result["scored_categories"]), 13)

    def test_same_seed_pairing_baseline_vs_unified(self):
        res_baseline = play_solo_game(
            self.tablebase_ai,
            seed=500,
            target_score=260,
            score_fallback_ai=self.optuna_ai,
            unified_mode=False,
        )
        res_unified = play_solo_game(
            self.tablebase_ai,
            seed=500,
            target_score=260,
            score_fallback_ai=self.optuna_ai,
            epsilon=0.005,
            unified_mode=True,
        )
        self.assertTrue(res_baseline["final_score"] > 0)
        self.assertTrue(res_unified["final_score"] > 0)

    def test_live_path_unified_mode(self):
        from yahtzee_bot import choose_unified_move

        move = choose_unified_move(
            tablebase_ai=self.tablebase_ai,
            score_fallback_ai=self.optuna_ai,
            open_categories=["ones", "chance"],
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            target_final_score=260,
            player_total_score=0,
            epsilon="dynamic_v1",
        )
        self.assertIn("action", move)
        self.assertIn("target", move)
        self.assertIn("utility", move)
        self.assertIn("wp_changed", move)
        self.assertEqual(move["fallback_solver"], "Unified Evaluator" if move["wp_changed"] else None)

if __name__ == "__main__":
    unittest.main()
