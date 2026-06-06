import os
import sys
import math
import time
import argparse
import json
import multiprocessing
from pathlib import Path
from statistics import median, mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aleatrix_solver.yahtzee_ai import YahtzeeAI, CATEGORIES
from yahtzee_bot import TablebaseAI, is_tablebase_ready
from yahtzee_simulator import (
    play_solo_game,
    repeat_opponent_scores,
    DEFAULT_HISTORY_PATH,
    get_epsilon_value,
)
from aleatrix_solver.opponent_history import build_opponent_profile
from aleatrix_solver.strategy_config import DEFAULT_STRATEGY_CONFIG, create_tablebase_fallback_ai

# Global variables in worker processes
_worker_tablebase_ai = None
_worker_optuna_ai = None

def init_worker(dll_path, bin_path):
    global _worker_tablebase_ai, _worker_optuna_ai
    from yahtzee_bot import TablebaseAI
    from aleatrix_solver.strategy_config import DEFAULT_STRATEGY_CONFIG, create_tablebase_fallback_ai
    _worker_tablebase_ai = TablebaseAI(dll_path, bin_path)
    _worker_optuna_ai, _ = create_tablebase_fallback_ai(DEFAULT_STRATEGY_CONFIG, verbose=False)

def run_single_game(args):
    seed, opp_score, target_score, projection_model, opponent_risk_percentile, epsilon, unified_mode = args
    from yahtzee_simulator import play_solo_game
    res = play_solo_game(
        _worker_tablebase_ai,
        seed=seed,
        target_score=target_score,
        opponent_score=0,
        simulated_opponent_final_score=opp_score,
        use_opponent_projection=True,
        projection_model=projection_model,
        opponent_risk_percentile=opponent_risk_percentile,
        score_fallback_ai=_worker_optuna_ai,
        epsilon=epsilon,
        unified_mode=unified_mode,
    )
    return res

def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def binom_cdf(k, n, p=0.5):
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    ans = 0.0
    log_p = math.log(p)
    log_1_minus_p = math.log(1.0 - p)
    for i in range(k + 1):
        log_comb = math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
        term_log = log_comb + i * log_p + (n - i) * log_1_minus_p
        ans += math.exp(term_log)
    return min(1.0, ans)

def exact_mcnemar_p_value(saves, throws):
    n = saves + throws
    if n == 0:
        return 1.0
    k = min(saves, throws)
    p_exact = 2.0 * binom_cdf(k, n, 0.5)
    return min(1.0, p_exact)

def edwards_mcnemar_p_value(saves, throws):
    n = saves + throws
    if n == 0:
        return 1.0
    if abs(saves - throws) <= 1:
        return 1.0
    chi2 = (abs(saves - throws) - 1.0) ** 2 / n
    z = math.sqrt(chi2)
    p_edwards = 2.0 * (1.0 - phi(z))
    return p_edwards

