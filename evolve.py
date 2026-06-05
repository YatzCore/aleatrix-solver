import argparse
import os
import random
import sys
from pathlib import Path
try:
    import optuna
    TrialPrunedClass = optuna.TrialPruned
except ImportError:
    optuna = None
    class TrialPrunedClass(Exception):
        pass

# Ensure we can import modules from the current directory
sys.path.append(str(Path(__file__).resolve().parent))

from opponent_history import build_opponent_profile
from yahtzee_ai import YahtzeeAI
from yahtzee_simulator import (
    VALIDATION_MODE_LIVE_LIKE,
    VALIDATION_MODE_ORACLE_TARGET,
    play_solo_game,
    repeat_opponent_scores,
)
from strategy_config import save_strategy_config, DEFAULT_STRATEGY_CONFIG

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HISTORY_PATH = os.environ.get(
    "YAHTZEE_GAME_HISTORY_PATH",
    str(PROJECT_ROOT / "game_history.jsonl"),
)
DEFAULT_CONFIG_PATH = os.environ.get(
    "YAHTZEE_STRATEGY_CONFIG_PATH",
    str(PROJECT_ROOT / "strategy_config.json"),
)


def build_tuned_ai(params, exact_dp_enabled=False):
    config = dict(DEFAULT_STRATEGY_CONFIG)
    config.update(params)
    exact_limit = config["exact_category_limit"] if exact_dp_enabled else 0
    lower_limit = config["lower_only_exact_category_limit"] if exact_dp_enabled else 0

    return YahtzeeAI(
        exact_category_limit=exact_limit,
        lower_only_exact_category_limit=lower_limit,
        risk_multiplier=config["risk_multiplier"],
        decay_exponent=config["decay_exponent"],
        yahtzee_baseline=config["yahtzee_baseline"],
        chance_baseline=config["chance_baseline"],
        bonus_multiplier=config["bonus_multiplier"],
        opponent_risk_percentile=config["opponent_risk_percentile"],
        verbose=False,
    )


def suggest_trial_params(trial):
    return {
        "decay_exponent": trial.suggest_float("decay_exponent", 0.4, 1.0),
        "yahtzee_baseline": trial.suggest_float("yahtzee_baseline", 20.0, 45.0),
        "chance_baseline": trial.suggest_float("chance_baseline", 15.0, 30.0),
        "bonus_multiplier": trial.suggest_float("bonus_multiplier", 30.0, 70.0),
        "risk_multiplier": trial.suggest_float("risk_multiplier", 0.1, 2.0),
        "opponent_risk_percentile": trial.suggest_int("opponent_risk_percentile", 50, 95),
    }


def evaluate_params_against_opponents(
    params,
    opponent_scores,
    projection_model,
    total_games,
    game_seeds,
    target_score=None,
    exact_dp_enabled=False,
    validation_mode=VALIDATION_MODE_LIVE_LIKE,
):
    ai = build_tuned_ai(params, exact_dp_enabled=exact_dp_enabled)
    sampled_opponents = repeat_opponent_scores(opponent_scores, total_games)
    wins = 0
    scores = []

    for step in range(total_games):
        game_seed = game_seeds[step]
        opp_score = sampled_opponents[step]
        if validation_mode == VALIDATION_MODE_ORACLE_TARGET:
            game_target_score = opp_score
            simulated_opponent_final_score = None
            use_projection = False
        else:
            game_target_score = target_score
            simulated_opponent_final_score = opp_score
            use_projection = True

        res = play_solo_game(
            ai,
            seed=game_seed,
            target_score=game_target_score,
            opponent_score=0,
            simulated_opponent_final_score=simulated_opponent_final_score,
            use_opponent_projection=use_projection,
            projection_model=projection_model,
            opponent_risk_percentile=ai.opponent_risk_percentile,
        )
        final_score = res["final_score"]
        scores.append(final_score)
        if final_score > opp_score:
            wins += 1

    return {
        "win_rate": wins / total_games if total_games else 0.0,
        "average_score": sum(scores) / len(scores) if scores else 0.0,
        "scores": scores,
    }


