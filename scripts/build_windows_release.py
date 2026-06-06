import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


REQUIRED_BINARIES = ("yahtzee_core.dll", "yahtzee_core_tests.exe")


def archive_name(version):
    return f"aleatrix-solver-{version}-windows-x64.zip"


def release_root_name(version):
    return f"aleatrix-solver-{version}"


def git_output(repo_root, *args):
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write_release_zip(source_dir, archive_path):
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(source_dir.parent).as_posix()
            info = zipfile.ZipInfo(relative_path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def build_release_archive(repo_root, version, binary_dir, output_dir):
    repo_root = Path(repo_root).resolve()
    binary_dir = Path(binary_dir).resolve()
    output_dir = Path(output_dir).resolve()

    missing = [name for name in REQUIRED_BINARIES if not (binary_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing release binaries: {', '.join(missing)}")

    commit = git_output(repo_root, "rev-parse", "HEAD")
    root_name = release_root_name(version)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name(version)

    with tempfile.TemporaryDirectory(prefix="aleatrix-release-") as temp_dir:
        temp_root = Path(temp_dir)
        source_archive = temp_root / "source.zip"
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "archive",
                "--format=zip",
                f"--prefix={root_name}/",
                f"--output={source_archive}",
                "HEAD",
            ],
            check=True,
        )

        with zipfile.ZipFile(source_archive) as source_zip:
            source_zip.extractall(temp_root / "staging")

        release_root = temp_root / "staging" / root_name
        release_binary_dir = release_root / "cpp" / "build" / "Release"
        release_binary_dir.mkdir(parents=True, exist_ok=True)
        for name in REQUIRED_BINARIES:
            shutil.copy2(binary_dir / name, release_binary_dir / name)

        metadata = (
            "Aleatrix Solver prebuilt release\n"
            f"Version: {version}\n"
            f"Commit: {commit}\n"
            "Architecture: windows-x64\n"
            "Tablebase: https://huggingface.co/datasets/YatzCore/aleatrix-solver-tablebase\n"
        )
        (release_root / "RELEASE_BUILD.txt").write_text(metadata, encoding="utf-8")
        write_release_zip(release_root, archive_path)

    return archive_path


def parse_args(argv=None):
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build the precompiled Windows release ZIP.")
    parser.add_argument("--version", required=True, help="Release tag, for example v1.0.0.")
    parser.add_argument("--repo-root", type=Path, default=project_root)
    parser.add_argument(
        "--binary-dir",
        type=Path,
        default=project_root / "cpp" / "build" / "Release",
    )
    parser.add_argument("--output-dir", type=Path, default=project_root / "dist")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    archive_path = build_release_archive(
        repo_root=args.repo_root,
        version=args.version,
        binary_dir=args.binary_dir,
        output_dir=args.output_dir,
    )
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
