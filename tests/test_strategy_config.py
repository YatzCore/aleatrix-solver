import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sqlite3

from aleatrix_solver.strategy_config import (
    DEFAULT_STRATEGY_CONFIG,
    create_ai_from_config,
    create_tablebase_fallback_ai,
    load_best_optuna_config,
    load_strategy_config,
    save_strategy_config,
    sanitize_strategy_config,
)


class StrategyConfigTests(unittest.TestCase):
    def test_load_missing_config_returns_defaults(self):
        config = load_strategy_config("missing-strategy-config.json")

        self.assertEqual(config, DEFAULT_STRATEGY_CONFIG)

    def test_sanitize_strategy_config_clamps_invalid_values(self):
        config = sanitize_strategy_config({
            "exact_category_limit": 99,
            "lower_only_exact_category_limit": -2,
            "risk_multiplier": "2.5",
        })

        self.assertEqual(config["exact_category_limit"], 5)
        self.assertEqual(config["lower_only_exact_category_limit"], 0)
        self.assertEqual(config["risk_multiplier"], 2.5)

    def test_save_and_load_strategy_config_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "strategy_config.json"
            save_strategy_config({
                "exact_category_limit": 3,
                "lower_only_exact_category_limit": 4,
                "risk_multiplier": 2.0,
            }, path)

            loaded = load_strategy_config(path)

        self.assertEqual(loaded["exact_category_limit"], 3)
        self.assertEqual(loaded["lower_only_exact_category_limit"], 4)
        self.assertEqual(loaded["risk_multiplier"], 2.0)

    def test_create_ai_from_config_applies_settings(self):
        ai = create_ai_from_config({
            "exact_category_limit": 3,
            "lower_only_exact_category_limit": 4,
            "risk_multiplier": 2.0,
        })

        self.assertEqual(ai.exact_category_limit, 3)
        self.assertEqual(ai.lower_only_exact_category_limit, 4)
        self.assertEqual(ai.risk_multiplier, 2.0)

    def test_load_best_optuna_config_uses_top_complete_trial(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "yahtzee_optuna.db"
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            cur.execute("create table trials (trial_id integer primary key, number integer, state varchar(8))")
            cur.execute("create table trial_values (trial_id integer, objective integer, value float, value_type varchar(7))")
            cur.execute("create table trial_params (trial_id integer, param_name varchar(512), param_value float)")
            cur.executemany(
                "insert into trials values (?, ?, ?)",
                [
                    (1, 10, "COMPLETE"),
                    (2, 11, "COMPLETE"),
                    (3, 12, "PRUNED"),
                ],
            )
            cur.executemany(
                "insert into trial_values values (?, ?, ?, ?)",
                [
                    (1, 0, 0.38, "FINITE"),
                    (2, 0, 0.42, "FINITE"),
                    (3, 0, 0.99, "FINITE"),
                ],
            )
            cur.executemany(
                "insert into trial_params values (?, ?, ?)",
                [
                    (2, "risk_multiplier", 0.64),
                    (2, "opponent_risk_percentile", 85.0),
                    (2, "yahtzee_baseline", 25.1),
                ],
            )
            con.commit()
            con.close()

            config, metadata = load_best_optuna_config(db_path)

        self.assertEqual(config["risk_multiplier"], 0.64)
        self.assertEqual(config["opponent_risk_percentile"], 85)
        self.assertEqual(metadata["trial_number"], 11)
        self.assertEqual(metadata["objective_value"], 0.42)
        self.assertEqual(metadata["source"], "optuna_db")

    def test_create_tablebase_fallback_ai_prefers_optuna_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "yahtzee_optuna.db"
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            cur.execute("create table trials (trial_id integer primary key, number integer, state varchar(8))")
            cur.execute("create table trial_values (trial_id integer, objective integer, value float, value_type varchar(7))")
            cur.execute("create table trial_params (trial_id integer, param_name varchar(512), param_value float)")
            cur.execute("insert into trials values (1, 2734, 'COMPLETE')")
            cur.execute("insert into trial_values values (1, 0, 0.422, 'FINITE')")
            cur.execute("insert into trial_params values (1, 'risk_multiplier', 0.64)")
            con.commit()
            con.close()

            calls = []

            def fake_factory(config, verbose=True):
                calls.append((config, verbose))
                return SimpleNamespace()

            ai, metadata = create_tablebase_fallback_ai(
                {"risk_multiplier": 2.0},
                optuna_db_path=db_path,
                ai_factory=fake_factory,
                verbose=False,
            )

        self.assertEqual(calls[0][0]["risk_multiplier"], 0.64)
        self.assertFalse(calls[0][1])
        self.assertEqual(metadata["source"], "optuna_db")
        self.assertEqual(metadata["trial_number"], 2734)
        self.assertEqual(ai.fallback_solver_name, "Optuna Expectiminimax")

    def test_create_tablebase_fallback_ai_uses_runtime_config_without_optuna_db(self):
        calls = []

        def fake_factory(config, verbose=True):
            calls.append((config, verbose))
            return SimpleNamespace()

        ai, metadata = create_tablebase_fallback_ai(
            {"risk_multiplier": 1.7},
            optuna_db_path="missing-optuna.db",
            ai_factory=fake_factory,
            verbose=False,
        )

        self.assertEqual(calls[0][0]["risk_multiplier"], 1.7)
        self.assertEqual(metadata["source"], "runtime_config")
        self.assertEqual(ai.fallback_solver_name, "Runtime Expectiminimax")


if __name__ == "__main__":
    unittest.main()
