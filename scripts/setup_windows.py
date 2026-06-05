import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TABLEBASE_REPO_ID = "YatzCore/aleatrix-solver-tablebase"


@dataclass(frozen=True)
class Step:
    name: str
    command: list


def default_cmake_candidates():
    return [
        Path("C:/Program Files/CMake/bin/cmake.exe"),
        Path("C:/Program Files (x86)/CMake/bin/cmake.exe"),
        Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"),
        Path("C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"),
        Path("C:/Program Files/Microsoft Visual Studio/2022/Professional/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"),
        Path("C:/Program Files/Microsoft Visual Studio/2022/Enterprise/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"),
    ]


def find_cmake(explicit_path=None, which_func=shutil.which, candidate_paths=None, exists_func=None):
    exists_func = exists_func or (lambda path: Path(path).exists())
    if explicit_path is not None:
        return Path(explicit_path)

    found = which_func("cmake")
    if found:
        return Path(found)

    for candidate in candidate_paths or default_cmake_candidates():
        candidate = Path(candidate)
        if exists_func(candidate):
            return candidate

    return Path("cmake")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Set up Aleatrix Solver on Windows.")
    parser.add_argument("--repo-id", default=DEFAULT_TABLEBASE_REPO_ID, help="Hugging Face dataset repo for tablebase download.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use for setup commands.")
    parser.add_argument("--cmake", type=Path, default=None, help="Path to cmake.exe if it is not on PATH.")
    parser.add_argument("--skip-deps", action="store_true", help="Skip Python dependency installation.")
    parser.add_argument("--skip-playwright", action="store_true", help="Skip Playwright Chromium installation.")
    parser.add_argument("--skip-build", action="store_true", help="Skip C++ configure/build.")
    parser.add_argument("--skip-tablebase", action="store_true", help="Skip Hugging Face tablebase download.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip Python and C++ verification tests.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    return parser.parse_args(argv)


def build_steps(args, python_exe, cmake_exe, project_root):
    project_root = Path(project_root)
    cpp_build_dir = project_root / "cpp" / "build"
    steps = []

    if not args.skip_deps:
        steps.append(Step("Install Python dependencies", [python_exe, "-m", "pip", "install", "-r", project_root / "requirements.txt"]))
    if not args.skip_playwright:
        steps.append(Step("Install Playwright Chromium", [python_exe, "-m", "playwright", "install", "chromium"]))
    if not args.skip_build:
        steps.append(Step("Configure C++ build", [cmake_exe, "-S", project_root / "cpp", "-B", cpp_build_dir, "-DCMAKE_BUILD_TYPE=Release"]))
        steps.append(Step("Build C++ DLL and tests", [cmake_exe, "--build", cpp_build_dir, "--config", "Release"]))
    if not args.skip_tablebase:
        steps.append(Step("Download tablebase", [python_exe, "scripts/download_tablebase.py", "--repo-id", args.repo_id]))
    if not args.skip_tests:
        steps.append(Step("Run Python tests", [python_exe, "-m", "unittest", "discover", "-v"]))
        steps.append(Step("Run C++ tests", [project_root / "cpp" / "build" / "Release" / "yahtzee_core_tests.exe"]))

    return steps


def format_command(command):
    return " ".join(str(part) for part in command)


def run_step(step, project_root, dry_run=False):
    print(f"\n==> {step.name}")
    print(format_command(step.command))
    if dry_run:
        return
    try:
        subprocess.run([str(part) for part in step.command], cwd=project_root, check=True)
    except FileNotFoundError as exc:
        missing = step.command[0]
        raise SystemExit(
            f"Could not run {missing}. Install CMake/Visual Studio Build Tools, "
            "or pass --cmake C:\\path\\to\\cmake.exe."
        ) from exc


def main(argv=None):
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    python_exe = args.python
    cmake_exe = find_cmake(args.cmake)
    steps = build_steps(args, python_exe=python_exe, cmake_exe=cmake_exe, project_root=project_root)

    for step in steps:
        run_step(step, project_root=project_root, dry_run=args.dry_run)

    print("\nSetup complete.")
    print("Run the standalone browser controller with:")
    print("python -u yahtzee_bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
