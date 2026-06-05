import unittest

from scripts.check_randomness import chi_square_p_value, extract_roll_groups
from yahtzee_bot import append_unique_opponent_observation, make_opponent_observation


class OpponentDiceLoggingTests(unittest.TestCase):
    def test_make_opponent_observation_records_visible_dice_snapshot(self):
        observation = make_opponent_observation(
            opponent_id="0",
            opponent_score=123,
            rolls_left=2,
            dice=[1, 4, 5, 5, 6],
            timestamp="2026-06-02T17:00:00",
        )

        self.assertEqual(observation["event"], "opponent_observation")
        self.assertEqual(observation["player"], "opponent")
        self.assertEqual(observation["opponent_id"], "0")
        self.assertEqual(observation["opponent_score"], 123)
        self.assertEqual(observation["rolls_left"], 2)
        self.assertEqual(observation["dice"], [1, 4, 5, 5, 6])
        self.assertEqual(observation["source"], "visible_dice")

    def test_make_opponent_observation_rejects_stale_or_invalid_dice(self):
        self.assertIsNone(make_opponent_observation("0", 0, 3, [1, 2, 3, 4, 5]))
        self.assertIsNone(make_opponent_observation("0", 0, 2, [1, 2, 3]))
        self.assertIsNone(make_opponent_observation("0", 0, 2, [1, 2, 3, 4, 9]))

    def test_append_unique_opponent_observation_dedupes_repeated_poll_states(self):
        observations = []
        first = make_opponent_observation("0", 123, 2, [1, 4, 5, 5, 6], timestamp="t1")
        duplicate = make_opponent_observation("0", 123, 2, [1, 4, 5, 5, 6], timestamp="t2")
        changed = make_opponent_observation("0", 123, 1, [1, 5, 5, 6, 6], timestamp="t3")

        last_key = append_unique_opponent_observation(observations, first, last_key=None)
        last_key = append_unique_opponent_observation(observations, duplicate, last_key=last_key)
        append_unique_opponent_observation(observations, changed, last_key=last_key)

        self.assertEqual([obs["timestamp"] for obs in observations], ["t1", "t3"])

    def test_randomness_parser_splits_you_and_opponent_rolls(self):
        records = [
            {
                "turns": [
                    {"rolls_left": 2, "dice": [1, 2, 3, 4, 5], "action": "keep"},
                    {"rolls_left": 1, "dice": [1, 2, 3, 4, 6], "action": "score"},
                ],
                "opponent_observations": [
                    {
                        "event": "opponent_observation",
                        "player": "opponent",
                        "opponent_id": "0",
                        "opponent_score": 42,
                        "rolls_left": 2,
                        "dice": [6, 6, 6, 2, 1],
                        "source": "visible_dice",
                    }
                ],
            }
        ]

        groups = extract_roll_groups(records)

        self.assertEqual(groups["you"], [(1, 2, 3, 4, 5)])
        self.assertEqual(groups["opponent"], [(6, 6, 6, 2, 1)])

    def test_chi_square_p_value_accepts_scipy_style_survival_function(self):
        p_value = chi_square_p_value(
            2.0,
            5,
            survival_function=lambda chi_stat, df: 0.8123,
        )

        self.assertEqual(p_value, 0.8123)


if __name__ == "__main__":
    unittest.main()
