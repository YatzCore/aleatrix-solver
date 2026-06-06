import random
import argparse
import os
from pathlib import Path
from statistics import mean

from aleatrix_solver.yahtzee_ai import CATEGORIES, UPPER_CATEGORIES, get_score
from aleatrix_solver.match_strategy import choose_risk_level, project_opponent_score
from aleatrix_solver.tablebase_target import (
    TABLEBASE_SCORE_FALLBACK_THRESHOLD,
    choose_tablebase_target_score,
    get_stabilized_tablebase_target,
    should_use_score_fallback,
)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HISTORY_PATH = os.environ.get(
    "YAHTZEE_GAME_HISTORY_PATH",
    str(PROJECT_ROOT / "game_history.jsonl"),
)
VALIDATION_MODE_LIVE_LIKE = "live-like"
VALIDATION_MODE_ORACLE_TARGET = "oracle-target"


def is_tablebase_ai(ai):
    return bool(getattr(ai, "is_tablebase_ai", False))


def get_epsilon_value(policy_name, wp):
    if policy_name in ("dynamic", "dynamic_v1"):
        if wp >= 0.80: return 0.001
        if wp >= 0.50: return 0.0025
        if wp >= 0.20: return 0.005
        if wp >= 0.075: return 0.01
        return 0.03
    elif policy_name == "dynamic_no_desperation":
        if wp >= 0.80: return 0.001
        if wp >= 0.50: return 0.0025
        if wp >= 0.20: return 0.005
        if wp >= 0.075: return 0.01
        return 0.0
    elif policy_name == "dynamic_no_mid":
        if wp >= 0.80: return 0.001
        if wp >= 0.50: return 0.0
        if wp >= 0.20: return 0.0
        if wp >= 0.075: return 0.01
        return 0.03
    elif policy_name == "dynamic_strict_safe":
        if wp >= 0.80: return 0.0
        if wp >= 0.50: return 0.0025
        if wp >= 0.20: return 0.005
        if wp >= 0.075: return 0.01
        return 0.03
    elif policy_name == "dynamic_conservative":
        if wp >= 0.80: return 0.0
        if wp >= 0.50: return 0.001
        if wp >= 0.20: return 0.0025
        if wp >= 0.075: return 0.005
        return 0.01
    elif policy_name == "dynamic_aggressive":
        if wp >= 0.80: return 0.0025
        if wp >= 0.50: return 0.005
        if wp >= 0.20: return 0.01
        if wp >= 0.075: return 0.02
        return 0.05
    else:
        try:
            return float(policy_name)
        except Exception:
            return 0.0


choose_win_probability_target = choose_tablebase_target_score


def roll_dice(rng, count):
    return tuple(sorted(rng.randint(1, 6) for _ in range(count)))


def score_category(category, dice, upper_score, yahtzee_scored):
    score = get_score(category, dice, yahtzee_scored)
    yahtzee_bonus = 0
    if category != "yahtzee" and len(set(dice)) == 1 and yahtzee_scored:
        yahtzee_bonus = 100

    upper_bonus = 0
    new_upper_score = upper_score
    if category in UPPER_CATEGORIES:
        new_upper_score += score
        if upper_score < 63 <= new_upper_score:
            upper_bonus = 35

    new_yahtzee_scored = yahtzee_scored or (category == "yahtzee" and score == 50)
    return {
        "score": score,
        "upper_bonus": upper_bonus,
        "yahtzee_bonus": yahtzee_bonus,
        "upper_score": new_upper_score,
        "yahtzee_scored": new_yahtzee_scored,
    }


def estimate_simulated_opponent_score(final_score, open_category_count, total_categories=13):
    if final_score is None:
        return 0
    open_count = max(0, min(total_categories, int(open_category_count)))
    completed_turns = total_categories - open_count
    return int(round(final_score * completed_turns / total_categories))