def objective(
    trial,
    opponent_scores,
    projection_model,
    total_games,
    game_seeds,
    target_score=None,
    validation_mode=VALIDATION_MODE_LIVE_LIKE,
):
    params = suggest_trial_params(trial)
    ai = build_tuned_ai(params, exact_dp_enabled=False)

    sampled_opponents = repeat_opponent_scores(opponent_scores, total_games)
    report_interval = max(5, total_games // 20)
    wins = 0

    for step in range(total_games):
        game_seed = game_seeds[step]
        opp_score = sampled_opponents[step]
        if validation_mode == VALIDATION_MODE_ORACLE_TARGET:
            game_target_score = opp_score
            simulated_opponent_final_score = None
            use_projection = False
        else:
            game_target_score = target_score
            simulated_opponent_final_score = opp_score
            use_projection = True

        res = play_solo_game(
            ai,
            seed=game_seed,
            target_score=game_target_score,
            opponent_score=0,
            simulated_opponent_final_score=simulated_opponent_final_score,
            use_opponent_projection=use_projection,
            projection_model=projection_model,
            opponent_risk_percentile=ai.opponent_risk_percentile,
        )

        if res["final_score"] > opp_score:
            wins += 1

        if (step + 1) % report_interval == 0 or (step + 1) == total_games:
            current_win_rate = wins / (step + 1)
            trial.report(current_win_rate, step=step)

            if trial.should_prune():
                raise TrialPrunedClass()

    return wins / total_games if total_games else 0.0


def distribute_trials(total_trials, workers):
    total_trials = max(0, int(total_trials))
    workers = max(1, int(workers))
    if total_trials == 0:
        return []
    active_workers = min(total_trials, workers)
    base = total_trials // active_workers
    remainder = total_trials % active_workers
    return [base + (1 if index < remainder else 0) for index in range(active_workers)]


def completed_trial_candidates(trials, top_n):
    candidates = [
        trial for trial in trials
        if getattr(trial, "value", None) is not None and getattr(trial, "params", None)
    ]
    return sorted(candidates, key=lambda trial: trial.value, reverse=True)[:top_n]


def rerank_top_trials_with_exact_dp(
    trials,
    top_n=20,
    evaluator=None,
    opponent_scores=None,
    projection_model=None,
    total_games=None,
    game_seeds=None,
    target_score=None,
    validation_mode=VALIDATION_MODE_LIVE_LIKE,
):
    candidates = completed_trial_candidates(trials, top_n)
    best_trial = None
    best_metrics = None

    if evaluator is None:
        def evaluator(params):
            return evaluate_params_against_opponents(
                params,
                opponent_scores,
                projection_model,
                total_games,
                game_seeds,
                target_score=target_score,
                exact_dp_enabled=True,
                validation_mode=validation_mode,
            )

    for trial in candidates:
        metrics = evaluator(trial.params)
        rank_key = (metrics["win_rate"], metrics["average_score"])
        if best_metrics is None or rank_key > (best_metrics["win_rate"], best_metrics["average_score"]):
            best_trial = trial
            best_metrics = metrics

    return best_trial, best_metrics


def run_optimization_process(
    opponent_scores,
    projection_model,
    games,
    game_seeds,
    target_score,
    validation_mode,
    db_file,
    trials,
    worker_id,
):
    # Each process gets its own database connection session engine
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    storage = optuna.storages.RDBStorage(
        url=f"sqlite:///{db_file}",
        engine_kwargs={"connect_args": {"timeout": 60}}
    )
    study = optuna.create_study(
        study_name="yahtzee_optimization",
        storage=storage,
        direction="maximize",
        load_if_exists=True,
        pruner=optuna.pruners.MedianPruner(),
    )
    study.optimize(
        lambda trial: objective(
            trial,
            opponent_scores,
            projection_model,
            games,
            game_seeds,
            target_score=target_score,
            validation_mode=validation_mode,
        ),
        n_trials=trials,
        n_jobs=1,
    )


def main():
    parser = argparse.ArgumentParser(description="Optimize Yahtzee AI parameters using Optuna.")
    parser.add_argument("--games", type=int, default=50, help="Number of games per trial.")
    parser.add_argument("--trials", type=int, default=30, help="Number of optimization trials.")
    parser.add_argument("--seed", type=int, default=1, help="Master random seed.")
    parser.add_argument("--n-jobs", type=int, default=-1, help="Number of parallel jobs. -1 uses all cores.")
    parser.add_argument("--history-path", default=DEFAULT_HISTORY_PATH, help="Path to game history JSONL file.")
    parser.add_argument("--config-path", default=DEFAULT_CONFIG_PATH, help="Path to save best strategy config.")
    parser.add_argument("--resume", action="store_true", help="Resume optimization from existing database.")
    parser.add_argument(
        "--validation-mode",
        choices=[VALIDATION_MODE_LIVE_LIKE, VALIDATION_MODE_ORACLE_TARGET],
        default=VALIDATION_MODE_LIVE_LIKE,
        help="Validation semantics used during tuning and reranking.",
    )
    parser.add_argument(
        "--holdout-fraction",
        type=float,
        default=0.2,
        help="Fraction of valid opponent scores reserved for holdout reporting.",
    )
    parser.add_argument(
        "--rerank-top",
        type=int,
        default=20,
        help="Number of completed trials to rerank with exact DP before saving.",
    )
    parser.add_argument(
        "--rerank-games",
        type=int,
        help="Games used for exact-DP reranking and holdout checks. Defaults to --games.",
    )
    args = parser.parse_args()

    if args.games <= 0:
        print("Error: --games must be positive.", file=sys.stderr)
        sys.exit(1)
    if args.trials <= 0:
        print("Error: --trials must be positive.", file=sys.stderr)
        sys.exit(1)
    if args.rerank_games is not None and args.rerank_games <= 0:
        print("Error: --rerank-games must be positive when provided.", file=sys.stderr)
        sys.exit(1)
    if args.rerank_top < 0:
        print("Error: --rerank-top cannot be negative.", file=sys.stderr)
        sys.exit(1)
    if not 0.0 <= args.holdout_fraction < 1.0:
        print("Error: --holdout-fraction must be in [0.0, 1.0).", file=sys.stderr)
        sys.exit(1)

    if optuna is None:
        print("Error: The 'optuna' package is required to run parameter optimization.", file=sys.stderr)
        print("Please install it by running:", file=sys.stderr)
        print("    pip install -r requirements.txt", file=sys.stderr)
        print("or:", file=sys.stderr)
        print("    pip install optuna sqlalchemy", file=sys.stderr)
        sys.exit(1)

    # Load history and reserve a holdout slice for reporting only.
    history_path = Path(args.history_path)
    profile = build_opponent_profile(history_path, holdout_fraction=args.holdout_fraction)
    opponent_scores = profile["training_opponent_scores"] or profile["opponent_scores"]
    holdout_scores = profile["holdout_opponent_scores"]
    target_score = profile["target_score"]
    projection_model = profile["projection_model"]

    if not opponent_scores:
        print(f"Warning: No opponent scores found in {args.history_path}. Generating synthetic scores.")
        # Fallback to realistic Solitaired opponent scores (mean ~240, std ~25)
        rnd = random.Random(args.seed)
        opponent_scores = [int(rnd.normalvariate(240, 25)) for _ in range(100)]
        synthetic_target = sorted(opponent_scores)[int(0.75 * (len(opponent_scores) - 1))]
        target_score = synthetic_target + 1

    print(
        f"Loaded {len(opponent_scores)} training opponent scores "
        f"({profile['games']} valid games, {profile['skipped_games']} skipped, "
        f"{len(holdout_scores)} holdout)."
    )
    if target_score is not None:
        print(f"Live-like target score: {target_score}")

    # Optuna SQLite RDBStorage file setup
    db_file = "yahtzee_optuna.db"
    if not args.resume and os.path.exists(db_file):
        try:
            os.remove(db_file)
            print(f"Removed old SQLite database '{db_file}' to start a fresh optimization.")
        except OSError as e:
            print(f"Warning: Could not remove '{db_file}': {e}")

    # Safely create all database tables in the main thread first to avoid SQLite race conditions on subprocess spawns
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    storage = optuna.storages.RDBStorage(
        url=f"sqlite:///{db_file}",
        engine_kwargs={"connect_args": {"timeout": 60}}
    )
    optuna.create_study(
        study_name="yahtzee_optimization",
        storage=storage,
        direction="maximize",
        load_if_exists=True,
        pruner=optuna.pruners.MedianPruner(),
    )
    del storage  # Clean up database connection before spawning child processes

    # Determine worker count for process-level parallelization
    import multiprocessing
    if args.n_jobs == -1:
        workers = multiprocessing.cpu_count()
    elif args.n_jobs > 1:
        workers = args.n_jobs
    else:
        workers = 1
    trial_counts = distribute_trials(args.trials, workers)
    workers = len(trial_counts)

    # Generate one shared game_seeds list to ensure trial comparisons are fair
    rnd = random.Random(args.seed)
    game_seeds = [rnd.randrange(2**32) for _ in range(args.games)]

    print(
        f"Starting study 'yahtzee_optimization' with {args.trials} trials, "
        f"{args.games} games per trial, validation={args.validation_mode} (workers={workers})..."
    )

    # Enable ANSI terminal sequences on Windows if applicable
    if sys.platform == "win32":
        os.system("")

    if workers == 1:
        storage = optuna.storages.RDBStorage(
            url=f"sqlite:///{db_file}",
            engine_kwargs={"connect_args": {"timeout": 60}}
        )
        study = optuna.create_study(
            study_name="yahtzee_optimization",
            storage=storage,
            direction="maximize",
            load_if_exists=True,
            pruner=optuna.pruners.MedianPruner(),
        )
        import time
        start_time = time.time()
        
        def print_progress_callback(study, trial):
            trials = study.trials
            completed_trials = sum(1 for t in trials if t.state == optuna.trial.TrialState.COMPLETE)
            pruned_trials = sum(1 for t in trials if t.state == optuna.trial.TrialState.PRUNED)
            
            best_val = 0.0
            try:
                best_val = study.best_value
            except Exception:
                pass
                
            progress_percent = min(1.0, completed_trials / args.trials)
            bar_len = 20
            filled_len = int(round(bar_len * progress_percent))
            bar = '#' * filled_len + '-' * (bar_len - filled_len)
            
            elapsed = int(time.time() - start_time)
            m, s = divmod(elapsed, 60)
            time_str = f"{m}m {s}s"
            
            # \033[K: erase line from cursor to end, \033[94m: blue, \033[92m: green, \033[97m: white, \033[93m: yellow, \033[96m: cyan, \033[0m: reset
            sys.stdout.write(
                f"\r\033[K\033[94m[\033[92m{bar}\033[94m]\033[0m "
                f"\033[97m{completed_trials}/{args.trials}\033[0m Completed | "
                f"\033[93mPruned: {pruned_trials}\033[0m | "
                f"\033[92mBest WR: {best_val*100:.2f}%\033[0m | "
                f"\033[96mTime: {time_str}\033[0m | "
                f"\033[95mWorkers: 1\033[0m"
            )
            sys.stdout.flush()

        study.optimize(
            lambda trial: objective(
                trial,
                opponent_scores,
                projection_model,
                args.games,
                game_seeds,
                target_score=target_score,
                validation_mode=args.validation_mode,
            ),
            n_trials=args.trials,
            n_jobs=1,
            callbacks=[print_progress_callback],
        )
        print() # New line after completion
    else:
        # Launch independent processes that coordinate via RDB SQLite locking (avoids Python GIL entirely)
        processes = []
        for i, trial_count in enumerate(trial_counts):
            p = multiprocessing.Process(
                target=run_optimization_process,
                args=(
                    opponent_scores,
                    projection_model,
                    args.games,
                    game_seeds,
                    target_score,
                    args.validation_mode,
                    db_file,
                    trial_count,
                    i
                )
            )
            p.start()
            processes.append(p)

        # Progress visualization loop
        import time
        start_time = time.time()
        completed = False
        while not completed:
            alive = sum(1 for p in processes if p.is_alive())
            if alive == 0:
                completed = True
                
            try:
                storage = optuna.storages.RDBStorage(
                    url=f"sqlite:///{db_file}",
                    engine_kwargs={"connect_args": {"timeout": 10}}
                )
                study = optuna.load_study(
                    study_name="yahtzee_optimization",
                    storage=storage
                )
                trials = study.trials
                completed_trials = sum(1 for t in trials if t.state == optuna.trial.TrialState.COMPLETE)
                pruned_trials = sum(1 for t in trials if t.state == optuna.trial.TrialState.PRUNED)
                
                best_val = 0.0
                try:
                    best_val = study.best_value
                except Exception:
                    pass
                
                progress_percent = min(1.0, completed_trials / args.trials)
                bar_len = 20
                filled_len = int(round(bar_len * progress_percent))
                bar = '#' * filled_len + '-' * (bar_len - filled_len)
                
                elapsed = int(time.time() - start_time)
                m, s = divmod(elapsed, 60)
                time_str = f"{m}m {s}s"
                
                # \033[K: erase line from cursor to end, \033[94m: blue, \033[92m: green, \033[97m: white, \033[93m: yellow, \033[96m: cyan, \033[0m: reset
                sys.stdout.write(
                    f"\r\033[K\033[94m[\033[92m{bar}\033[94m]\033[0m "
                    f"\033[97m{completed_trials}/{args.trials}\033[0m Completed | "
                    f"\033[93mPruned: {pruned_trials}\033[0m | "
                    f"\033[92mBest WR: {best_val*100:.2f}%\033[0m | "
                    f"\033[96mTime: {time_str}\033[0m | "
                    f"\033[95mActive Workers: {alive}\033[0m"
                )
                sys.stdout.flush()
            except Exception:
                pass
                
            if not completed:
                time.sleep(3.0)
        print() # New line after completion

    # Load completed study in main thread to report best results
    storage = optuna.storages.RDBStorage(
        url=f"sqlite:///{db_file}",
        engine_kwargs={"connect_args": {"timeout": 60}}
    )
    study = optuna.create_study(
        study_name="yahtzee_optimization",
        storage=storage,
        direction="maximize",
        load_if_exists=True,
        pruner=optuna.pruners.MedianPruner(),
    )

    print("\nOptimization completed!")
    print(f"Number of finished trials: {len(study.trials)}")
    if not completed_trial_candidates(study.trials, len(study.trials)):
        print("Error: No completed trials were available to save.", file=sys.stderr)
        sys.exit(1)

    best_trial = study.best_trial
    selected_trial = best_trial
    selected_metrics = None
    print(f"Best fast trial value (win rate): {best_trial.value:.4f}")

    rerank_games = args.rerank_games or args.games
    if args.rerank_top > 0:
        rerank_rng = random.Random(args.seed + 99991)
        rerank_seeds = [rerank_rng.randrange(2**32) for _ in range(rerank_games)]
        reranked_trial, selected_metrics = rerank_top_trials_with_exact_dp(
            study.trials,
            top_n=args.rerank_top,
            opponent_scores=opponent_scores,
            projection_model=projection_model,
            total_games=rerank_games,
            game_seeds=rerank_seeds,
            target_score=target_score,
            validation_mode=args.validation_mode,
        )
        if reranked_trial is not None:
            selected_trial = reranked_trial
            print(
                f"Exact-DP rerank selected trial {selected_trial.number}: "
                f"WR={selected_metrics['win_rate']:.4f}, "
                f"avg={selected_metrics['average_score']:.2f}"
            )

    if holdout_scores:
        holdout_games = max(len(holdout_scores), rerank_games)
        holdout_rng = random.Random(args.seed + 424242)
        holdout_seeds = [holdout_rng.randrange(2**32) for _ in range(holdout_games)]
        holdout_metrics = evaluate_params_against_opponents(
            selected_trial.params,
            holdout_scores,
            projection_model,
            holdout_games,
            holdout_seeds,
            target_score=target_score,
            exact_dp_enabled=True,
            validation_mode=args.validation_mode,
        )
        print(
            f"Holdout exact-DP check ({holdout_games} games): "
            f"WR={holdout_metrics['win_rate']:.4f}, "
            f"avg={holdout_metrics['average_score']:.2f}"
        )

    print("Selected parameters:")
    for k, v in selected_trial.params.items():
        print(f"  {k}: {v}")

    # Merge best parameters with default config and save
    config = dict(DEFAULT_STRATEGY_CONFIG)
    config.update(selected_trial.params)
    saved_config = save_strategy_config(config, args.config_path)
    print(f"\nSaved best configuration to {args.config_path}: {saved_config}")


if __name__ == "__main__":
    main()
