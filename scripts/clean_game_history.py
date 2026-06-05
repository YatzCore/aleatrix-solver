import argparse
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aleatrix_solver.game_history import BAD_HISTORY_PATH, GOOD_HISTORY_PATH, clean_history_file


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Move incomplete or dirty Yahtzee game logs out of the default history."
    )
    parser.add_argument("--history-path", default=GOOD_HISTORY_PATH, help="JSONL history file to clean.")
    parser.add_argument(
        "--bad-history-path",
        default=BAD_HISTORY_PATH,
        help="JSONL quarantine file to append bad records to.",
    )
    parser.add_argument("--backup-path", default=None, help="Backup path. Defaults to <history-path>.bak.")
    parser.add_argument(
        "--replace-backup",
        action="store_true",
        help="Allow replacing an existing backup file.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = clean_history_file(
        args.history_path,
        args.bad_history_path,
        backup_path=args.backup_path,
        replace_backup=args.replace_backup,
    )
    print(
        "History cleanup complete: "
        f"kept={result['kept']} "
        f"quarantined={result['quarantined']} "
        f"malformed={result['malformed']} "
        f"backup={result['backup_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