def play_solo_game(
    ai,
    seed=None,
    rng=None,
    target_score=None,
    opponent_score=0,
    simulated_opponent_final_score=None,
    use_opponent_projection=False,
    projection_model=None,
    opponent_risk_percentile=75,
    score_fallback_ai=None,
    tablebase_fallback_threshold=TABLEBASE_SCORE_FALLBACK_THRESHOLD,
    epsilon=None,
    unified_mode=False,
):
    def keep_values_from_mask(current_dice, target_mask):
        sorted_dice = sorted(int(die) for die in current_dice)
        return [sorted_dice[i] for i in range(5) if (int(target_mask) >> i) & 1]

    rng = rng or random.Random(seed)
    open_categories = list(CATEGORIES)
    upper_score = 0
    lower_score = 0
    bonus_score = 0
    yahtzee_scored = False
    turns = []
    scored_categories = []
    current_tablebase_target = None

    while open_categories:
        dice = roll_dice(rng, 5)
        rolls_left = 2
        decisions = []

        while True:
            current_total = upper_score + lower_score + bonus_score

            current_opp_score = opponent_score
            if use_opponent_projection and simulated_opponent_final_score is not None:
                current_opp_score = estimate_simulated_opponent_score(
                    simulated_opponent_final_score,
                    len(open_categories),
                )

            projected = None
            if use_opponent_projection and current_opp_score > 0:
                projected = project_opponent_score(
                    current_opp_score,
                    len(open_categories),
                    projection_model=projection_model,
                    percentile=opponent_risk_percentile,
                )

            risk_level = choose_risk_level(
                current_total,
                current_opp_score,
                len(open_categories),
                target_score=target_score,
                projected_opponent_score=projected,
            )
            tablebase_target_score = None
            if is_tablebase_ai(ai):
                tablebase_target_score = get_stabilized_tablebase_target(
                    open_category_count=len(open_categories),
                    projected_opponent_score=projected,
                    target_score=target_score,
                    opponent_score=current_opp_score,
                    previous_target=current_tablebase_target,
                )
                current_tablebase_target = tablebase_target_score

                if unified_mode:
                    ranked_moves = ai.get_ranked_moves(
                        open_categories=open_categories,
                        current_dice=dice,
                        rolls_left=rolls_left,
                        upper_sum=upper_score,
                        yahtzee_scored=yahtzee_scored,
                        target_final_score=tablebase_target_score,
                        player_total_score=current_total,
                    )
                    best_wp = ranked_moves[0]["wp"]
                    current_epsilon = get_epsilon_value(epsilon, best_wp)

                    candidates = [
                        m for m in ranked_moves
                        if best_wp - m["wp"] <= current_epsilon + 1e-12
                    ]

                    num_candidates = len(candidates)
                    ev_calls = 0
                    wp_changed = False

                    for m in candidates:
                        ev_val = score_fallback_ai.evaluate_action_ev(
                            open_categories=open_categories,
                            current_dice=dice,
                            rolls_left=rolls_left,
                            upper_sum=upper_score,
                            yahtzee_scored=yahtzee_scored,
                            action_type=m["action_type"],
                            target_idx=m["target_idx"],
                            risk_level=0.0
                        )
                        m["ev"] = ev_val
                        ev_calls += 1

                    best_candidate = max(candidates, key=lambda m: m["ev"])

                    best_wp_move = ranked_moves[0]
                    tablebase_action_ev = best_wp_move.get("ev", -999999.0)
                    chosen_action_ev = best_candidate["ev"]
                    ev_gain = chosen_action_ev - tablebase_action_ev
                    wp_drop = best_wp - best_candidate["wp"]

                    tb_action_kind = "score" if best_wp_move["action_type"] == 0 else "keep"
                    tb_action_mask = best_wp_move["target_idx"] if best_wp_move["action_type"] == 1 else None
                    tb_action_cat = CATEGORIES[best_wp_move["target_idx"]] if best_wp_move["action_type"] == 0 else None

                    chosen_action_kind = "score" if best_candidate["action_type"] == 0 else "keep"
                    chosen_action_mask = best_candidate["target_idx"] if best_candidate["action_type"] == 1 else None
                    chosen_action_cat = CATEGORIES[best_candidate["target_idx"]] if best_candidate["action_type"] == 0 else None

                    if best_candidate["target_idx"] != ranked_moves[0]["target_idx"] or best_candidate["action_type"] != ranked_moves[0]["action_type"]:
                        wp_changed = True

                    if best_candidate["action_type"] == 0:
                        action = "score"
                        target = CATEGORIES[best_candidate["target_idx"]]
                    else:
                        action = "keep"
                        target_mask = best_candidate["target_idx"]
                        target = keep_values_from_mask(dice, target_mask)

                    utility = best_candidate["wp"]
                    tablebase_win_probability = best_wp
                    score_fallback_used = False
                    full_keep_converted = False
                    fallback_solver = "Unified Evaluator"

                    if action == "keep" and len(target) == 5:
                        rolls_0_moves = ai.get_ranked_moves(
                            open_categories=open_categories,
                            current_dice=dice,
                            rolls_left=0,
                            upper_sum=upper_score,
                            yahtzee_scored=yahtzee_scored,
                            target_final_score=tablebase_target_score,
                            player_total_score=current_total,
                        )

                        candidates_0 = [
                            m for m in rolls_0_moves
                            if best_wp - m["wp"] <= current_epsilon + 1e-12
                        ]

                        if candidates_0:
                            for m in candidates_0:
                                ev_val = score_fallback_ai.evaluate_action_ev(
                                    open_categories=open_categories,
                                    current_dice=dice,
                                    rolls_left=0,
                                    upper_sum=upper_score,
                                    yahtzee_scored=yahtzee_scored,
                                    action_type=m["action_type"],
                                    target_idx=m["target_idx"],
                                    risk_level=0.0
                                )
                                m["ev"] = ev_val
                                ev_calls += 1

                            best_candidate_0 = max(candidates_0, key=lambda m: m["ev"])

                            best_wp_move_0 = rolls_0_moves[0]
                            if "ev" not in best_wp_move_0:
                                best_wp_move_0["ev"] = score_fallback_ai.evaluate_action_ev(
                                    open_categories=open_categories,
                                    current_dice=dice,
                                    rolls_left=0,
                                    upper_sum=upper_score,
                                    yahtzee_scored=yahtzee_scored,
                                    action_type=best_wp_move_0["action_type"],
                                    target_idx=best_wp_move_0["target_idx"],
                                    risk_level=0.0,
                                )
                                ev_calls += 1
                            tablebase_action_ev = best_wp_move_0["ev"]
                            chosen_action_ev = best_candidate_0["ev"]
                            ev_gain = chosen_action_ev - tablebase_action_ev
                            wp_drop = best_wp - best_candidate_0["wp"]

                            tb_action_kind = "score" if best_wp_move_0["action_type"] == 0 else "keep"
                            tb_action_mask = best_wp_move_0["target_idx"] if best_wp_move_0["action_type"] == 1 else None
                            tb_action_cat = CATEGORIES[best_wp_move_0["target_idx"]] if best_wp_move_0["action_type"] == 0 else None

                            chosen_action_kind = "score" if best_candidate_0["action_type"] == 0 else "keep"
                            chosen_action_mask = best_candidate_0["target_idx"] if best_candidate_0["action_type"] == 1 else None
                            chosen_action_cat = CATEGORIES[best_candidate_0["target_idx"]] if best_candidate_0["action_type"] == 0 else None

                            wp_changed = wp_changed or (
                                best_candidate_0["target_idx"] != best_wp_move_0["target_idx"]
                                or best_candidate_0["action_type"] != best_wp_move_0["action_type"]
                            )

                            action = "score"
                            target = CATEGORIES[best_candidate_0["target_idx"]]
                            utility = best_candidate_0["wp"]
                            best_candidate = best_candidate_0
                            num_candidates = len(candidates_0)
                            full_keep_converted = True

                    evs = {cat: get_score(cat, dice, yahtzee_scored) for cat in open_categories}

                    decision_entry = {
                        "rolls_left": rolls_left,
                        "roll_index": 3 - rolls_left,
                        "decision_type": "keep" if action == "keep" else "score",
                        "dice": list(dice),
                        "action": action,
                        "target": target if isinstance(target, str) else list(target),
                        "utility": float(utility),
                        "risk_level": risk_level,
                        "opponent_score": current_opp_score,
                        "projected_opponent_score": projected,
                        "tablebase_target_score": tablebase_target_score,
                        "tablebase_win_probability": float(best_wp),
                        "score_fallback_used": False,
                        "full_keep_converted": full_keep_converted,
                        "fallback_solver": "Unified Evaluator",
                        "num_candidates": num_candidates,
                        "ev_calls": ev_calls,
                        "wp_changed": wp_changed,

                        "best_wp": float(best_wp),
                        "chosen_wp": float(best_candidate["wp"]),
                        "wp_drop": float(wp_drop),

                        "tablebase_action": {
                            "kind": tb_action_kind,
                            "mask": tb_action_mask,
                            "category": tb_action_cat
                        },
                        "chosen_action": {
                            "kind": chosen_action_kind,
                            "mask": chosen_action_mask,
                            "category": chosen_action_cat
                        },
                        "tablebase_action_ev": float(tablebase_action_ev),
                        "chosen_action_ev": float(chosen_action_ev),
                        "ev_gain": float(ev_gain),

                        "candidate_count": num_candidates,
                        "epsilon": float(current_epsilon),
                        "policy_name": epsilon,
                        "turn_index": 14 - len(open_categories),
                    }
                else:
                    move = ai.get_optimal_move(
                        open_categories=open_categories,
                        current_dice=dice,
                        rolls_left=rolls_left,
                        upper_sum=upper_score,
                        yahtzee_scored=yahtzee_scored,
                        target_final_score=tablebase_target_score,
                        player_total_score=current_total,
                    )
                    action, target, utility, evs = move[:4]
                    tablebase_win_probability = float(utility)
                    score_fallback_used = False
                    full_keep_converted = False
                    fallback_solver = None
                    num_candidates = None
                    ev_calls = None
                    wp_changed = None

                    if action == "keep" and len(target) == 5:
                        move = ai.get_optimal_move(
                            open_categories=open_categories,
                            current_dice=dice,
                            rolls_left=0,
                            upper_sum=upper_score,
                            yahtzee_scored=yahtzee_scored,
                            target_final_score=tablebase_target_score,
                            player_total_score=current_total,
                        )
                        action, target, utility, evs = move[:4]
                        full_keep_converted = True
                    if (
                        score_fallback_ai is not None
                        and should_use_score_fallback(
                            tablebase_win_probability,
                            tablebase_fallback_threshold,
                            action=action,
                            target=target,
                            evs=evs,
                            target_score=tablebase_target_score,
                            player_total_score=current_total,
                            open_categories=open_categories,
                        )
                    ):
                        action, target, utility, evs = score_fallback_ai.get_optimal_move(
                            open_categories=open_categories,
                            current_dice=dice,
                            rolls_left=0 if full_keep_converted else rolls_left,
                            upper_sum=upper_score,
                            yahtzee_scored=yahtzee_scored,
                            risk_level=0.0,
                        )
                        fallback_solver = getattr(score_fallback_ai, "fallback_solver_name", "Expectiminimax")
                        if action == "keep" and len(target) == 5:
                            action, target, utility, evs = score_fallback_ai.get_optimal_move(
                                open_categories=open_categories,
                                current_dice=dice,
                                rolls_left=0,
                                upper_sum=upper_score,
                                yahtzee_scored=yahtzee_scored,
                                risk_level=0.0,
                            )
                            full_keep_converted = True
                        score_fallback_used = True

                    decision_entry = {
                        "rolls_left": rolls_left,
                        "roll_index": 3 - rolls_left,
                        "decision_type": "keep" if action == "keep" else "score",
                        "dice": list(dice),
                        "action": action,
                        "target": target if isinstance(target, str) else list(target),
                        "utility": float(utility),
                        "risk_level": risk_level,
                        "opponent_score": current_opp_score,
                        "projected_opponent_score": projected,
                        "tablebase_target_score": tablebase_target_score,
                        "tablebase_win_probability": tablebase_win_probability,
                        "score_fallback_used": score_fallback_used,
                        "full_keep_converted": full_keep_converted,
                        "fallback_solver": fallback_solver,
                        "num_candidates": num_candidates,
                        "ev_calls": ev_calls,
                        "wp_changed": wp_changed,

                        "best_wp": tablebase_win_probability,
                        "chosen_wp": float(utility) if utility is not None else None,
                        "wp_drop": 0.0,
                        "tablebase_action": None,
                        "chosen_action": None,
                        "tablebase_action_ev": None,
                        "chosen_action_ev": None,
                        "ev_gain": 0.0,
                        "candidate_count": None,
                        "epsilon": None,
                        "policy_name": None,
                        "turn_index": 14 - len(open_categories),
                    }
            else:
                action, target, utility, evs = ai.get_optimal_move(
                    open_categories=open_categories,
                    current_dice=dice,
                    rolls_left=rolls_left,
                    upper_sum=upper_score,
                    yahtzee_scored=yahtzee_scored,
                    risk_level=risk_level,
                )
                tablebase_win_probability = None
                score_fallback_used = False
                full_keep_converted = False
                fallback_solver = None
                num_candidates = None
                ev_calls = None
                wp_changed = None

                decision_entry = {
                    "rolls_left": rolls_left,
                    "roll_index": 3 - rolls_left,
                    "decision_type": "keep" if action == "keep" else "score",
                    "dice": list(dice),
                    "action": action,
                    "target": target if isinstance(target, str) else list(target),
                    "utility": float(utility) if utility is not None else None,
                    "risk_level": risk_level,
                    "opponent_score": current_opp_score,
                    "projected_opponent_score": projected,
                    "tablebase_target_score": tablebase_target_score,
                    "tablebase_win_probability": tablebase_win_probability,
                    "score_fallback_used": score_fallback_used,
                    "full_keep_converted": full_keep_converted,
                    "fallback_solver": fallback_solver,
                    "num_candidates": num_candidates,
                    "ev_calls": ev_calls,
                    "wp_changed": wp_changed,

                    "best_wp": tablebase_win_probability,
                    "chosen_wp": float(utility) if utility is not None else None,
                    "wp_drop": 0.0,
                    "tablebase_action": None,
                    "chosen_action": None,
                    "tablebase_action_ev": None,
                    "chosen_action_ev": None,
                    "ev_gain": 0.0,
                    "candidate_count": None,
                    "epsilon": None,
                    "policy_name": None,
                    "turn_index": 14 - len(open_categories),
                }

            decisions.append(decision_entry)

            if action == "score" or rolls_left == 0:
                category = target if action == "score" else open_categories[0]
                scoring = score_category(category, dice, upper_score, yahtzee_scored)
                upper_score = scoring["upper_score"]
                yahtzee_scored = scoring["yahtzee_scored"]
                bonus_score += scoring["upper_bonus"] + scoring["yahtzee_bonus"]
                if category not in UPPER_CATEGORIES:
                    lower_score += scoring["score"]

                open_categories.remove(category)
                scored_categories.append(category)
                turns.append({
                    "category": category,
                    "score": scoring["score"],
                    "upper_bonus": scoring["upper_bonus"],
                    "yahtzee_bonus": scoring["yahtzee_bonus"],
                    "decisions": decisions,
                })
                break

            keep = tuple(target)
            dice = tuple(sorted(keep + roll_dice(rng, 5 - len(keep))))
            rolls_left -= 1

    final_score = upper_score + lower_score + bonus_score
    return {
        "final_score": final_score,
        "upper_score": upper_score,
        "lower_score": lower_score,
        "bonus_score": bonus_score,
        "turns": turns,
        "scored_categories": scored_categories,
        "target_score": target_score,
    }


