"""Paired head-to-head evaluation of solver policies against a simulated opponent.

Each game is a real two-player game: the opponent plays its own dice with the
exact expected-score policy (optionally with mistakes), turns alternate, and
the policy under test only sees the opponent's scorecard as it stands at the
start of each of its turns. Every policy plays the same seeds, with the same
opponent games and the same dice tables (common random numbers), so the
results are paired and compared with an exact McNemar test.

Example:
    python scripts/run_mixture_evaluation.py --games 4000 --policies unified,mixture,ev

Policies: unified (current default), mixture (assumes an expected-score-optimal
opponent), mixture_cal (mixture with --mean-ratio/--std-ratio calibration, as
OpponentModel.from_history derives from logged games), ev (pure expected score).
"""

import argparse
import contextlib
import io
import math
import multiprocessing
import os
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aleatrix_solver.match_strategy import project_opponent_score  # noqa: E402
from aleatrix_solver.mixture_solver import choose_mixture_move  # noqa: E402
from aleatrix_solver.opponent_history import fit_opponent_projection_model  # noqa: E402
from aleatrix_solver.opponent_model import OpponentBoard, OpponentModel  # noqa: E402
from aleatrix_solver.tablebase_target import get_stabilized_tablebase_target  # noqa: E402
from aleatrix_solver.yahtzee_ai import CATEGORIES  # noqa: E402
from yahtzee_simulator import score_category  # noqa: E402

UPPER = set(CATEGORIES[:6])

_ai = None
_fallback_ai = None
_config = None


class Scorecard:
    def __init__(self):
        self.open = list(CATEGORIES)
        self.upper = 0
        self.total = 0
        self.yahtzee_scored = False

    def score(self, category, dice):
        result = score_category(category, dice, self.upper, self.yahtzee_scored)
        self.total += result["score"] + result["upper_bonus"] + result["yahtzee_bonus"]
        self.upper = result["upper_score"]
        self.yahtzee_scored = result["yahtzee_scored"]
        self.open.remove(category)

    def board(self):
        return OpponentBoard(self.total, self.open, self.upper, self.yahtzee_scored)


def dice_table(rng):
    """13 turns x 3 rolls x 5 dice; a roll rerolling k dice uses the first k values."""
    return [[[rng.randint(1, 6) for _ in range(5)] for _ in range(3)] for _ in range(13)]


def play_turn(card, table, choose):
    """Plays one turn; choose(dice, rolls_left) returns (action, target)."""
    dice = sorted(table[0])
    rolls_left = 2
    while True:
        action, target = choose(dice, rolls_left)
        if action == "score" or rolls_left == 0:
            card.score(target, dice)
            return
        kept = list(target)
        roll_index = 3 - rolls_left
        dice = sorted(kept + table[roll_index][: 5 - len(kept)])
        rolls_left -= 1


def ev_choice(card, rng=None, noise=0.0):
    def choose(dice, rolls_left):
        moves = _ai.get_ranked_moves_ev(card.open, dice, rolls_left, card.upper, card.yahtzee_scored)
        index = 1 if (rng is not None and noise > 0 and len(moves) > 1 and rng.random() < noise) else 0
        return move_to_action(moves[index], dice)
    return choose


def move_to_action(move, dice):
    if move["action_type"] == 0:
        return "score", CATEGORIES[move["target_idx"]]
    sorted_dice = sorted(dice)
    return "keep", [sorted_dice[i] for i in range(5) if (move["target_idx"] >> i) & 1]


def play_opponent_game(seed, noise):
    """Returns the opponent's scorecard after each of its 13 turns."""
    rng = random.Random(seed * 7919 + 1)
    tables = dice_table(rng)
    card = Scorecard()
    boards = []
    for turn in range(13):
        play_turn(card, tables[turn], ev_choice(card, rng, noise))
        boards.append(card.board())
    return boards


def make_policy(name, card, opponent_view, state):
    """Returns choose(dice, rolls_left) for the policy under test."""
    if name == "ev":
        return ev_choice(card)

    if name in ("mixture", "mixture_cal"):
        model = _config["opponent_model" if name == "mixture" else "calibrated_model"]

        def choose(dice, rolls_left):
            distribution = model.final_score_distribution(opponent_view)
            move = choose_mixture_move(
                _ai, card.open, dice, rolls_left, card.upper, card.yahtzee_scored, card.total, distribution
            )
            return move["action"], move["target"]
        return choose

    if name == "unified":
        from yahtzee_bot import choose_unified_move

        def choose(dice, rolls_left):
            opp_score = opponent_view.score
            projected = None
            if opp_score > 0:
                projected = project_opponent_score(
                    opp_score,
                    len(card.open),
                    projection_model=_config["projection_model"],
                    percentile=_config["opponent_risk_percentile"],
                )
            target = get_stabilized_tablebase_target(
                open_category_count=len(card.open),
                projected_opponent_score=projected,
                target_score=None,
                opponent_score=opp_score,
                previous_target=state.get("previous_target"),
            )
            state["previous_target"] = target
            with contextlib.redirect_stdout(io.StringIO()):
                move = choose_unified_move(
                    tablebase_ai=_ai,
                    score_fallback_ai=_fallback_ai,
                    open_categories=card.open,
                    current_dice=dice,
                    rolls_left=rolls_left,
                    upper_sum=card.upper,
                    yahtzee_scored=card.yahtzee_scored,
                    target_final_score=target,
                    player_total_score=card.total,
                    epsilon="dynamic_v1",
                )
            return move["action"], move["target"]
        return choose

    raise ValueError(f"unknown policy {name}")


