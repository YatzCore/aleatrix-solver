import math
import unittest

from aleatrix_solver.opponent_model import (
    OPTIMAL_FULL_GAME_MEAN,
    OPTIMAL_FULL_GAME_STD,
    OpponentBoard,
    OpponentModel,
    discretized_normal,
    distribution_mean,
    max_of_independent,
    score_to_beat_weights,
)
from aleatrix_solver.yahtzee_ai import CATEGORIES


def fixed_moments(mean, std):
    return lambda open_categories, upper_sum, yahtzee_scored: (mean, std)


class DiscretizedNormalTests(unittest.TestCase):
    def test_sums_to_one_and_keeps_mean_and_std(self):
        distribution = discretized_normal(250.0, 40.0)
        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=12)
        mean = distribution_mean(distribution)
        std = math.sqrt(sum(p * (s - mean) ** 2 for s, p in distribution.items()))
        self.assertAlmostEqual(mean, 250.0, places=2)
        self.assertAlmostEqual(std, 40.0, delta=0.1)

    def test_respects_minimum(self):
        distribution = discretized_normal(105.0, 30.0, minimum=100)
        self.assertEqual(min(distribution), 100)
        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=12)

    def test_zero_std_is_point_mass(self):
        self.assertEqual(discretized_normal(201.4, 0.0), {201: 1.0})


class MaxOfIndependentTests(unittest.TestCase):
    def test_point_masses(self):
        self.assertEqual(max_of_independent([{200: 1.0}, {250: 1.0}]), {250: 1.0})

    def test_two_coin_flips(self):
        result = max_of_independent([{0: 0.5, 1: 0.5}, {0: 0.5, 1: 0.5}])
        self.assertAlmostEqual(result[0], 0.25)
        self.assertAlmostEqual(result[1], 0.75)

    def test_single_distribution_is_unchanged(self):
        self.assertEqual(max_of_independent([{3: 0.2, 7: 0.8}]), {3: 0.2, 7: 0.8})


class OpponentModelTests(unittest.TestCase):
    def test_finished_opponent_is_exact(self):
        model = OpponentModel(fixed_moments(100.0, 10.0))
        board = OpponentBoard(score=231, open_categories=[])
        self.assertEqual(model.final_score_distribution(board), {231: 1.0})

    def test_remaining_moments_are_added_to_current_score(self):
        model = OpponentModel(fixed_moments(50.0, 15.0))
        board = OpponentBoard(score=180, open_categories=["chance", "yahtzee"])
        distribution = model.final_score_distribution(board)
        self.assertAlmostEqual(distribution_mean(distribution), 230.0, delta=0.5)
        self.assertGreaterEqual(min(distribution), 180)

    def test_history_calibration(self):
        weak_scores = [200.0, 220.0] * 20
        model = OpponentModel.from_history(fixed_moments(0, 0), weak_scores)
        self.assertAlmostEqual(model.mean_ratio, 210.0 / OPTIMAL_FULL_GAME_MEAN)
        self.assertEqual(model.std_ratio, 0.8)  # clamped: 10.1 / 60 is implausibly narrow

        too_few = OpponentModel.from_history(fixed_moments(0, 0), weak_scores[:10])
        self.assertEqual((too_few.mean_ratio, too_few.std_ratio), (1.0, 1.0))

    def test_optimal_constants_match_full_game(self):
        self.assertAlmostEqual(OPTIMAL_FULL_GAME_MEAN, 254.609, places=3)
        self.assertAlmostEqual(OPTIMAL_FULL_GAME_STD, 60.012, places=3)

    def test_best_of_several_opponents(self):
        model = OpponentModel(fixed_moments(0.0, 0.0))
        boards = [
            OpponentBoard(score=210, open_categories=[]),
            OpponentBoard(score=240, open_categories=list(CATEGORIES[:1])),
        ]
        self.assertEqual(model.best_opponent_distribution(boards), {240: 1.0})


class ScoreToBeatWeightTests(unittest.TestCase):
    def test_maps_final_scores_to_points_needed(self):
        # 150 total with 70 upper (bonus earned): 45 lower points are banked.
        weights = score_to_beat_weights({280: 0.25, 300: 0.75}, player_total_score=150, upper_sum=70)
        self.assertEqual(len(weights), 401)
        self.assertAlmostEqual(weights[280 + 1 - 45], 0.25)
        self.assertAlmostEqual(weights[300 + 1 - 45], 0.75)
        self.assertAlmostEqual(sum(weights), 1.0)

    def test_clamps_to_tablebase_range(self):
        weights = score_to_beat_weights({0: 0.5, 900: 0.5}, player_total_score=40, upper_sum=0)
        self.assertAlmostEqual(weights[0], 0.5)
        self.assertAlmostEqual(weights[400], 0.5)


if __name__ == "__main__":
    unittest.main()