def run_simulation(ai, games=100, seed=1, target_score=None):
    master_rng = random.Random(seed)
    game_seeds = [master_rng.randrange(2**32) for _ in range(games)]
    scores = [
        play_solo_game(ai, seed=game_seed, target_score=target_score)["final_score"]
        for game_seed in game_seeds
    ]

    return summarize_scores(scores, games, seed, target_score=target_score)


def summarize_scores(scores, games, seed, target_score=None):
    return {
        "games": games,
        "seed": seed,
        "target_score": target_score,
        "scores": scores,
        "average_score": mean(scores) if scores else 0.0,
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
    }


def summarize_match_results(scores, opponent_scores):
    if len(scores) != len(opponent_scores):
        raise ValueError("scores and opponent_scores must have the same length")

    wins = 0
    losses = 0
    ties = 0
    for score, opponent_score in zip(scores, opponent_scores):
        if score > opponent_score:
            wins += 1
        elif score < opponent_score:
            losses += 1
        else:
            ties += 1

    games = len(scores)
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": wins / games if games else 0.0,
        "non_loss_rate": (wins + ties) / games if games else 0.0,
    }


def compare_strategies(strategies, games=100, seed=1, target_score=None):
    master_rng = random.Random(seed)
    game_seeds = [master_rng.randrange(2**32) for _ in range(games)]
    comparison = {}

    for name, ai in strategies:
        scores = [
            play_solo_game(ai, seed=game_seed, target_score=target_score)["final_score"]
            for game_seed in game_seeds
        ]
        comparison[name] = summarize_scores(scores, games, seed, target_score=target_score)

    return comparison


