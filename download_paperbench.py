"""Download the pinned PaperBench dev split in Code-Dev task format."""

import argparse
from pathlib import Path

from rubric_gen.paperbench.loader import download_paperbench_code_dev


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    destination = download_paperbench_code_dev(args.output)
    print(f"Loaded PaperBench Code-Dev tasks at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
