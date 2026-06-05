import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryStructureTests(unittest.TestCase):
    def test_tests_live_under_tests_directory(self):
        root_tests = sorted(path.name for path in ROOT.glob("test_*.py"))

        self.assertEqual(root_tests, [])
        self.assertTrue((ROOT / "tests").is_dir())
        self.assertTrue((ROOT / "tests" / "test_yahtzee_ai.py").exists())

    def test_reusable_modules_live_in_package(self):
        package = ROOT / "aleatrix_solver"
        expected_modules = [
            "game_history.py",
            "match_strategy.py",
            "opponent_history.py",
            "strategy_config.py",
            "tablebase_target.py",
            "yahtzee_ai.py",
        ]

        self.assertTrue((package / "__init__.py").exists())
        for module_name in expected_modules:
            self.assertTrue((package / module_name).exists(), module_name)
            self.assertFalse((ROOT / module_name).exists(), module_name)

    def test_utility_scripts_live_in_scripts_directory(self):
        for script_name in ["check_randomness.py", "clean_game_history.py"]:
            self.assertTrue((ROOT / "scripts" / script_name).exists(), script_name)
            self.assertFalse((ROOT / script_name).exists(), script_name)


if __name__ == "__main__":
    unittest.main()