def evaluate_config(
    dll_path,
    bin_path,
    seeds,
    opp_scores,
    target_score,
    projection_model,
    opponent_risk_percentile,
    epsilon=None,
    unified_mode=False,
    baseline_results=None,
):
    start_time = time.perf_counter()

    scores = []
    win_statuses = []
    num_candidates_list = []
    ev_calls_list = []
    wp_changed_count = 0
    total_decisions = 0

    changed_games_count = 0
    saves = 0
    throws = 0

    wp_drops_on_shifts = []
    ev_gains_on_shifts = []
    game_results = []

    tasks = [
        (seed, opp_score, target_score, projection_model, opponent_risk_percentile, epsilon, unified_mode)
        for seed, opp_score in zip(seeds, opp_scores)
    ]

    num_workers = multiprocessing.cpu_count()
    print(f"  Spawning {num_workers} parallel workers...", flush=True)

    with multiprocessing.Pool(
        processes=num_workers,
        initializer=init_worker,
        initargs=(dll_path, bin_path)
    ) as pool:
        for i, res in enumerate(pool.imap(run_single_game, tasks)):
            game_results.append(res)
            final_score = res["final_score"]
            scores.append(final_score)
            is_win = final_score > opp_scores[i]
            win_statuses.append(is_win)

            game_wp_changed = False
            for turn in res["turns"]:
                for d in turn["decisions"]:
                    if unified_mode and d.get("num_candidates") is not None:
                        num_candidates_list.append(d["num_candidates"])
                        ev_calls_list.append(d["ev_calls"])
                        total_decisions += 1
                        if d.get("wp_changed"):
                            wp_changed_count += 1
                            game_wp_changed = True
                            wp_drops_on_shifts.append(d.get("wp_drop", 0.0))
                            ev_gains_on_shifts.append(d.get("ev_gain", 0.0))

            if game_wp_changed:
                changed_games_count += 1

            if baseline_results is not None:
                base_win = baseline_results["win_statuses"][i]
                if is_win and not base_win:
                    saves += 1
                elif base_win and not is_win:
                    throws += 1

            if (i + 1) % 500 == 0:
                print(f"    Simulated {i + 1}/{len(seeds)} games...", flush=True)

    runtime = time.perf_counter() - start_time
    avg_score = mean(scores)
    win_rate = sum(1 for w in win_statuses if w) / len(seeds)

    # Split win rates by realistic (< 250) vs hard (>= 250) opponent final scores
    realistic_games = sum(1 for s in opp_scores if s < 250)
    hard_games = sum(1 for s in opp_scores if s >= 250)

    win_rate_realistic = sum(1 for i, w in enumerate(win_statuses) if w and opp_scores[i] < 250) / realistic_games if realistic_games > 0 else 0.0
    win_rate_hard = sum(1 for i, w in enumerate(win_statuses) if w and opp_scores[i] >= 250) / hard_games if hard_games > 0 else 0.0

    avg_candidates = mean(num_candidates_list) if num_candidates_list else 0.0
    med_candidates = median(num_candidates_list) if num_candidates_list else 0.0
    ev_calls_per_decision = mean(ev_calls_list) if ev_calls_list else 0.0
    shift_rate = (wp_changed_count / total_decisions * 100) if total_decisions > 0 else 0.0

    avg_wp_drop_on_shifts = mean(wp_drops_on_shifts) if wp_drops_on_shifts else 0.0
    avg_ev_gain_on_shifts = mean(ev_gains_on_shifts) if ev_gains_on_shifts else 0.0

    # Calculate detailed shift metrics
    total_shifts = wp_changed_count
    avg_shifts_per_game = total_shifts / len(seeds)
    saves_per_1000 = (saves / total_shifts * 1000) if total_shifts > 0 else 0.0
    throws_per_1000 = (throws / total_shifts * 1000) if total_shifts > 0 else 0.0
    shift_efficiency = (saves - throws) / total_shifts if total_shifts > 0 else 0.0

    return {
        "scores": scores,
        "win_statuses": win_statuses,
        "win_rate": win_rate,
        "avg_score": avg_score,
        "win_rate_realistic": win_rate_realistic,
        "win_rate_hard": win_rate_hard,
        "realistic_games": realistic_games,
        "hard_games": hard_games,
        "runtime": runtime,
        "saves": saves,
        "throws": throws,
        "net": saves - throws,
        "avg_candidates": avg_candidates,
        "med_candidates": med_candidates,
        "ev_calls_per_decision": ev_calls_per_decision,
        "shift_rate": shift_rate,
        "changed_games": changed_games_count,
        "avg_wp_drop_on_shifts": avg_wp_drop_on_shifts,
        "avg_ev_gain_on_shifts": avg_ev_gain_on_shifts,

        "total_shifts": total_shifts,
        "avg_shifts_per_game": avg_shifts_per_game,
        "saves_per_1000": saves_per_1000,
        "throws_per_1000": throws_per_1000,
        "shift_efficiency": shift_efficiency,

        "game_results": game_results,
    }

