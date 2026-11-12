import os
import unittest

from aleatrix_solver.mixture_solver import choose_mixture_move
from aleatrix_solver.yahtzee_ai import CATEGORIES
from yahtzee_bot import TablebaseAI, default_library_path, is_tablebase_ready

CHANCE = CATEGORIES.index("chance")
ONES = CATEGORIES.index("ones")


class FakeMixtureAI:
    def __init__(self, wp_moves, ev_moves):
        self.wp_moves = wp_moves
        self.ev_moves = ev_moves
        self.weights = None

    def get_ranked_moves_weighted(self, weights, **kwargs):
        self.weights = weights
        return [dict(m) for m in self.wp_moves]

    def get_ranked_moves_ev(self, **kwargs):
        return [dict(m) for m in self.ev_moves]


def move(action_type, target_idx, value):
    return {"action_type": action_type, "target_idx": target_idx, "wp": value}


class MixtureSolverUnitTests(unittest.TestCase):
    def choose(self, ai, dice=(1, 1, 3, 5, 6), distribution=None):
        return choose_mixture_move(
            tablebase_ai=ai,
            open_categories=["ones", "chance"],
            current_dice=list(dice),
            rolls_left=2,
            upper_sum=0,
            yahtzee_scored=False,
            player_total_score=100,
            opponent_final_distribution=distribution or {250: 1.0},
        )

    def test_picks_highest_win_probability(self):
        ai = FakeMixtureAI(
            [move(1, 0b00011, 0.40), move(0, CHANCE, 0.35)],
            [move(0, CHANCE, 30.0), move(1, 0b00011, 20.0)],
        )
        result = self.choose(ai)
        self.assertEqual(result["action"], "keep")
        self.assertEqual(result["target"], [1, 1])
        self.assertFalse(result["wp_changed"])
        self.assertAlmostEqual(result["utility"], 0.40)

    def test_exact_ties_are_broken_by_expected_score(self):
        ai = FakeMixtureAI(
            [move(0, ONES, 0.5), move(0, CHANCE, 0.5), move(1, 1, 0.2)],
            [move(0, CHANCE, 40.0), move(0, ONES, 30.0), move(1, 1, 35.0)],
        )
        result = self.choose(ai)
        self.assertEqual(result["action"], "score")
        self.assertEqual(result["target"], "chance")
        self.assertTrue(result["wp_changed"])
        self.assertAlmostEqual(result["ev_gain"], 10.0)

    def test_weights_encode_the_opponent_distribution(self):
        ai = FakeMixtureAI([move(0, CHANCE, 0.5)], [move(0, CHANCE, 1.0)])
        self.choose(ai, distribution={240: 0.5, 260: 0.5})
        # 100 lower points banked: need 141 or 161 more points.
        self.assertAlmostEqual(ai.weights[141], 0.5)
        self.assertAlmostEqual(ai.weights[161], 0.5)
        self.assertAlmostEqual(sum(ai.weights), 1.0)


def library_with_ev():
    path = default_library_path(os.getcwd())
    if not os.path.exists(path):
        return None
    try:
        ai = TablebaseAI.ev_only(path)
    except (OSError, RuntimeError):
        return None
    return ai


class ExactEvLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = library_with_ev()
        if cls.ai is None:
            raise unittest.SkipTest("compiled solver library with exact-EV support is not available")

    def test_full_game_moments(self):
        mean, std = self.ai.get_remaining_score_moments(CATEGORIES, 0, False)
        self.assertAlmostEqual(mean, 254.609, places=2)
        self.assertAlmostEqual(std, 60.012, places=2)

    def test_scores_a_rolled_yahtzee(self):
        moves = self.ai.get_ranked_moves_ev(CATEGORIES, [4, 4, 4, 4, 4], 2, 0, False)
        self.assertEqual((moves[0]["action_type"], CATEGORIES[moves[0]["target_idx"]]), (0, "yahtzee"))
        self.assertFalse(any(m["action_type"] == 1 and m["target_idx"] == 31 for m in moves))


class MixtureTablebaseLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dll_path = default_library_path(os.getcwd())
        bin_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "tablebase.bin"))
        if not is_tablebase_ready(dll_path, bin_path):
            raise unittest.SkipTest("complete C++ tablebase is not available")
        cls.ai = TablebaseAI(dll_path, bin_path)
        if not cls.ai.supports_exact_ev:
            raise unittest.SkipTest("solver library predates the mixture entry points")

    def test_point_mass_matches_single_target_ranking(self):
        kwargs = dict(
            open_categories=["ones", "fullhouse", "largestraight", "chance"],
            current_dice=[2, 3, 4, 5, 5],
            rolls_left=2,
            upper_sum=12,
            yahtzee_scored=False,
        )
        single = self.ai.get_ranked_moves(target_final_score=230, player_total_score=180, **kwargs)
        weights = [0.0] * 401
        weights[230 + 1 - (180 - 12)] = 1.0
        mixed = self.ai.get_ranked_moves_weighted(weights=weights, **kwargs)

        single_by_move = {(m["action_type"], m["target_idx"]): m["wp"] for m in single}
        self.assertTrue(mixed)
        for m in mixed:
            self.assertAlmostEqual(m["wp"], single_by_move[(m["action_type"], m["target_idx"])], places=12)

    def test_mixture_is_the_weighted_average_for_score_moves(self):
        kwargs = dict(
            open_categories=["chance", "yahtzee"],
            current_dice=[6, 6, 5, 5, 4],
            rolls_left=0,
            upper_sum=0,
            yahtzee_scored=False,
        )
        weights = [0.0] * 401
        weights[30] = 0.25
        weights[60] = 0.75
        mixed = {m["target_idx"]: m["wp"] for m in self.ai.get_ranked_moves_weighted(weights=weights, **kwargs)}
        low = {m["target_idx"]: m["wp"] for m in self.ai.get_ranked_moves(
            target_final_score=29, player_total_score=0, **kwargs)}
        high = {m["target_idx"]: m["wp"] for m in self.ai.get_ranked_moves(
            target_final_score=59, player_total_score=0, **kwargs)}
        for category, wp in mixed.items():
            self.assertAlmostEqual(wp, 0.25 * low[category] + 0.75 * high[category], places=12)


if __name__ == "__main__":
    unittest.main()
