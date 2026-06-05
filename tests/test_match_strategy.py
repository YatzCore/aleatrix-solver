import unittest

from aleatrix_solver.match_strategy import choose_risk_level, project_opponent_score
from aleatrix_solver.yahtzee_ai import CATEGORIES, YahtzeeAI


class MatchStrategyTests(unittest.TestCase):
    def test_choose_risk_level_gets_aggressive_when_far_behind(self):
        self.assertEqual(choose_risk_level(player_score=120, opponent_score=180, open_category_count=6), 1.0)

    def test_choose_risk_level_gets_conservative_when_ahead_late(self):
        self.assertEqual(choose_risk_level(player_score=230, opponent_score=190, open_category_count=4), -0.5)

    def test_project_opponent_score_adds_expected_remaining_turns(self):
        self.assertEqual(project_opponent_score(opponent_score=120, open_category_count=5), 230)

    def test_choose_risk_level_uses_projected_opponent_score(self):
        # Projected opponent is 230.
        # Bot score is 70, with 5 turns left, projecting to 70 + 5 * 22 = 180.
        # Score gap is 230 - 180 = 50, which is >= 45, requiring aggressive risk mode (1.0).
        risk = choose_risk_level(
            player_score=70,
            opponent_score=120,
            open_category_count=5,
            projected_opponent_score=230,
        )

        self.assertEqual(risk, 1.0)

    def test_ai_accepts_risk_level_without_changing_normal_default(self):
        ai = YahtzeeAI()
        normal = ai.get_optimal_move(
            open_categories=CATEGORIES,
            current_dice=[1, 2, 3, 4, 6],
            rolls_left=1,
            upper_sum=0,
        )
        explicit_normal = ai.get_optimal_move(
            open_categories=CATEGORIES,
            current_dice=[1, 2, 3, 4, 6],
            rolls_left=1,
            upper_sum=0,
            risk_level=0.0,
        )

        self.assertEqual(explicit_normal[:2], normal[:2])

    def test_aggressive_risk_level_boosts_high_upside_chase_value(self):
        ai = YahtzeeAI()
        normal = ai.get_optimal_move(
            open_categories=CATEGORIES,
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=1,
            upper_sum=0,
            risk_level=0.0,
        )
        aggressive = ai.get_optimal_move(
            open_categories=CATEGORIES,
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=1,
            upper_sum=0,
            risk_level=1.0,
        )

        self.assertEqual(aggressive[:2], normal[:2])
        self.assertGreater(aggressive[2], normal[2])

    def test_aggressive_risk_level_boosts_exact_scorecard_branch(self):
        ai = YahtzeeAI()
        normal = ai.get_optimal_move(
            open_categories=["yahtzee", "chance"],
            current_dice=[6, 6, 6, 6, 1],
            rolls_left=1,
            upper_sum=0,
            risk_level=0.0,
        )
        aggressive = ai.get_optimal_move(
            open_categories=["yahtzee", "chance"],
            current_dice=[6, 6, 6, 6, 1],
            rolls_left=1,
            upper_sum=0,
            risk_level=1.0,
        )

        self.assertEqual(aggressive[:2], normal[:2])
        self.assertGreater(aggressive[2], normal[2])

    def test_risk_multiplier_controls_aggressive_utility_boost(self):
        default_ai = YahtzeeAI(risk_multiplier=1.0)
        bold_ai = YahtzeeAI(risk_multiplier=2.0)

        default_move = default_ai.get_optimal_move(
            open_categories=CATEGORIES,
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=1,
            upper_sum=0,
            risk_level=1.0,
        )
        bold_move = bold_ai.get_optimal_move(
            open_categories=CATEGORIES,
            current_dice=[6, 6, 6, 1, 2],
            rolls_left=1,
            upper_sum=0,
            risk_level=1.0,
        )

        self.assertEqual(bold_move[:2], default_move[:2])
        self.assertGreater(bold_move[2], default_move[2])

    def test_project_opponent_score_uses_projection_model_and_percentiles(self):
        # Model with U=5 having posterior mean = 110, std dev = 20
        model = {5: (110.0, 20.0)}

        # 75th percentile z-score = 0.674
        proj_75 = project_opponent_score(
            opponent_score=100,
            open_category_count=5,
            projection_model=model,
            percentile=75
        )
        self.assertAlmostEqual(proj_75, 100 + 110.0 + 0.674 * 20.0, places=2)

        # 95th percentile z-score = 1.645
        proj_95 = project_opponent_score(
            opponent_score=100,
            open_category_count=5,
            projection_model=model,
            percentile=95
        )
        self.assertAlmostEqual(proj_95, 100 + 110.0 + 1.645 * 20.0, places=2)


if __name__ == "__main__":
    unittest.main()
