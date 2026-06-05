import unittest
from types import SimpleNamespace

from evolve import (
    build_tuned_ai,
    distribute_trials,
    rerank_top_trials_with_exact_dp,
)
from aleatrix_solver.strategy_config import DEFAULT_STRATEGY_CONFIG


class EvolveTests(unittest.TestCase):
    def test_distribute_trials_does_not_overshoot_requested_trials(self):
        self.assertEqual(distribute_trials(10, 3), [4, 3, 3])
        self.assertEqual(distribute_trials(2, 4), [1, 1])
        self.assertEqual(sum(distribute_trials(31, 8)), 31)

    def test_build_tuned_ai_uses_fast_limits_for_optimization_and_exact_limits_for_rerank(self):
        params = {
            "risk_multiplier": 0.5,
            "decay_exponent": 0.6,
            "yahtzee_baseline": 20.0,
            "chance_baseline": 29.0,
            "bonus_multiplier": 42.0,
            "opponent_risk_percentile": 77,
        }

        fast_ai = build_tuned_ai(params, exact_dp_enabled=False)
        exact_ai = build_tuned_ai(params, exact_dp_enabled=True)

        self.assertEqual(fast_ai.exact_category_limit, 0)
        self.assertEqual(fast_ai.lower_only_exact_category_limit, 0)
        self.assertEqual(exact_ai.exact_category_limit, DEFAULT_STRATEGY_CONFIG["exact_category_limit"])
        self.assertEqual(exact_ai.lower_only_exact_category_limit, DEFAULT_STRATEGY_CONFIG["lower_only_exact_category_limit"])

    def test_rerank_top_trials_with_exact_dp_uses_evaluator_result_not_original_value(self):
        low_original_best_exact = SimpleNamespace(number=1, value=0.9, params={"risk_multiplier": 1.0})
        high_original_bad_exact = SimpleNamespace(number=2, value=0.95, params={"risk_multiplier": 2.0})

        def evaluator(params):
            return {
                "win_rate": 0.8 if params["risk_multiplier"] == 1.0 else 0.4,
                "average_score": 240,
            }

        trial, metrics = rerank_top_trials_with_exact_dp(
            [low_original_best_exact, high_original_bad_exact],
            top_n=2,
            evaluator=evaluator,
        )

        self.assertEqual(trial.number, 1)
        self.assertEqual(metrics["win_rate"], 0.8)


if __name__ == "__main__":
    unittest.main()
