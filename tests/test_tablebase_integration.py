import ctypes
import inspect
import json
import tempfile
import unittest
from pathlib import Path

import yahtzee_bot
from aleatrix_solver import tablebase_target
from yahtzee_bot import (
    TablebaseAI,
    build_overlay_html,
    choose_tablebase_target_score,
    click_game_element,
    compute_tablebase_score_to_beat,
    compute_upper_sum_from_score_cells,
    get_active_tentative_player_id_from_snapshot,
    get_live_scores_from_snapshot,
    get_open_categories_from_snapshot,
    get_player_score_from_snapshot,
    get_upper_sum_from_snapshot,
    is_our_turn_from_snapshot,
    is_yahtzee_scored_from_snapshot,
    is_tablebase_ready,
    keep_values_from_mask,
    read_dice_from_snapshot,
    read_rolls_left_from_snapshot,
    wait_for_new_game_after_restart,
)


class FakeTablebaseLib:
    def __init__(self):
        self.captured_score_to_beat = None
        self.captured_rolls_left = None

    def get_optimal_move_dll(
        self,
        ctx,
        mask,
        upper_sum,
        yahtzee_scored,
        score_to_beat,
        rolls_left,
        current_dice,
        out_cat,
        out_mask,
        out_ev,
    ):
        self.captured_score_to_beat = score_to_beat
        self.captured_rolls_left = rolls_left
        ctypes.cast(out_mask, ctypes.POINTER(ctypes.c_int))[0] = 3
        ctypes.cast(out_ev, ctypes.POINTER(ctypes.c_double))[0] = 0.75
        return 1


class FakeLocator:
    def __init__(self, visible=True):
        self.clicked = False
        self.visible = visible
        self.waits = []

    def count(self):
        return 1

    def is_visible(self):
        return self.visible

    def click(self, force=False):
        self.clicked = True

    def wait_for(self, state=None, timeout=None):
        self.waits.append((state, timeout))


class FakeRestartPage:
    def __init__(self):
        self.play_again = FakeLocator()
        self.modal = FakeLocator()
        self.waited_functions = []

    def locator(self, selector):
        if selector == "#playNextRound":
            return self.play_again
        if selector == "#yahtzeeScoreModal":
            return self.modal
        raise AssertionError(f"unexpected selector: {selector}")

    def wait_for_function(self, script, timeout=None):
        self.waited_functions.append((script, timeout))


class FakeClickPage:
    def __init__(self):
        self.evaluate_calls = []
        self.clicked_selectors = []

    def evaluate(self, script, *args):
        self.evaluate_calls.append((script, args))

    def locator(self, selector):
        page = self

        class Locator:
            def click(self, force=False):
                page.clicked_selectors.append((selector, force))

        return Locator()


class FakeSnapshotPage:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.evaluate_calls = []

    def evaluate(self, script, *args):
        self.evaluate_calls.append((script, args))
        return self.snapshot


