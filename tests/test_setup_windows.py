import importlib.util
import sys
import unittest
from pathlib import Path


def load_setup_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "setup_windows.py"
    spec = importlib.util.spec_from_file_location("setup_windows", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["setup_windows"] = module
    spec.loader.exec_module(module)
    return module


class SetupWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setup = load_setup_module()

    def test_find_cmake_prefers_explicit_path(self):
        cmake = self.setup.find_cmake(
            explicit_path=Path("C:/Tools/cmake.exe"),
            which_func=lambda name: None,
            candidate_paths=[Path("C:/Other/cmake.exe")],
            exists_func=lambda path: True,
        )

        self.assertEqual(cmake, Path("C:/Tools/cmake.exe"))

    def test_find_cmake_uses_first_existing_candidate_before_plain_command(self):
        cmake = self.setup.find_cmake(
            explicit_path=None,
            which_func=lambda name: None,
            candidate_paths=[Path("C:/Missing/cmake.exe"), Path("C:/VS/cmake.exe")],
            exists_func=lambda path: path == Path("C:/VS/cmake.exe"),
        )

        self.assertEqual(cmake, Path("C:/VS/cmake.exe"))

    def test_build_steps_include_default_average_user_flow(self):
        args = self.setup.parse_args([])
        steps = self.setup.build_steps(
            args,
            python_exe="python",
            cmake_exe=Path("cmake"),
            project_root=Path("C:/repo"),
        )
        names = [step.name for step in steps]
        commands = [" ".join(str(part) for part in step.command) for step in steps]

        self.assertEqual(
            names,
            [
                "Install Python dependencies",
                "Install Playwright Chromium",
                "Configure C++ build",
                "Build C++ DLL and tests",
                "Download tablebase",
                "Run Python tests",
                "Run C++ tests",
            ],
        )
        self.assertIn("python -m pip install -r C:\\repo\\requirements.txt", commands[0])
        self.assertIn("python scripts/download_tablebase.py --repo-id YatzCore/aleatrix-solver-tablebase", commands[4])


if __name__ == "__main__":
    unittest.main()
