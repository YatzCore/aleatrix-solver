import json
import os
import sqlite3
from pathlib import Path

from yahtzee_ai import (
    ENDGAME_EXACT_CATEGORY_LIMIT,
    LOWER_ONLY_EXACT_CATEGORY_LIMIT,
    YahtzeeAI,
)


PROJECT_ROOT = Path(__file__).resolve().parent
STRATEGY_CONFIG_PATH = os.environ.get(
    "YAHTZEE_STRATEGY_CONFIG_PATH",
    str(PROJECT_ROOT / "strategy_config.json"),
)
FALLBACK_OPTUNA_DB_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "optimization"
    / "5mil-2026-06-02"
    / "yahtzee_optuna.db"
)
DEFAULT_STRATEGY_CONFIG = {
    "exact_category_limit": ENDGAME_EXACT_CATEGORY_LIMIT,
    "lower_only_exact_category_limit": LOWER_ONLY_EXACT_CATEGORY_LIMIT,
    "risk_multiplier": 1.0,
    "opponent_risk_percentile": 75,
    "decay_exponent": 0.7,
    "yahtzee_baseline": 35.0,
    "chance_baseline": 22.0,
    "bonus_multiplier": 55.0,
}


def clamp(value, low, high):
    return max(low, min(high, value))


def sanitize_strategy_config(config):
    merged = dict(DEFAULT_STRATEGY_CONFIG)
    if isinstance(config, dict):
        merged.update(config)

    return {
        "exact_category_limit": clamp(int(merged["exact_category_limit"]), 0, 5),
        "lower_only_exact_category_limit": clamp(int(merged["lower_only_exact_category_limit"]), 0, 5),
        "risk_multiplier": clamp(float(merged["risk_multiplier"]), 0.0, 5.0),
        "opponent_risk_percentile": clamp(int(merged.get("opponent_risk_percentile", 75)), 50, 95),
        "decay_exponent": clamp(float(merged.get("decay_exponent", 0.7)), 0.1, 2.0),
        "yahtzee_baseline": clamp(float(merged.get("yahtzee_baseline", 35.0)), 10.0, 60.0),
        "chance_baseline": clamp(float(merged.get("chance_baseline", 22.0)), 5.0, 40.0),
        "bonus_multiplier": clamp(float(merged.get("bonus_multiplier", 55.0)), 10.0, 100.0),
    }


def load_strategy_config(path=STRATEGY_CONFIG_PATH):
    config_path = Path(path)
    if not config_path.exists():
        return dict(DEFAULT_STRATEGY_CONFIG)

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_STRATEGY_CONFIG)

    return sanitize_strategy_config(raw_config)


def save_strategy_config(config, path=STRATEGY_CONFIG_PATH):
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    clean_config = sanitize_strategy_config(config)
    config_path.write_text(json.dumps(clean_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return clean_config


def create_ai_from_config(config, verbose=True):
    clean_config = sanitize_strategy_config(config)
    return YahtzeeAI(
        exact_category_limit=clean_config["exact_category_limit"],
        lower_only_exact_category_limit=clean_config["lower_only_exact_category_limit"],
        risk_multiplier=clean_config["risk_multiplier"],
        decay_exponent=clean_config["decay_exponent"],
        yahtzee_baseline=clean_config["yahtzee_baseline"],
        chance_baseline=clean_config["chance_baseline"],
        bonus_multiplier=clean_config["bonus_multiplier"],
        opponent_risk_percentile=clean_config["opponent_risk_percentile"],
        verbose=verbose,
    )


def load_best_optuna_config(db_path=FALLBACK_OPTUNA_DB_PATH):
    optuna_path = Path(db_path)
    if not optuna_path.exists():
        return None, None

    con = None
    try:
        con = sqlite3.connect(optuna_path)
        cur = con.cursor()
        row = cur.execute(
            """
            select t.trial_id, t.number, tv.value
            from trials t
            join trial_values tv on tv.trial_id = t.trial_id
            where t.state = 'COMPLETE'
              and tv.objective = 0
              and tv.value_type = 'FINITE'
              and tv.value is not null
            order by tv.value desc
            limit 1
            """
        ).fetchone()
        if row is None:
            return None, None

        trial_id, trial_number, objective_value = row
        params = dict(
            cur.execute(
                "select param_name, param_value from trial_params where trial_id = ?",
                (trial_id,),
            ).fetchall()
        )
    except sqlite3.Error:
        return None, None
    finally:
        if con is not None:
            con.close()

    config = dict(DEFAULT_STRATEGY_CONFIG)
    config.update(params)
    clean_config = sanitize_strategy_config(config)
    metadata = {
        "source": "optuna_db",
        "path": str(optuna_path),
        "trial_number": int(trial_number),
        "objective_value": float(objective_value),
    }
    return clean_config, metadata


def create_tablebase_fallback_ai(
    runtime_config,
    optuna_db_path=FALLBACK_OPTUNA_DB_PATH,
    ai_factory=create_ai_from_config,
    verbose=False,
):
    config, metadata = load_best_optuna_config(optuna_db_path)
    if config is None:
        config = sanitize_strategy_config(runtime_config)
        metadata = {
            "source": "runtime_config",
            "path": None,
            "trial_number": None,
            "objective_value": None,
        }

    ai = ai_factory(config, verbose=verbose)
    if metadata["source"] == "optuna_db":
        ai.fallback_solver_name = "Optuna Expectiminimax"
    else:
        ai.fallback_solver_name = "Runtime Expectiminimax"
    ai.fallback_solver_metadata = dict(metadata)
    ai.fallback_solver_config = dict(config)
    return ai, metadata