def analyze_shifts(policy_name, seeds, opp_scores, baseline_results, cfg_results):
    game_results = cfg_results["game_results"]
    baseline_win_statuses = baseline_results["win_statuses"]
    baseline_scores = baseline_results["scores"]

    all_decisions = []
    all_shifts = []

    for i, (res, seed, opp_score) in enumerate(zip(game_results, seeds, opp_scores)):
        base_win = baseline_win_statuses[i]
        unified_win = cfg_results["win_statuses"][i]

        if unified_win and not base_win:
            game_outcome = "save_game"
        elif base_win and not unified_win:
            game_outcome = "throw_game"
        elif base_win and unified_win:
            game_outcome = "both_win"
        else:
            base_score = baseline_scores[i]
            unified_score = cfg_results["scores"][i]
            if base_score == opp_score and unified_score == opp_score:
                game_outcome = "both_tie"
            else:
                game_outcome = "both_loss"

        for turn in res["turns"]:
            for d in turn["decisions"]:
                if d.get("fallback_solver") == "Unified Evaluator":
                    decision_entry = {
                        "seed": seed,
                        "game_id": i,
                        "game_outcome": game_outcome,
                        "turn_index": d["turn_index"],
                        "roll_index": d["roll_index"],
                        "rolls_left": d["rolls_left"],
                        "decision_type": d["decision_type"],
                        "best_wp": d["best_wp"],
                        "chosen_wp": d["chosen_wp"],
                        "wp_drop": d["wp_drop"],
                        "tablebase_action": d["tablebase_action"],
                        "chosen_action": d["chosen_action"],
                        "tablebase_action_ev": d["tablebase_action_ev"],
                        "chosen_action_ev": d["chosen_action_ev"],
                        "ev_gain": d["ev_gain"],
                        "candidate_count": d["candidate_count"],
                        "epsilon": d["epsilon"],
                        "policy_name": policy_name,
                        "wp_changed": d["wp_changed"],
                    }
                    all_decisions.append(decision_entry)
                    if d["wp_changed"]:
                        all_shifts.append(decision_entry)

    os.makedirs("logs", exist_ok=True)
    with open(f"logs/decision_summary_{policy_name}.json", "w") as f:
        json.dump(all_decisions, f, indent=2)
    with open(f"logs/shift_analysis_log_{policy_name}.json", "w") as f:
        json.dump(all_shifts, f, indent=2)

    total_decisions = len(all_decisions)
    total_shifts = len(all_shifts)
    shift_rate = (total_shifts / total_decisions * 100) if total_decisions > 0 else 0.0

    print(f"\n================================================================================")
    print(f"SHIFT & ABLATION ATTRIBUTION ANALYSIS: {policy_name}")
    print(f"================================================================================")
    print(f"Total Decisions: {total_decisions}")
    print(f"Total Shifts:    {total_shifts} (Shift Rate: {shift_rate:.2f}%)")
    print(f"A shift is labeled by final paired game outcome (attribution by association, not causal proof).")

    def get_stats(subset):
        count = len(subset)
        saves = sum(1 for d in subset if d["game_outcome"] == "save_game")
        throws = sum(1 for d in subset if d["game_outcome"] == "throw_game")
        avg_wp_drop = mean([d["wp_drop"] for d in subset]) if subset else 0.0
        avg_ev_gain = mean([d["ev_gain"] for d in subset]) if subset else 0.0
        return count, saves, throws, avg_wp_drop, avg_ev_gain

    # A. WP Bucket analysis
    print(f"\n--- Analysis by Tablebase Win Probability (WP) Buckets ---")
    wp_buckets = [
        ("0-0.075", lambda wp: wp < 0.075),
        ("0.075-0.20", lambda wp: 0.075 <= wp < 0.20),
        ("0.20-0.50", lambda wp: 0.20 <= wp < 0.50),
        ("0.50-0.80", lambda wp: 0.50 <= wp < 0.80),
        ("0.80-1.00", lambda wp: wp >= 0.80),
    ]
    print(f"{'WP Bucket':<12} | {'Decisions':<9} | {'Shifts':<6} | {'Saves':<5} | {'Throws':<6} | {'avg wp_drop':<11} | {'avg ev_gain':<11}")
    print(f"-"*80)
    for name, cond in wp_buckets:
        dec_sub = [d for d in all_decisions if cond(d["best_wp"])]
        shift_sub = [d for d in all_shifts if cond(d["best_wp"])]
        d_cnt = len(dec_sub)
        s_cnt, saves, throws, avg_wp_drop, avg_ev_gain = get_stats(shift_sub)
        print(f"{name:<12} | {d_cnt:<9d} | {s_cnt:<6d} | {saves:<5d} | {throws:<6d} | {avg_wp_drop:11.5f} | {avg_ev_gain:11.2f}")

    # B. Analysis by Turn index
    print(f"\n--- Analysis by Turn Index ---")
    print(f"{'Turn':<4} | {'Shifts':<6} | {'Saves':<5} | {'Throws':<6} | {'avg wp_drop':<11} | {'avg ev_gain':<11}")
    print(f"-"*60)
    for turn in range(1, 14):
        shift_sub = [d for d in all_shifts if d["turn_index"] == turn]
        s_cnt, saves, throws, avg_wp_drop, avg_ev_gain = get_stats(shift_sub)
        print(f"{turn:<4d} | {s_cnt:<6d} | {saves:<5d} | {throws:<6d} | {avg_wp_drop:11.5f} | {avg_ev_gain:11.2f}")

    # C. Analysis by Decision Type
    print(f"\n--- Analysis by Decision Type ---")
    print(f"{'Type':<6} | {'Shifts':<6} | {'Saves':<5} | {'Throws':<6} | {'avg wp_drop':<11} | {'avg ev_gain':<11}")
    print(f"-"*60)
    for dtype in ("keep", "score"):
        shift_sub = [d for d in all_shifts if d["decision_type"] == dtype]
        s_cnt, saves, throws, avg_wp_drop, avg_ev_gain = get_stats(shift_sub)
        print(f"{dtype:<6} | {s_cnt:<6d} | {saves:<5d} | {throws:<6d} | {avg_wp_drop:11.5f} | {avg_ev_gain:11.2f}")

    # D. Analysis by WP Drop Buckets
    print(f"\n--- Analysis by WP Drop Buckets ---")
    wp_drop_buckets = [
        ("0", lambda x: x == 0.0),
        ("0-0.001", lambda x: 0.0 < x <= 0.001),
        ("0.001-0.0025", lambda x: 0.001 < x <= 0.0025),
        ("0.0025-0.005", lambda x: 0.0025 < x <= 0.005),
        ("0.005-0.01", lambda x: 0.005 < x <= 0.01),
        ("0.01+", lambda x: x > 0.01),
    ]
    print(f"{'WP Drop Bucket':<15} | {'Shifts':<6} | {'Saves':<5} | {'Throws':<6} | {'avg ev_gain':<11}")
    print(f"-"*60)
    for name, cond in wp_drop_buckets:
        shift_sub = [d for d in all_shifts if cond(d["wp_drop"])]
        s_cnt, saves, throws, _, avg_ev_gain = get_stats(shift_sub)
        print(f"{name:<15} | {s_cnt:<6d} | {saves:<5d} | {throws:<6d} | {avg_ev_gain:11.2f}")

    # E. Analysis by EV Gain Buckets
    print(f"\n--- Analysis by EV Gain Buckets ---")
    ev_gain_buckets = [
        ("0-1", lambda x: x < 1.0),
        ("1-3", lambda x: 1.0 <= x < 3.0),
        ("3-5", lambda x: 3.0 <= x < 5.0),
        ("5-10", lambda x: 5.0 <= x < 10.0),
        ("10+", lambda x: x >= 10.0),
    ]
    print(f"{'EV Gain Bucket':<15} | {'Shifts':<6} | {'Saves':<5} | {'Throws':<6} | {'avg wp_drop':<11}")
    print(f"-"*60)
    for name, cond in ev_gain_buckets:
        shift_sub = [d for d in all_shifts if cond(d["ev_gain"])]
        s_cnt, saves, throws, avg_wp_drop, _ = get_stats(shift_sub)
        print(f"{name:<15} | {s_cnt:<6d} | {saves:<5d} | {throws:<6d} | {avg_wp_drop:11.5f}")
    print(f"================================================================================\n")

