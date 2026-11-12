"""Mixture solver: maximize win probability averaged over the opponent's final score.

Every legal action is ranked by its tablebase win probability averaged over a
distribution of the opponent's final score (see opponent_model). Exact ties
are broken by the exact expected remaining score.
"""

import time

from aleatrix_solver.opponent_model import distribution_mean, score_to_beat_weights
from aleatrix_solver.yahtzee_ai import CATEGORIES, get_score

TIE_TOLERANCE = 1e-9


def keep_values_from_mask(current_dice, target_mask):
    sorted_dice = sorted(int(die) for die in current_dice)
    return [sorted_dice[i] for i in range(5) if (int(target_mask) >> i) & 1]


def choose_mixture_move(
    tablebase_ai,
    open_categories,
    current_dice,
    rolls_left,
    upper_sum,
    yahtzee_scored,
    player_total_score,
    opponent_final_distribution,
    tie_tolerance=TIE_TOLERANCE,
):
    start_time = time.perf_counter()
    weights = score_to_beat_weights(opponent_final_distribution, player_total_score, upper_sum)

    lookup_start = time.perf_counter()
    ranked_moves = tablebase_ai.get_ranked_moves_weighted(
        open_categories=open_categories,
        current_dice=current_dice,
        rolls_left=rolls_left,
        upper_sum=upper_sum,
        yahtzee_scored=yahtzee_scored,
        weights=weights,
    )
    ev_moves = tablebase_ai.get_ranked_moves_ev(
        open_categories=open_categories,
        current_dice=current_dice,
        rolls_left=rolls_left,
        upper_sum=upper_sum,
        yahtzee_scored=yahtzee_scored,
    )
    lookup_seconds = time.perf_counter() - lookup_start
    if not ranked_moves:
        raise RuntimeError("tablebase returned no legal moves")

    ev_by_move = {(m["action_type"], m["target_idx"]): m["wp"] for m in ev_moves}
    for move in ranked_moves:
        move["ev"] = ev_by_move.get((move["action_type"], move["target_idx"]), float("-inf"))

    best_wp_move = ranked_moves[0]
    best_wp = best_wp_move["wp"]
    candidates = [m for m in ranked_moves if best_wp - m["wp"] <= tie_tolerance]
    chosen = max(candidates, key=lambda m: m["ev"])  # first wins on equal EV

    if chosen["action_type"] == 0:
        action = "score"
        target = CATEGORIES[chosen["target_idx"]]
        evs = {target: get_score(target, current_dice, yahtzee_scored)}
    else:
        action = "keep"
        target = keep_values_from_mask(current_dice, chosen["target_idx"])
        evs = {}

    wp_changed = chosen is not best_wp_move
    return {
        "action": action,
        "target": target,
        "utility": chosen["wp"],
        "evs": evs,
        "t_lookup": lookup_seconds,
        "decision_latency_seconds": time.perf_counter() - start_time,
        "tablebase_win_probability": best_wp,
        "score_fallback_used": False,
        "wp_changed": wp_changed,
        "full_keep_converted": False,
        "fallback_solver": "Exact EV tie-break" if wp_changed else None,
        "chosen_action_ev": chosen["ev"],
        "tablebase_action_ev": best_wp_move["ev"],
        "wp_drop": best_wp - chosen["wp"],
        "ev_gain": chosen["ev"] - best_wp_move["ev"],
        "num_candidates": len(candidates),
        "epsilon": tie_tolerance,
        "expected_final_score": player_total_score + chosen["ev"],
        "opponent_expected_final_score": distribution_mean(opponent_final_distribution),
    }
