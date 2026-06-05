import argparse
from pathlib import Path

from huggingface_hub import HfApi, create_repo


DEFAULT_REPO_ID = "YatzCore/aleatrix-solver-tablebase"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Upload tablebase release files to a Hugging Face dataset repo.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="Target Hugging Face dataset repo id.")
    parser.add_argument("--tablebase-path", default=Path("cpp/tablebase.bin"), type=Path)
    parser.add_argument("--release-dir", default=Path("dist/hf-tablebase"), type=Path)
    parser.add_argument("--private", action="store_true", help="Create the dataset as private.")
    args = parser.parse_args(argv)

    required = [
        args.tablebase_path,
        args.release_dir / "tablebase.meta.json",
        args.release_dir / "tablebase.sha256",
        args.release_dir / "README.md",
    ]
    for path in required:
        if not path.exists():
            raise SystemExit(f"Missing release file: {path}")

    create_repo(args.repo_id, repo_type="dataset", private=args.private, exist_ok=True)
    api = HfApi()
    api.upload_file(
        repo_id=args.repo_id,
        repo_type="dataset",
        path_or_fileobj=str(args.tablebase_path),
        path_in_repo="tablebase.bin",
    )
    for filename in ["tablebase.meta.json", "tablebase.sha256", "README.md"]:
        api.upload_file(
            repo_id=args.repo_id,
            repo_type="dataset",
            path_or_fileobj=str(args.release_dir / filename),
            path_in_repo=filename,
        )

    print(f"Uploaded tablebase dataset to https://huggingface.co/datasets/{args.repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
