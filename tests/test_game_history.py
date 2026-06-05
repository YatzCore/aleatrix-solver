import json
import tempfile
import unittest
from pathlib import Path

from scripts.clean_game_history import parse_args
from aleatrix_solver.game_history import (
    classify_game_record,
    clean_history_file,
    iter_jsonl_records,
    quarantine_record,
    save_routed_game_log,
)
import yahtzee_bot


def score_turn(category="chance"):
    return {"action": "score", "target": category}


def keep_turn():
    return {"action": "keep", "target": [1, 2]}


def complete_record(player_id="0", player_score=240, final_scores=None, score_count=13):
    if final_scores is None:
        final_scores = {str(player_id): player_score, "1": 225}
    turns = [score_turn() for _ in range(score_count)]
    return {
        "timestamp": "2026-06-05T10:00:00",
        "mode": "multiplayer",
        "player_id": str(player_id),
        "final_scores": final_scores,
        "turns": turns,
    }


class GameHistoryClassificationTests(unittest.TestCase):
    def test_classifies_complete_two_player_game_as_valid(self):
        result = classify_game_record(complete_record())

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["invalid_reasons"], [])
        self.assertEqual(result["scoring_action_count"], 13)
        self.assertEqual(result["valid_opponent_score_count"], 1)

    def test_classifies_multiplayer_game_with_one_valid_opponent_as_valid(self):
        record = complete_record(
            player_id="2",
            player_score=260,
            final_scores={"0": 55, "1": 311, "2": 260},
        )

        result = classify_game_record(record)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["valid_opponent_score_count"], 1)

    def test_rejects_less_than_13_bot_scoring_actions(self):
        record = complete_record(score_count=12)
        record["turns"].append(keep_turn())

        result = classify_game_record(record)

        self.assertFalse(result["is_valid"])
        self.assertIn("unexpected_scoring_action_count", result["invalid_reasons"])
        self.assertEqual(result["scoring_action_count"], 12)

    def test_rejects_more_than_13_bot_scoring_actions(self):
        result = classify_game_record(complete_record(score_count=14))

        self.assertFalse(result["is_valid"])
        self.assertIn("unexpected_scoring_action_count", result["invalid_reasons"])
        self.assertEqual(result["scoring_action_count"], 14)

    def test_rejects_missing_player_score(self):
        record = complete_record(final_scores={"1": 225})

        result = classify_game_record(record)

        self.assertFalse(result["is_valid"])
        self.assertIn("missing_player_score", result["invalid_reasons"])

    def test_rejects_invalid_player_score(self):
        record = complete_record(player_score=55)

        result = classify_game_record(record)

        self.assertFalse(result["is_valid"])
        self.assertIn("invalid_player_score", result["invalid_reasons"])

    def test_rejects_no_valid_opponent_score(self):
        record = complete_record(final_scores={"0": 240, "1": 0, "2": 75})

        result = classify_game_record(record)

        self.assertFalse(result["is_valid"])
        self.assertIn("invalid_opponent_score", result["invalid_reasons"])
        self.assertEqual(result["valid_opponent_score_count"], 0)

    def test_quarantine_record_keeps_original_fields_and_adds_metadata(self):
        record = complete_record(score_count=7)

        quarantined = quarantine_record(record)

        self.assertEqual(quarantined["history_status"], "quarantined")
        self.assertEqual(quarantined["scoring_action_count"], 7)
        self.assertIn("unexpected_scoring_action_count", quarantined["invalid_reasons"])
        self.assertEqual(quarantined["final_scores"], record["final_scores"])