class TablebaseIntegrationTests(unittest.TestCase):
    def test_score_fallback_policy_uses_optimized_thresholds(self):
        self.assertEqual(tablebase_target.TABLEBASE_SCORE_FALLBACK_THRESHOLD, 0.075)
        self.assertEqual(getattr(tablebase_target, "TABLEBASE_TARGET_SCORE_FALLBACK_THRESHOLD", None), 260)
        self.assertEqual(getattr(tablebase_target, "TABLEBASE_REQUIRED_AVG_FALLBACK_THRESHOLD", None), 22.0)

        self.assertTrue(tablebase_target.should_use_score_fallback(0.075))
        self.assertFalse(
            tablebase_target.should_use_score_fallback(
                0.076,
                target_score=259,
                player_total_score=238,
                open_category_count=1,
            )
        )

    def test_score_fallback_policy_uses_target_and_required_average_gates(self):
        self.assertTrue(
            tablebase_target.should_use_score_fallback(
                0.8,
                target_score=260,
                player_total_score=250,
                open_category_count=2,
            )
        )
        self.assertTrue(
            tablebase_target.should_use_score_fallback(
                0.8,
                target_score=259,
                player_total_score=215,
                open_category_count=2,
            )
        )
        self.assertFalse(
            tablebase_target.should_use_score_fallback(
                0.8,
                target_score=259,
                player_total_score=216,
                open_category_count=2,
            )
        )

    def test_inject_ui_overlay_uses_single_overlay_html_source(self):
        source = inspect.getsource(yahtzee_bot.inject_ui_overlay)

        self.assertEqual(source.count("overlay_html ="), 1)
        self.assertIn("overlay_html = build_overlay_html(", source)
        self.assertNotIn("SOLVER_MODE", source)

    def test_visible_snapshot_normalizes_core_game_state_without_double_counting_totals(self):
        snapshot = {
            "rolls_left": 2,
            "roll_button_disabled": False,
            "active_tentative_player_id": "0",
            "dice": [
                {"value": 5, "held": False},
                {"value": 5, "held": True},
                {"value": 6, "held": False},
                {"value": 1, "held": False},
                {"value": 2, "held": False},
            ],
            "players": ["0", "1"],
            "score_cells": {
                "0": {
                    "ones": {"text": "3", "classes": "scoreCell"},
                    "twos": {"text": "4", "classes": "scoreCell"},
                    "threes": {"text": "", "classes": "scoreCell tentative"},
                    "fours": {"text": "", "classes": "scoreCell"},
                    "fives": {"text": "", "classes": "scoreCell tentative"},
                    "sixes": {"text": "", "classes": "scoreCell"},
                    "chance": {"text": "26", "classes": "scoreCell"},
                    "bonus": {"text": "35", "classes": "scoreCell"},
                    "sum": {"text": "7", "classes": "scoreCell"},
                    "totalscore": {"text": "", "classes": "scoreCell"},
                    "yahtzee": {"text": "50", "classes": "scoreCell"},
                },
                "1": {
                    "chance": {"text": "22", "classes": "scoreCell"},
                    "totalscore": {"text": "222", "classes": "scoreCell"},
                },
            },
        }

        self.assertEqual(read_rolls_left_from_snapshot(snapshot), 2)
        self.assertEqual(read_dice_from_snapshot(snapshot), [5, 5, 6, 1, 2])
        self.assertEqual(get_player_score_from_snapshot(snapshot, "0"), 118)
        self.assertEqual(get_live_scores_from_snapshot(snapshot, "0"), (118, 222))
        self.assertEqual(get_upper_sum_from_snapshot(snapshot, "0"), 7)
        self.assertEqual(get_active_tentative_player_id_from_snapshot(snapshot), "0")
        self.assertTrue(is_our_turn_from_snapshot(snapshot, "0"))
        self.assertTrue(is_yahtzee_scored_from_snapshot(snapshot, "0"))
        self.assertIn("threes", get_open_categories_from_snapshot(snapshot, "0"))
        self.assertIn("fives", get_open_categories_from_snapshot(snapshot, "0"))
        self.assertNotIn("chance", get_open_categories_from_snapshot(snapshot, "0"))

    def test_scorecard_reconciliation_reopens_uncommitted_ui_categories(self):
        reconcile = getattr(yahtzee_bot, "reconcile_scored_categories_from_snapshot", None)
        self.assertIsNotNone(reconcile)

        scored_categories = {"ones", "twos", "sixes", "chance"}
        snapshot = {
            "score_cells": {
                "0": {
                    "ones": {"text": "3", "classes": "scoreCell", "visible": True},
                    "twos": {"text": "", "classes": "scoreCell tentative", "visible": True},
                    "sixes": {"text": "", "classes": "scoreCell", "visible": True},
                    "chance": {"text": "24", "classes": "scoreCell", "visible": False},
                }
            }
        }

        reopened = reconcile(scored_categories, snapshot, "0")

        self.assertEqual(reopened, {"twos", "sixes"})
        self.assertEqual(scored_categories, {"ones", "chance"})

    def test_user_player_id_does_not_drift_to_active_opponent_turn(self):
        yahtzee_bot.KNOWN_USER_PLAYER_ID = "0"
        page = FakeSnapshotPage({
            "players": ["0", "1"],
            "current_player_id": "1",
            "user_player_id": None,
            "active_tentative_player_id": "1",
        })

        try:
            self.assertEqual(yahtzee_bot.get_user_player_id(page), "0")
            self.assertEqual(page.evaluate_calls[0][1], ("0",))
        finally:
            yahtzee_bot.KNOWN_USER_PLAYER_ID = None

    def test_game_click_temporarily_disables_overlay_pointer_events(self):
        page = FakeClickPage()

        click_game_element(page, "#roll")

        self.assertEqual(page.clicked_selectors, [("#roll", True)])
        self.assertEqual(len(page.evaluate_calls), 2)
        self.assertFalse(page.evaluate_calls[0][1][0])
        self.assertTrue(page.evaluate_calls[1][1][0])

    def test_overlay_stop_button_requires_confirmation(self):
        html = build_overlay_html(is_tablebase=True)

        self.assertIn("data-stop-confirm-ms", html)
        self.assertIn("Confirm Stop", html)
        self.assertIn("btn-bot-minimize", html)

    def test_upper_sum_comes_from_locked_upper_category_cells(self):
        cells = {
            "ones": {"text": "0", "classes": "scoreCell ones_0"},
            "twos": {"text": "8", "classes": "scoreCell twos_0"},
            "threes": {"text": "3", "classes": "scoreCell threes_0"},
            "fours": {"text": "16", "classes": "scoreCell fours_0"},
            "fives": {"text": "15", "classes": "scoreCell fives_0"},
            "sixes": {"text": "", "classes": "scoreCell sixes_0 tentative"},
        }

        self.assertEqual(compute_upper_sum_from_score_cells(cells, displayed_sum=0), 42)

    def test_upper_sum_falls_back_to_displayed_sum_when_no_upper_cells_locked(self):
        cells = {
            "ones": {"text": "", "classes": "scoreCell ones_0 tentative"},
            "twos": {"text": "", "classes": "scoreCell twos_0"},
        }

        self.assertEqual(compute_upper_sum_from_score_cells(cells, displayed_sum=24), 24)

    def test_target_score_prefers_projected_then_historical_then_current(self):
        self.assertEqual(
            choose_tablebase_target_score(projected_opponent_score=287.2, target_score=260, opponent_score=120),
            288,
        )
        self.assertEqual(
            choose_tablebase_target_score(projected_opponent_score=None, target_score=260, opponent_score=120),
            260,
        )
        self.assertEqual(
            choose_tablebase_target_score(projected_opponent_score=None, target_score=None, opponent_score=120),
            120,
        )

    def test_stabilized_target_anchors_early_and_middle_game(self):
        self.assertEqual(
            yahtzee_bot.get_stabilized_tablebase_target(
                open_category_count=9,
                projected_opponent_score=470,
                target_score=281,
                opponent_score=120,
                previous_target=315,
            ),
            250,
        )

    def test_stabilized_target_clamps_endgame_projection(self):
        self.assertEqual(
            yahtzee_bot.get_stabilized_tablebase_target(
                open_category_count=4,
                projected_opponent_score=470,
                target_score=281,
                opponent_score=120,
                previous_target=250,
            ),
            315,
        )
        self.assertEqual(
            yahtzee_bot.get_stabilized_tablebase_target(
                open_category_count=4,
                projected_opponent_score=180,
                target_score=281,
                opponent_score=120,
                previous_target=315,
            ),
            240,
        )

    def test_stabilized_target_keeps_previous_target_for_small_endgame_changes(self):
        self.assertEqual(
            yahtzee_bot.get_stabilized_tablebase_target(
                open_category_count=4,
                projected_opponent_score=258,
                target_score=281,
                opponent_score=120,
                previous_target=250,
            ),
            250,
        )
        self.assertEqual(
            yahtzee_bot.get_stabilized_tablebase_target(
                open_category_count=4,
                projected_opponent_score=None,
                target_score=281,
                opponent_score=120,
                previous_target=250,
            ),
            281,
        )

    def test_zero_win_tablebase_move_uses_score_ev_fallback(self):
        class ZeroWinTablebase:
            def __init__(self):
                self.calls = []

            def get_optimal_move(self, **kwargs):
                self.calls.append(kwargs)
                return "score", "ones", 0.0, {"ones": 1}, 0.0004

        class ScoreFallback:
            def __init__(self):
                self.calls = []
                self.fallback_solver_name = "Optuna Expectiminimax"

            def get_optimal_move(self, **kwargs):
                self.calls.append(kwargs)
                return "score", "chance", 22.0, {"chance": 22}

        tablebase_ai = ZeroWinTablebase()
        fallback_ai = ScoreFallback()

        result = yahtzee_bot.choose_tablebase_move_with_score_fallback(
            tablebase_ai=tablebase_ai,
            score_fallback_ai=fallback_ai,
            open_categories=["ones", "chance"],
            current_dice=[6, 5, 4, 4, 3],
            rolls_left=0,
            upper_sum=12,
            yahtzee_scored=False,
            target_final_score=315,
            player_total_score=140,
            fallback_threshold=0.00001,
        )

        self.assertEqual(result["action"], "score")
        self.assertEqual(result["target"], "chance")
        self.assertEqual(result["utility"], 22.0)
        self.assertEqual(result["tablebase_win_probability"], 0.0)
        self.assertTrue(result["score_fallback_used"])
        self.assertEqual(result["fallback_solver"], "Optuna Expectiminimax")
        self.assertEqual(fallback_ai.calls[0]["risk_level"], 0.0)
        self.assertEqual(tablebase_ai.calls[0]["target_final_score"], 315)

    def test_low_win_zero_scratch_uses_score_ev_fallback(self):
        class LowWinScratchTablebase:
            def get_optimal_move(self, **kwargs):
                return "score", "fives", 0.046, {"fives": 0, "threeofakind": 18}, 0.0003

        class ScoreFallback:
            def __init__(self):
                self.calls = []

            def get_optimal_move(self, **kwargs):
                self.calls.append(kwargs)
                return "score", "threeofakind", 31.2, {"fives": 0, "threeofakind": 18}

        fallback_ai = ScoreFallback()

        result = yahtzee_bot.choose_tablebase_move_with_score_fallback(
            tablebase_ai=LowWinScratchTablebase(),
            score_fallback_ai=fallback_ai,
            open_categories=["fives", "threeofakind"],
            current_dice=[4, 4, 2, 4, 4],
            rolls_left=0,
            upper_sum=38,
            yahtzee_scored=True,
            target_final_score=315,
            player_total_score=231,
            fallback_threshold=0.00001,
        )

        self.assertEqual(result["action"], "score")
        self.assertEqual(result["target"], "threeofakind")
        self.assertTrue(result["score_fallback_used"])
        self.assertEqual(fallback_ai.calls[0]["rolls_left"], 0)

    def test_high_target_score_uses_score_ev_fallback(self):
        class HighWinTablebase:
            def get_optimal_move(self, **kwargs):
                return "keep", [6, 6], 0.8, {"sixes": 12}, 0.0003

        class ScoreFallback:
            def __init__(self):
                self.calls = []

            def get_optimal_move(self, **kwargs):
                self.calls.append(kwargs)
                return "score", "chance", 22.0, {"chance": 22}

        fallback_ai = ScoreFallback()

        result = yahtzee_bot.choose_tablebase_move_with_score_fallback(
            tablebase_ai=HighWinTablebase(),
            score_fallback_ai=fallback_ai,
            open_categories=["sixes", "chance"],
            current_dice=[6, 6, 3, 2, 1],
            rolls_left=2,
            upper_sum=12,
            yahtzee_scored=False,
            target_final_score=260,
            player_total_score=250,
            fallback_threshold=0.00001,
        )

        self.assertEqual(result["action"], "score")
        self.assertEqual(result["target"], "chance")
        self.assertTrue(result["score_fallback_used"])
        self.assertEqual(fallback_ai.calls[0]["rolls_left"], 2)

    def test_nonzero_win_tablebase_move_does_not_use_score_ev_fallback(self):
        class LiveTablebase:
            def get_optimal_move(self, **kwargs):
                return "keep", [6, 6], 0.02, {"sixes": 12}, 0.0003

        class ScoreFallback:
            def __init__(self):
                self.calls = []

            def get_optimal_move(self, **kwargs):
                self.calls.append(kwargs)
                return "score", "chance", 22.0, {"chance": 22}

        fallback_ai = ScoreFallback()

        result = yahtzee_bot.choose_tablebase_move_with_score_fallback(
            tablebase_ai=LiveTablebase(),
            score_fallback_ai=fallback_ai,
            open_categories=["sixes", "chance"],
            current_dice=[6, 6, 3, 2, 1],
            rolls_left=2,
            upper_sum=12,
            yahtzee_scored=False,
            target_final_score=255,
            player_total_score=230,
            fallback_threshold=0.00001,
        )

        self.assertEqual(result["action"], "keep")
        self.assertEqual(result["target"], [6, 6])
        self.assertEqual(result["utility"], 0.02)
        self.assertFalse(result["score_fallback_used"])
        self.assertEqual(fallback_ai.calls, [])

    def test_tablebase_keep_all_is_converted_to_scoring_move(self):
        class KeepAllThenScoreTablebase:
            def __init__(self):
                self.rolls_left_calls = []

            def get_optimal_move(self, **kwargs):
                self.rolls_left_calls.append(kwargs["rolls_left"])
                if kwargs["rolls_left"] > 0:
                    return "keep", [1, 2, 3, 4, 5], 0.78, {"largestraight": 40}, 0.0003
                return "score", "largestraight", 0.77, {"largestraight": 40}, 0.0002

        tablebase_ai = KeepAllThenScoreTablebase()

        result = yahtzee_bot.choose_tablebase_move_with_score_fallback(
            tablebase_ai=tablebase_ai,
            score_fallback_ai=None,
            open_categories=["largestraight", "chance"],
            current_dice=[3, 2, 4, 1, 5],
            rolls_left=1,
            upper_sum=24,
            yahtzee_scored=False,
            target_final_score=250,
            player_total_score=104,
        )

        self.assertEqual(result["action"], "score")
        self.assertEqual(result["target"], "largestraight")
        self.assertEqual(result["evs"]["largestraight"], 40)
        self.assertTrue(result["full_keep_converted"])
        self.assertEqual(tablebase_ai.rolls_left_calls, [1, 0])

    def test_score_to_beat_removes_only_banked_non_upper_score(self):
        self.assertEqual(
            compute_tablebase_score_to_beat(target_final_score=280, player_total_score=150, upper_sum=70),
            236,
        )
        self.assertEqual(
            compute_tablebase_score_to_beat(target_final_score=280, player_total_score=70, upper_sum=70),
            316,
        )

    def test_keep_mask_is_interpreted_against_sorted_dice(self):
        self.assertEqual(keep_values_from_mask([6, 1, 5, 1, 3], 0b00011), [1, 1])

    def test_tablebase_ai_passes_projected_target_score_to_dll(self):
        ai = object.__new__(TablebaseAI)
        ai.lib = FakeTablebaseLib()
        ai.ctx = object()

        action, target, utility, _, _ = ai.get_optimal_move(
            open_categories=["ones", "chance"],
            current_dice=[6, 1, 5, 1, 3],
            rolls_left=2,
            upper_sum=70,
            yahtzee_scored=False,
            target_final_score=280,
            player_total_score=150,
        )

        self.assertEqual(ai.lib.captured_score_to_beat, 236)
        self.assertEqual(ai.lib.captured_rolls_left, 2)
        self.assertEqual(action, "keep")
        self.assertEqual(target, [1, 1])
        self.assertEqual(utility, 0.75)

    def test_restart_waits_for_old_game_modal_to_clear_and_clean_scorecard(self):
        page = FakeRestartPage()

        wait_for_new_game_after_restart(page, timeout_ms=1234)

        self.assertTrue(page.play_again.clicked)
        self.assertEqual(page.modal.waits, [("hidden", 1234)])
        self.assertEqual(len(page.waited_functions), 1)
        script, timeout = page.waited_functions[0]
        self.assertEqual(timeout, 1234)
        self.assertIn("yahtzeeScoreModal", script)
        self.assertIn("currentRoll", script)
        self.assertIn("data-cell", script)


    def test_tablebase_ready_requires_complete_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dll_path = root / "yahtzee_core.dll"
            bin_path = root / "tablebase.bin"
            meta_path = root / "tablebase.meta.json"

            dll_path.write_bytes(b"dll")
            bin_path.write_bytes(b"\0" * 8)

            self.assertFalse(is_tablebase_ready(dll_path, bin_path, expected_size=8))

            meta_path.write_text(json.dumps({
                "format_version": 1,
                "total_states": 1,
                "byte_size": 8,
                "solved_layer": 2,
                "scoring_rules_version": 2,
            }))
            self.assertFalse(is_tablebase_ready(dll_path, bin_path, expected_size=8))

            meta_path.write_text(json.dumps({
                "format_version": 1,
                "total_states": 1,
                "byte_size": 8,
                "solved_layer": 13,
            }))
            self.assertFalse(is_tablebase_ready(dll_path, bin_path, expected_size=8))

            meta_path.write_text(json.dumps({
                "format_version": 1,
                "scoring_rules_version": 2,
                "total_states": 1,
                "byte_size": 8,
                "solved_layer": 13,
            }))
            self.assertTrue(is_tablebase_ready(dll_path, bin_path, expected_size=8))


if __name__ == "__main__":
    unittest.main()
