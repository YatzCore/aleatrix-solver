import unittest

from aleatrix_solver.yahtzee_ai import YahtzeeAI


class YahtzeeAIEndgameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = YahtzeeAI()

    def test_scratches_full_house_to_preserve_chance_endgame(self):
        action, target, _, _ = self.ai.get_optimal_move(
            open_categories=["fullhouse", "chance"],
            current_dice=[1, 1, 2, 2, 6],
            rolls_left=0,
            upper_sum=0,
        )

        self.assertEqual(action, "score")
        self.assertEqual(target, "fullhouse")

    def test_keeps_two_pair_when_chasing_full_house_before_chance(self):
        action, target, _, _ = self.ai.get_optimal_move(
            open_categories=["fullhouse", "chance"],
            current_dice=[1, 1, 2, 2, 6],
            rolls_left=1,
            upper_sum=0,
        )

        self.assertEqual(action, "keep")
        self.assertEqual(target, (1, 1, 2, 2))

    def test_uses_upper_bonus_scorecard_lookahead_with_four_boxes_left(self):
        action, target, _, _ = self.ai.get_optimal_move(
            open_categories=["fours", "fives", "sixes", "chance"],
            current_dice=[6, 6, 5, 4, 1],
            rolls_left=2,
            upper_sum=42,
        )

        self.assertEqual(action, "keep")
        self.assertEqual(target, (6, 6))

    def test_exact_scorecard_depth_can_be_limited_for_strategy_comparison(self):
        ai = YahtzeeAI(exact_category_limit=3, lower_only_exact_category_limit=4)

        action, target, _, _ = ai.get_optimal_move(
            open_categories=["fours", "fives", "sixes", "chance"],
            current_dice=[6, 6, 5, 4, 1],
            rolls_left=2,
            upper_sum=42,
        )

        self.assertEqual(action, "keep")
        self.assertEqual(target, (5, 6, 6))

    def test_configurable_baselines_affect_move_decisions(self):
        ai_default = YahtzeeAI(chance_baseline=22.0)
        ai_high_chance = YahtzeeAI(chance_baseline=50.0)

        open_cats = ["chance", "twos", "threes", "fours", "fives"]
        dice = [6, 6, 6, 6, 6]

        _, _, util_default, _ = ai_default.get_optimal_move(
            open_categories=open_cats,
            current_dice=dice,
            rolls_left=1,
            upper_sum=0
        )
        _, _, util_high, _ = ai_high_chance.get_optimal_move(
            open_categories=open_cats,
            current_dice=dice,
            rolls_left=1,
            upper_sum=0
        )
        self.assertNotEqual(util_default, util_high)




if __name__ == "__main__":
    unittest.main()
