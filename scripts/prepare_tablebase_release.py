import argparse
import hashlib
import json
import shutil
from pathlib import Path


DEFAULT_REPO_ID = "YatzCore/aleatrix-solver-tablebase"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_card(repo_id, meta, checksum):
    return f"""---
license: mit
pretty_name: Aleatrix Solver Yahtzee Tablebase
tags:
- yahtzee
- tablebase
- game-ai
---

# Aleatrix Solver Yahtzee Tablebase

This dataset contains the generated win-probability tablebase for
[`YatzCore/aleatrix-solver`](https://github.com/YatzCore/aleatrix-solver).

## Files

- `tablebase.bin`: raw memory-mapped tablebase.
- `tablebase.meta.json`: tablebase format and solver metadata.
- `tablebase.sha256`: checksum for local verification.

## Metadata

```json
{json.dumps(meta, indent=2)}
```

SHA-256:

```text
{checksum}  tablebase.bin
```

## Use

```powershell
python scripts/download_tablebase.py --repo-id {repo_id}
```

Advanced users can rebuild the file locally from the C++ generator in the
GitHub repository instead of downloading this artifact.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare Hugging Face dataset files for the tablebase release.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="Target Hugging Face dataset repo id.")
    parser.add_argument("--tablebase-path", default=Path("cpp/tablebase.bin"), type=Path)
    parser.add_argument("--metadata-path", default=Path("cpp/tablebase.meta.json"), type=Path)
    parser.add_argument("--output-dir", default=Path("dist/hf-tablebase"), type=Path)
    parser.add_argument("--copy-bin", action="store_true", help="Copy tablebase.bin into the staging directory.")
    args = parser.parse_args(argv)

    if not args.tablebase_path.exists():
        raise SystemExit(f"Missing tablebase: {args.tablebase_path}")
    if not args.metadata_path.exists():
        raise SystemExit(f"Missing metadata: {args.metadata_path}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checksum = sha256_file(args.tablebase_path)
    meta_bytes = args.metadata_path.read_bytes()
    meta = json.loads(meta_bytes.decode("utf-8"))

    (args.output_dir / "tablebase.meta.json").write_bytes(meta_bytes)
    (args.output_dir / "tablebase.sha256").write_text(f"{checksum}  tablebase.bin\n", encoding="utf-8")
    (args.output_dir / "README.md").write_text(dataset_card(args.repo_id, meta, checksum), encoding="utf-8")

    if args.copy_bin:
        shutil.copy2(args.tablebase_path, args.output_dir / "tablebase.bin")

    print(f"Prepared tablebase release files in {args.output_dir}")
    print(f"SHA-256: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