def main():
    parser = argparse.ArgumentParser(description="Evaluate Unified Hybrid v1 Yahtzee AI.")
    parser.add_argument("--games", type=int, default=2000, help="Number of games to simulate (default: 2000).")
    parser.add_argument("--seed", type=int, default=42, help="Master simulation seed (default: 42).")
    parser.add_argument("--history-path", default=DEFAULT_HISTORY_PATH, help="Path to JSONL game history.")
    parser.add_argument("--configs", default="all", help="Comma-separated configs to run or 'all'.")
    args = parser.parse_args()

    dll_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "build", "Release", "yahtzee_core.dll"))
    bin_path = os.path.abspath(os.path.join(os.getcwd(), "cpp", "tablebase.bin"))

    if not is_tablebase_ready(dll_path, bin_path):
        print(f"Error: Tablebase binary or DLL not found at: {bin_path}, {dll_path}")
        sys.exit(1)

    print("Initializing Tablebase AI and Optuna Expectiminimax fallback AI...", flush=True)
    tablebase_ai = TablebaseAI(dll_path, bin_path)
    optuna_ai, _ = create_tablebase_fallback_ai(DEFAULT_STRATEGY_CONFIG, verbose=False)

    print("Loading opponent history profile...", flush=True)
    profile = build_opponent_profile(args.history_path)
    opponent_scores = profile["opponent_scores"]
    projection_model = profile["projection_model"]
    target_score = profile["target_score"]
    opponent_risk_percentile = getattr(optuna_ai, "opponent_risk_percentile", 75)

    master_rng = random = type(sys)("random")
    import random
    master_rng = random.Random(args.seed)
    game_seeds = [master_rng.randrange(2**32) for _ in range(args.games)]
    sampled_opp_scores = repeat_opponent_scores(opponent_scores, args.games)
    master_rng.shuffle(sampled_opp_scores)

    print(f"\n--- Starting Evaluation: {args.games} games ---")
    print(f"Derived Target Score: {target_score}")
    print(f"Opponent Risk Percentile: {opponent_risk_percentile}")

    print("\nRunning baseline_075_fallback...", flush=True)
    baseline = evaluate_config(
        dll_path,
        bin_path,
        game_seeds,
        sampled_opp_scores,
        target_score,
        projection_model,
        opponent_risk_percentile,
        epsilon=None,
        unified_mode=False,
    )
    print(f"Baseline -> Win Rate: {baseline['win_rate']*100:.3f}% (Realistic: {baseline['win_rate_realistic']*100:.3f}%, Hard: {baseline['win_rate_hard']*100:.3f}%), Avg Score: {baseline['avg_score']:.2f}, Runtime: {baseline['runtime']:.1f}s")

    all_configs = [
        {"name": "dynamic_v1", "epsilon": "dynamic_v1"},
        {"name": "dynamic_no_desperation", "epsilon": "dynamic_no_desperation"},
        {"name": "dynamic_no_mid", "epsilon": "dynamic_no_mid"},
        {"name": "dynamic_strict_safe", "epsilon": "dynamic_strict_safe"},
        {"name": "dynamic_aggressive", "epsilon": "dynamic_aggressive"},
    ]

    if args.configs == "all":
        configs = all_configs
    else:
        selected_names = [x.strip() for x in args.configs.split(",")]
        configs = []
        for x in selected_names:
            match = next((c for c in all_configs if c["name"] == x), None)
            if match:
                configs.append(match)
            else:
                try:
                    val = float(x)
                    configs.append({"name": f"unified_eps_{val}", "epsilon": x})
                except Exception:
                    pass

    results = {}

    for cfg in configs:
        name = cfg["name"]
        eps = cfg["epsilon"]
        print(f"\nRunning {name} (policy={eps})...", flush=True)
        res = evaluate_config(
            dll_path,
            bin_path,
            game_seeds,
            sampled_opp_scores,
            target_score,
            projection_model,
            opponent_risk_percentile,
            epsilon=eps,
            unified_mode=True,
            baseline_results=baseline,
        )

        p_exact = exact_mcnemar_p_value(res["saves"], res["throws"])
        p_edwards = edwards_mcnemar_p_value(res["saves"], res["throws"])

        res["p_exact"] = p_exact
        res["p_edwards"] = p_edwards
        results[name] = res

        print(f"{name} -> Win Rate: {res['win_rate']*100:.3f}% (Realistic: {res['win_rate_realistic']*100:.3f}%, Hard: {res['win_rate_hard']*100:.3f}%), Net saves: {res['net']:+d}, p_exact: {p_exact:.4f}, Avg Score: {res['avg_score']:.2f}, Runtime: {res['runtime']:.1f}s")
        print(f"  Diagnostics: avg candidates={res['avg_candidates']:.2f}, median={res['med_candidates']}, EV calls/decision={res['ev_calls_per_decision']:.2f}, shift rate={res['shift_rate']:.2f}%")

        # Perform shift log attribution analysis
        analyze_shifts(name, game_seeds, sampled_opp_scores, baseline, res)

    # Print comparison table
    print("\n" + "="*205)
    print("FINAL COMPARISON TABLE")
    print("="*205)
    print(f"{'Config':<25} | {'WR (Comb)':<9} | {'WR (Real)':<9} | {'WR (Hard)':<9} | {'Avg Score':<10} | {'Saves':<5} | {'Throws':<6} | {'Net':<4} | {'p-exact':<8} | {'Shifted Gms':<11} | {'Shifts/Gm':<9} | {'Saves/1k':<8} | {'Throws/1k':<9} | {'Shift Eff':<9} | {'Runtime':<7}")
    print("-"*205)
    print(f"{'baseline_075':<25} | {baseline['win_rate']*100:8.3f}% | {baseline['win_rate_realistic']*100:8.3f}% | {baseline['win_rate_hard']*100:8.3f}% | {baseline['avg_score']:10.2f} | {'-':<5} | {'-':<6} | {'-':<4} | {'-':<8} | {'-':<11} | {'-':<9} | {'-':<8} | {'-':<9} | {'-':<9} | {baseline['runtime']:6.1f}s")
    for name, res in results.items():
        print(f"{name:<25} | {res['win_rate']*100:8.3f}% | {res['win_rate_realistic']*100:8.3f}% | {res['win_rate_hard']*100:8.3f}% | {res['avg_score']:10.2f} | {res['saves']:5d} | {res['throws']:6d} | {res['net']:+4d} | {res['p_exact']:8.4f} | {res['changed_games']:11d} | {res['avg_shifts_per_game']:9.3f} | {res['saves_per_1000']:8.2f} | {res['throws_per_1000']:9.2f} | {res['shift_efficiency']:9.4f} | {res['runtime']:6.1f}s")
    print("="*205)

if __name__ == "__main__":
    main()
