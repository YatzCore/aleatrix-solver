import argparse
import hashlib
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download


DEFAULT_REPO_ID = "YatzCore/aleatrix-solver-tablebase"
EXPECTED_SIZE = 5_571_346_432


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksum(path):
    text = Path(path).read_text(encoding="utf-8").strip()
    return text.split()[0].lower()


def download_file(repo_id, filename, repo_type="dataset"):
    return Path(hf_hub_download(repo_id=repo_id, filename=filename, repo_type=repo_type))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download and verify the Yahtzee tablebase from Hugging Face.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="Hugging Face dataset repo id.")
    parser.add_argument("--output-dir", default=Path("cpp"), type=Path, help="Directory for tablebase files.")
    parser.add_argument("--skip-hash", action="store_true", help="Skip SHA-256 verification.")
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    bin_cache_path = download_file(args.repo_id, "tablebase.bin")
    meta_cache_path = download_file(args.repo_id, "tablebase.meta.json")
    checksum_cache_path = download_file(args.repo_id, "tablebase.sha256")

    tablebase_path = args.output_dir / "tablebase.bin"
    meta_path = args.output_dir / "tablebase.meta.json"
    checksum_path = args.output_dir / "tablebase.sha256"

    shutil.copy2(bin_cache_path, tablebase_path)
    shutil.copy2(meta_cache_path, meta_path)
    shutil.copy2(checksum_cache_path, checksum_path)

    actual_size = tablebase_path.stat().st_size
    if actual_size != EXPECTED_SIZE:
        raise SystemExit(f"Bad tablebase size: expected {EXPECTED_SIZE}, got {actual_size}")

    if not args.skip_hash:
        expected_hash = read_checksum(checksum_path)
        actual_hash = sha256_file(tablebase_path)
        if actual_hash != expected_hash:
            raise SystemExit(f"Bad tablebase SHA-256: expected {expected_hash}, got {actual_hash}")

    print(f"Downloaded verified tablebase to {tablebase_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