class GameHistoryRoutingTests(unittest.TestCase):
    def test_save_routed_game_log_writes_valid_game_to_good_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "game_history.jsonl"
            bad_path = Path(tmp_dir) / "game_history_bad.jsonl"

            result = save_routed_game_log(complete_record(), good_path, bad_path)

            self.assertTrue(result["is_valid"])
            self.assertEqual(len(good_path.read_text(encoding="utf-8").splitlines()), 1)
            self.assertFalse(bad_path.exists())

    def test_save_routed_game_log_writes_bad_game_to_bad_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "game_history.jsonl"
            bad_path = Path(tmp_dir) / "game_history_bad.jsonl"

            result = save_routed_game_log(complete_record(score_count=3), good_path, bad_path)

            self.assertFalse(result["is_valid"])
            self.assertFalse(good_path.exists())
            quarantined = json.loads(bad_path.read_text(encoding="utf-8").strip())
            self.assertEqual(quarantined["history_status"], "quarantined")
            self.assertIn("unexpected_scoring_action_count", quarantined["invalid_reasons"])

    def test_iter_jsonl_records_preserves_malformed_line_as_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "game_history.jsonl"
            path.write_text("not-json\n" + json.dumps(complete_record()) + "\n", encoding="utf-8")

            entries = list(iter_jsonl_records(path))

            self.assertEqual(entries[0]["history_status"], "quarantined")
            self.assertEqual(entries[0]["invalid_reasons"], ["malformed_record"])
            self.assertEqual(entries[0]["raw_line"], "not-json")
            self.assertEqual(entries[1]["player_id"], "0")

    def test_clean_history_file_rewrites_good_history_and_appends_bad_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "game_history.jsonl"
            bad_path = Path(tmp_dir) / "game_history_bad.jsonl"
            backup_path = Path(tmp_dir) / "game_history.jsonl.bak"
            records = [
                complete_record(),
                complete_record(score_count=5),
            ]
            good_path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\nnot-json\n",
                encoding="utf-8",
            )

            result = clean_history_file(good_path, bad_path, backup_path=backup_path)

            self.assertEqual(result["kept"], 1)
            self.assertEqual(result["quarantined"], 2)
            self.assertEqual(result["malformed"], 1)
            self.assertTrue(backup_path.exists())
            kept_lines = good_path.read_text(encoding="utf-8").splitlines()
            bad_lines = bad_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(kept_lines), 1)
            self.assertEqual(len(bad_lines), 2)
            self.assertEqual(json.loads(kept_lines[0])["player_id"], "0")
            self.assertEqual(json.loads(bad_lines[1])["invalid_reasons"], ["malformed_record"])

    def test_clean_history_file_refuses_existing_backup_without_replace(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "game_history.jsonl"
            bad_path = Path(tmp_dir) / "game_history_bad.jsonl"
            backup_path = Path(tmp_dir) / "game_history.jsonl.bak"
            good_path.write_text(json.dumps(complete_record()) + "\n", encoding="utf-8")
            backup_path.write_text("existing backup\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                clean_history_file(good_path, bad_path, backup_path=backup_path)


class CleanGameHistoryCliTests(unittest.TestCase):
    def test_parse_args_accepts_custom_paths_and_replace_backup(self):
        args = parse_args([
            "--history-path", "history.jsonl",
            "--bad-history-path", "bad.jsonl",
            "--backup-path", "history.backup.jsonl",
            "--replace-backup",
        ])

        self.assertEqual(args.history_path, "history.jsonl")
        self.assertEqual(args.bad_history_path, "bad.jsonl")
        self.assertEqual(args.backup_path, "history.backup.jsonl")
        self.assertTrue(args.replace_backup)


class YahtzeeBotHistoryRoutingTests(unittest.TestCase):
    def test_bot_save_game_log_routes_bad_games_to_bad_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "game_history.jsonl"
            bad_path = Path(tmp_dir) / "game_history_bad.jsonl"
            original_good = yahtzee_bot.GAME_HISTORY_PATH
            original_bad = yahtzee_bot.BAD_GAME_HISTORY_PATH
            try:
                yahtzee_bot.GAME_HISTORY_PATH = str(good_path)
                yahtzee_bot.BAD_GAME_HISTORY_PATH = str(bad_path)

                result = yahtzee_bot.save_game_log(complete_record(score_count=2))
            finally:
                yahtzee_bot.GAME_HISTORY_PATH = original_good
                yahtzee_bot.BAD_GAME_HISTORY_PATH = original_bad

            self.assertFalse(result["is_valid"])
            self.assertFalse(good_path.exists())
            self.assertTrue(bad_path.exists())

    def test_bot_save_game_log_routes_complete_games_to_good_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "game_history.jsonl"
            bad_path = Path(tmp_dir) / "game_history_bad.jsonl"
            original_good = yahtzee_bot.GAME_HISTORY_PATH
            original_bad = yahtzee_bot.BAD_GAME_HISTORY_PATH
            try:
                yahtzee_bot.GAME_HISTORY_PATH = str(good_path)
                yahtzee_bot.BAD_GAME_HISTORY_PATH = str(bad_path)

                result = yahtzee_bot.save_game_log(complete_record())
            finally:
                yahtzee_bot.GAME_HISTORY_PATH = original_good
                yahtzee_bot.BAD_GAME_HISTORY_PATH = original_bad

            self.assertTrue(result["is_valid"])
            self.assertTrue(good_path.exists())
            self.assertFalse(bad_path.exists())


if __name__ == "__main__":
    unittest.main()