def init_worker(dll_path, bin_path, ev_cache_path, policies, mean_ratio, std_ratio):
    global _ai, _fallback_ai, _config
    from yahtzee_bot import TablebaseAI

    _ai = TablebaseAI(dll_path, bin_path, ev_cache_path=ev_cache_path)
    if "unified" in policies:
        from aleatrix_solver.strategy_config import DEFAULT_STRATEGY_CONFIG, create_tablebase_fallback_ai
        _fallback_ai, _ = create_tablebase_fallback_ai(DEFAULT_STRATEGY_CONFIG, verbose=False)
    _config = {
        "opponent_model": OpponentModel(_ai.get_remaining_score_moments),
        "calibrated_model": OpponentModel(_ai.get_remaining_score_moments, mean_ratio, std_ratio),
        "projection_model": fit_opponent_projection_model([]),
        "opponent_risk_percentile": 85,
    }


def run_game(task):
    seed, policies, noise = task
    opponent_boards = play_opponent_game(seed, noise)
    opponent_final = opponent_boards[-1].score
    opponent_first = seed % 2 == 0
    my_tables = dice_table(random.Random(seed * 104729 + 3))

    results = {}
    for name in policies:
        card = Scorecard()
        state = {}
        for turn in range(13):
            opponent_turns_done = turn + 1 if opponent_first else turn
            view = opponent_boards[opponent_turns_done - 1] if opponent_turns_done else Scorecard().board()
            play_turn(card, my_tables[turn], make_policy(name, card, view, state))
        results[name] = card.total
    return seed, opponent_final, results


def exact_mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--policies", default="unified,mixture,ev")
    parser.add_argument("--opponent-noise", type=float, default=0.0,
                        help="Probability the opponent plays its second-best move at each decision.")
    parser.add_argument("--mean-ratio", type=float, default=1.0,
                        help="Opponent-strength calibration used by the mixture_cal policy.")
    parser.add_argument("--std-ratio", type=float, default=1.0,
                        help="Opponent-spread calibration used by the mixture_cal policy.")
    parser.add_argument("--workers", type=int, default=multiprocessing.cpu_count())
    parser.add_argument("--bin", default=str(PROJECT_ROOT / "cpp" / "tablebase.bin"))
    parser.add_argument("--lib", default=None)
    parser.add_argument("--ev-cache", default=str(PROJECT_ROOT / "cpp" / "ev_table.bin"))
    args = parser.parse_args()

    from yahtzee_bot import default_library_path, TablebaseAI

    lib_path = args.lib or default_library_path(str(PROJECT_ROOT))
    policies = [p.strip() for p in args.policies.split(",") if p.strip()]
    TablebaseAI.ev_only(lib_path, ev_cache_path=args.ev_cache)  # build the EV cache once

    tasks = [(args.seed * 1_000_003 + i, policies, args.opponent_noise) for i in range(args.games)]
    start = time.time()
    rows = []
    with multiprocessing.Pool(args.workers, initializer=init_worker,
                              initargs=(lib_path, args.bin, args.ev_cache, policies, args.mean_ratio, args.std_ratio)) as pool:
        for i, row in enumerate(pool.imap_unordered(run_game, tasks, chunksize=4)):
            rows.append(row)
            if (i + 1) % max(1, args.games // 10) == 0:
                print(f"  {i + 1}/{args.games} games ({time.time() - start:.0f}s)", flush=True)

    opp_scores = [r[1] for r in rows]
    print(f"\nOpponent: noise={args.opponent_noise}, mean final {sum(opp_scores) / len(opp_scores):.1f}")
    print(f"{'policy':<10}{'win %':>8}{'tie %':>8}{'mean':>9}")
    wins = {}
    for name in policies:
        w = [r[2][name] > r[1] for r in rows]
        t = sum(r[2][name] == r[1] for r in rows)
        wins[name] = w
        mean = sum(r[2][name] for r in rows) / len(rows)
        print(f"{name:<10}{100 * sum(w) / len(rows):>8.2f}{100 * t / len(rows):>8.2f}{mean:>9.1f}")

    print("\nPaired comparisons (games won by one policy and lost by the other):")
    for i, a in enumerate(policies):
        for bname in policies[i + 1:]:
            only_a = sum(x and not y for x, y in zip(wins[a], wins[bname]))
            only_b = sum(y and not x for x, y in zip(wins[a], wins[bname]))
            print(f"  {a} vs {bname}: {only_a} vs {only_b} "
                  f"(net {100 * (only_a - only_b) / len(rows):+.2f} pp, McNemar p={exact_mcnemar(only_a, only_b):.4f})")
    print(f"\nTotal time {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
