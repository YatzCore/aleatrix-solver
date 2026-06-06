import importlib.util
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_download_module():
    path = PROJECT_ROOT / "scripts" / "download_tablebase.py"
    spec = importlib.util.spec_from_file_location("download_tablebase", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_release_module():
    path = PROJECT_ROOT / "scripts" / "build_windows_release.py"
    spec = importlib.util.spec_from_file_location("build_windows_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.download = load_download_module()

    def test_release_launchers_use_prebuilt_runtime(self):
        setup_text = (PROJECT_ROOT / "SETUP_WINDOWS.bat").read_text(encoding="utf-8")
        run_text = (PROJECT_ROOT / "RUN_BOT.bat").read_text(encoding="utf-8")

        self.assertIn(r"scripts\setup_windows.py --skip-build", setup_text)
        self.assertIn("yahtzee_bot.py", run_text)
        self.assertIn("%*", run_text)

    def test_tablebase_download_writes_directly_to_output_directory(self):
        output_dir = Path("C:/aleatrix/cpp")
        expected_path = output_dir / "tablebase.bin"

        with patch.object(self.download, "hf_hub_download", return_value=str(expected_path)) as mocked:
            result = self.download.download_file(
                "YatzCore/aleatrix-solver-tablebase",
                "tablebase.bin",
                output_dir,
            )

        self.assertEqual(result, expected_path)
        mocked.assert_called_once_with(
            repo_id="YatzCore/aleatrix-solver-tablebase",
            filename="tablebase.bin",
            repo_type="dataset",
            local_dir=output_dir,
        )

    def test_runtime_targets_do_not_link_openmp_and_use_static_msvc_runtime(self):
        cmake_text = (PROJECT_ROOT / "cpp" / "CMakeLists.txt").read_text(encoding="utf-8")

        self.assertIn("CMAKE_MSVC_RUNTIME_LIBRARY", cmake_text)
        self.assertIn(
            "target_link_libraries(yahtzee_core PRIVATE OpenMP::OpenMP_CXX)",
            cmake_text,
        )
        self.assertNotIn(
            "target_link_libraries(yahtzee_core_shared PRIVATE OpenMP::OpenMP_CXX)",
            cmake_text,
        )
        self.assertNotIn(
            "target_link_libraries(yahtzee_core_tests PRIVATE OpenMP::OpenMP_CXX)",
            cmake_text,
        )

    @unittest.skipUnless(shutil.which("git"), "Git is required to test release packaging")
    def test_release_builder_exports_head_and_injects_prebuilt_binaries(self):
        release = load_release_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            binary_dir = temp_root / "bin"
            output_dir = temp_root / "dist"
            repo_root.mkdir()
            binary_dir.mkdir()

            (repo_root / "README.md").write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repo_root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "release@example.invalid"],
                cwd=repo_root,
                check=True,
            )
            subprocess.run(["git", "add", "README.md"], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-qm", "test fixture"], cwd=repo_root, check=True)
            (repo_root / "untracked.txt").write_text("do not package\n", encoding="utf-8")

            (binary_dir / "yahtzee_core.dll").write_bytes(b"dll")
            (binary_dir / "yahtzee_core_tests.exe").write_bytes(b"exe")

            archive_path = release.build_release_archive(
                repo_root=repo_root,
                version="v1.0.0",
                binary_dir=binary_dir,
                output_dir=output_dir,
            )

            self.assertEqual(
                archive_path.name,
                "aleatrix-solver-v1.0.0-windows-x64.zip",
            )
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                metadata = archive.read(
                    "aleatrix-solver-v1.0.0/RELEASE_BUILD.txt"
                ).decode("utf-8")

            self.assertIn("aleatrix-solver-v1.0.0/README.md", names)
            self.assertIn(
                "aleatrix-solver-v1.0.0/cpp/build/Release/yahtzee_core.dll",
                names,
            )
            self.assertIn(
                "aleatrix-solver-v1.0.0/cpp/build/Release/yahtzee_core_tests.exe",
                names,
            )
            self.assertNotIn("aleatrix-solver-v1.0.0/untracked.txt", names)
            self.assertIn("Version: v1.0.0", metadata)
            self.assertIn("Architecture: windows-x64", metadata)
            self.assertNotIn(str(temp_root), metadata)


if __name__ == "__main__":
    unittest.main()
