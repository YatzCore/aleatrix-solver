import copy
import json
import os
import shutil
from pathlib import Path

from aleatrix_solver.opponent_history import is_valid_final_score, parse_int


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOOD_HISTORY_PATH = os.environ.get(
    "YAHTZEE_GAME_HISTORY_PATH",
    str(PROJECT_ROOT / "game_history.jsonl"),
)
BAD_HISTORY_PATH = os.environ.get(
    "YAHTZEE_BAD_GAME_HISTORY_PATH",
    str(PROJECT_ROOT / "game_history_bad.jsonl"),
)


def _count_scoring_actions(record):
    turns = record.get("turns", [])
    if not isinstance(turns, list):
        return 0
    return sum(1 for turn in turns if isinstance(turn, dict) and turn.get("action") == "score")


def classify_game_record(record):
    if not isinstance(record, dict):
        return {
            "is_valid": False,
            "invalid_reasons": ["malformed_record"],
            "scoring_action_count": 0,
            "valid_opponent_score_count": 0,
        }

    invalid_reasons = []
    scoring_action_count = _count_scoring_actions(record)
    if scoring_action_count != 13:
        invalid_reasons.append("unexpected_scoring_action_count")

    final_scores = record.get("final_scores")
    player_id = str(record.get("player_id"))
    valid_opponent_score_count = 0

    if not isinstance(final_scores, dict):
        invalid_reasons.append("missing_player_score")
        invalid_reasons.append("missing_opponent_score")
    else:
        if player_id not in final_scores:
            invalid_reasons.append("missing_player_score")
        else:
            player_score = parse_int(final_scores[player_id])
            if not is_valid_final_score(player_score):
                invalid_reasons.append("invalid_player_score")

        for score_id, score in final_scores.items():
            if str(score_id) == player_id:
                continue
            opponent_score = parse_int(score)
            if is_valid_final_score(opponent_score):
                valid_opponent_score_count += 1

        if valid_opponent_score_count == 0:
            invalid_reasons.append("invalid_opponent_score")

    return {
        "is_valid": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "scoring_action_count": scoring_action_count,
        "valid_opponent_score_count": valid_opponent_score_count,
    }


def quarantine_record(record, classification=None):
    classification = classification or classify_game_record(record)
    quarantined = copy.deepcopy(record) if isinstance(record, dict) else {"raw_record": record}
    quarantined["history_status"] = "quarantined"
    quarantined["invalid_reasons"] = list(classification["invalid_reasons"])
    quarantined["scoring_action_count"] = classification["scoring_action_count"]
    quarantined["valid_opponent_score_count"] = classification["valid_opponent_score_count"]
    return quarantined


def append_jsonl(path, record):
    history_path = Path(path)
    parent = history_path.parent
    if str(parent):
        os.makedirs(parent, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def save_routed_game_log(game_data, good_path=GOOD_HISTORY_PATH, bad_path=BAD_HISTORY_PATH):
    classification = classify_game_record(game_data)
    if classification["is_valid"]:
        append_jsonl(good_path, game_data)
    else:
        append_jsonl(bad_path, quarantine_record(game_data, classification))
    return classification


def malformed_line_record(raw_line):
    return {
        "history_status": "quarantined",
        "invalid_reasons": ["malformed_record"],
        "raw_line": raw_line,
    }


def iter_jsonl_records(path):
    history_path = Path(path)
    if not history_path.exists():
        return
    with history_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw_line = line.rstrip("\n")
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                yield malformed_line_record(raw_line)
                continue
            if isinstance(record, dict):
                yield record
            else:
                wrapper = malformed_line_record(raw_line)
                wrapper["parsed_value"] = record
                yield wrapper


def default_backup_path(good_path):
    history_path = Path(good_path)
    return history_path.with_name(history_path.name + ".bak")


def clean_history_file(good_path=GOOD_HISTORY_PATH, bad_path=BAD_HISTORY_PATH, backup_path=None, replace_backup=False):
    good_history_path = Path(good_path)
    bad_history_path = Path(bad_path)
    backup_history_path = Path(backup_path) if backup_path is not None else default_backup_path(good_history_path)

    if not good_history_path.exists():
        return {"kept": 0, "quarantined": 0, "malformed": 0, "backup_path": str(backup_history_path)}

    if backup_history_path.exists() and not replace_backup:
        raise FileExistsError(f"Backup already exists: {backup_history_path}")

    if str(backup_history_path.parent):
        os.makedirs(backup_history_path.parent, exist_ok=True)
    shutil.copy2(good_history_path, backup_history_path)

    kept_records = []
    quarantined_records = []
    malformed_count = 0

    for record in iter_jsonl_records(good_history_path):
        if record.get("invalid_reasons") == ["malformed_record"] and "raw_line" in record:
            quarantined_records.append(record)
            malformed_count += 1
            continue
        classification = classify_game_record(record)
        if classification["is_valid"]:
            kept_records.append(record)
        else:
            quarantined_records.append(quarantine_record(record, classification))

    with good_history_path.open("w", encoding="utf-8") as handle:
        for record in kept_records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    for record in quarantined_records:
        append_jsonl(bad_history_path, record)

    return {
        "kept": len(kept_records),
        "quarantined": len(quarantined_records),
        "malformed": malformed_count,
        "backup_path": str(backup_history_path),
    }