def repeat_opponent_scores(opponent_scores, games):
    if not opponent_scores:
        return []
    return [opponent_scores[i % len(opponent_scores)] for i in range(games)]


def compare_strategies_against_opponents(
    strategies,
    opponent_scores,
    games=100,
    seed=1,
    validation_mode=VALIDATION_MODE_LIVE_LIKE,
    target_score=None,
    projection_model=None,
    history_path=DEFAULT_HISTORY_PATH,
):
    from aleatrix_solver.opponent_history import build_opponent_profile

    if validation_mode not in (VALIDATION_MODE_LIVE_LIKE, VALIDATION_MODE_ORACLE_TARGET):
        raise ValueError("validation_mode must be 'live-like' or 'oracle-target'")
    profile = None
    if projection_model is None or (target_score is None and validation_mode == VALIDATION_MODE_LIVE_LIKE):
        profile = build_opponent_profile(history_path)
    if projection_model is None:
        projection_model = profile["projection_model"]
    if target_score is None and validation_mode == VALIDATION_MODE_LIVE_LIKE:
        target_score = profile["target_score"]

    sampled_opponents = repeat_opponent_scores(opponent_scores, games)
    master_rng = random.Random(seed)
    game_seeds = [master_rng.randrange(2**32) for _ in range(games)]
    comparison = {}

    for name, ai in strategies:
        percentile = getattr(ai, "opponent_risk_percentile", 75)

        scores = []
        for game_seed, opp_score in zip(game_seeds, sampled_opponents):
            if validation_mode == VALIDATION_MODE_ORACLE_TARGET:
                game_target_score = opp_score
                simulated_final_score = None
                use_projection = False
            else:
                game_target_score = target_score
                simulated_final_score = opp_score
                use_projection = True

            res = play_solo_game(
                ai,
                seed=game_seed,
                target_score=game_target_score,
                opponent_score=0,
                simulated_opponent_final_score=simulated_final_score,
                use_opponent_projection=use_projection,
                projection_model=projection_model,
                opponent_risk_percentile=percentile,
            )
            scores.append(res["final_score"])

        comparison[name] = summarize_scores(scores, games, seed, target_score=target_score)
        comparison[name]["validation_mode"] = validation_mode
        comparison[name]["opponent_scores"] = sampled_opponents
        comparison[name]["match_summary"] = summarize_match_results(scores, sampled_opponents)

    return comparison


