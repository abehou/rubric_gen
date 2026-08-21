"""Download one pinned PaperBench paper set in Code-Dev task format."""

import argparse
from pathlib import Path

from rubric_gen.benchmarks.paperbench_code_dev.dataset import (
    download_paperbench_code_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_split", choices=("dev", "all"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    destination = download_paperbench_code_dataset(
        args.output,
        source_split=args.source_split,
    )
    print(f"Loaded PaperBench Code-Dev tasks at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
