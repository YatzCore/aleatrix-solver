import os
import unittest

from yahtzee_ai import CATEGORIES
from yahtzee_bot import TablebaseAI, is_tablebase_ready


class LiveTablebasePolicyTests(unittest.TestCase):
    def test_tablebase_defers_zero_scratch_when_rolls_remain(self):
        dll_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "build", "Release", "yahtzee_core.dll"))
        bin_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "tablebase.bin"))
        if not is_tablebase_ready(dll_path, bin_path):
            self.skipTest("complete C++ tablebase is not available")

        ai = TablebaseAI(dll_path, bin_path)
        open_categories = [
            cat for cat in CATEGORIES
            if cat not in {"fullhouse", "chance", "threeofakind"}
        ]

        action, target, _, evs, _ = ai.get_optimal_move(
            open_categories=open_categories,
            current_dice=[4, 2, 6, 1, 5],
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            target_final_score=284,
            player_total_score=72,
        )

        self.assertFalse(action == "score" and evs[target] == 0)


if __name__ == "__main__":
    unittest.main()