def parse_depth_specs(spec):
    depths = []
    for item in spec.split(","):
        exact_text, lower_text = item.strip().split(":", 1)
        depths.append((int(exact_text), int(lower_text)))
    return depths


def parse_risk_specs(spec):
    return [float(item.strip()) for item in spec.split(",")]


def print_summary(summary):
    print(f"Games: {summary['games']}")
    print(f"Average score: {summary['average_score']:.2f}")
    print(f"Min score: {summary['min_score']}")
    print(f"Max score: {summary['max_score']}")
    if summary["target_score"] is not None:
        target_scores = [summary["target_score"]] * summary["games"]
        match_summary = summarize_match_results(summary["scores"], target_scores)
        print(f"Target score: {summary['target_score']}")
        print(f"Target win rate: {match_summary['win_rate']:.3f}")


def print_ranked_strategies(ranked):
    for index, row in enumerate(ranked, start=1):
        print(f"{index}. {row['name']}")
        print(f"   Average score: {row['average_score']:.2f}")
        print(f"   Min/Max score: {row['min_score']} / {row['max_score']}")
        if row["target_score"] is not None:
            print(f"   Target score: {row['target_score']}")
            print(f"   Target win rate: {row['target_win_rate']:.3f}")
        if row["opponent_win_rate"] is not None:
            print(f"   Opponent win rate: {row['opponent_win_rate']:.3f}")


def resolve_target_score(target_score, history_path):
    if target_score is not None:
        return target_score
    if history_path is None:
        return None

    from aleatrix_solver.opponent_history import build_opponent_profile

    profile = build_opponent_profile(history_path)
    return profile["target_score"]


def parse_args():
    parser = argparse.ArgumentParser(description="Run deterministic Yahtzee AI simulations.")
    parser.add_argument("--games", type=int, default=100, help="Number of games to simulate.")
    parser.add_argument("--seed", type=int, default=1, help="Master random seed.")
    parser.add_argument("--target-score", type=int, help="Score target used for risk pressure and win-rate output.")
    parser.add_argument(
        "--history-path",
        help="JSONL game history path used to derive target score when --target-score is omitted.",
    )
    parser.add_argument(
        "--compare-depths",
        help="Comma-separated exact:lower-only DP depth specs, for example 4:5,3:4.",
    )
    parser.add_argument(
        "--compare-risk",
        help="Comma-separated risk multiplier values, for example 0.5,1,2.",
    )
    parser.add_argument("--tune-grid", action="store_true", help="Grid search DP depth and risk multiplier settings.")
    parser.add_argument("--depths", default="4:5,3:4", help="Depth specs for --tune-grid.")
    parser.add_argument("--risks", default="0.5,1,1.5,2", help="Risk multipliers for --tune-grid.")
    parser.add_argument("--write-config", help="Write the top-ranked --tune-grid strategy to this JSON config path.")
    parser.add_argument(
        "--objective",
        choices=["target-win-rate", "opponent-win-rate", "average-score"],
        default="target-win-rate",
        help="Ranking objective for --tune-grid.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    from aleatrix_solver.yahtzee_ai import YahtzeeAI

    args = parse_args()
    target_score = resolve_target_score(args.target_score, args.history_path)
    opponent_scores = []
    if args.history_path:
        from aleatrix_solver.opponent_history import build_opponent_profile

        opponent_scores = build_opponent_profile(args.history_path)["opponent_scores"]
    if args.tune_grid:
        from aleatrix_solver.strategy_config import save_strategy_config
        from strategy_tuner import build_strategy_grid, config_from_strategy_name, rank_strategy_summaries

        strategies = build_strategy_grid(parse_depth_specs(args.depths), parse_risk_specs(args.risks))
        if args.objective == "opponent-win-rate" and opponent_scores:
            comparison = compare_strategies_against_opponents(
                strategies,
                opponent_scores=opponent_scores,
                games=args.games,
                seed=args.seed,
            )
        else:
            comparison = compare_strategies(
                strategies,
                games=args.games,
                seed=args.seed,
                target_score=target_score,
            )
        ranked = rank_strategy_summaries(comparison, objective=args.objective)
        print_ranked_strategies(ranked)
        if args.write_config and ranked:
            saved_config = save_strategy_config(config_from_strategy_name(ranked[0]["name"]), args.write_config)
            print(f"Saved strategy config to {args.write_config}: {saved_config}")
    elif args.compare_risk:
        strategies = []
        for risk_multiplier in parse_risk_specs(args.compare_risk):
            name = f"risk{risk_multiplier:g}"
            strategies.append((name, YahtzeeAI(risk_multiplier=risk_multiplier)))
        comparison = compare_strategies(
            strategies,
            games=args.games,
            seed=args.seed,
            target_score=target_score,
        )
        for name, summary in comparison.items():
            print(name)
            print_summary(summary)
    elif args.compare_depths:
        strategies = []
        for exact_limit, lower_limit in parse_depth_specs(args.compare_depths):
            name = f"dp{exact_limit}_lower{lower_limit}"
            strategies.append((name, YahtzeeAI(exact_limit, lower_limit)))
        comparison = compare_strategies(
            strategies,
            games=args.games,
            seed=args.seed,
            target_score=target_score,
        )
        for name, summary in comparison.items():
            print(name)
            print_summary(summary)
    else:
        ai = YahtzeeAI()
        print_summary(run_simulation(ai, games=args.games, seed=args.seed, target_score=target_score))
