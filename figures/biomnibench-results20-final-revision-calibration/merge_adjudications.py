from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path


def _rows(path: Path) -> dict[str, dict[str, object]]:
    return {
        row["case_id"]: row
        for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("adjudication_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    first = _rows(args.first)
    second = _rows(args.second)
    if set(first) != set(second) or len(first) != 317:
        raise RuntimeError("independent annotation passes are incomplete")
    adjudications: dict[str, dict[str, object]] = {}
    for value in sorted(glob.glob(str(args.adjudication_dir / "batch-*.json"))):
        batch = json.loads(Path(value).read_text(encoding="utf-8"))
        for row in batch.get("annotations", []):
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or case_id in adjudications:
                raise RuntimeError(f"invalid adjudication row: {value}")
            adjudications[case_id] = row
    disagreements = {
        case_id for case_id in first
        if first[case_id]["label"] != second[case_id]["label"]
    }
    if set(adjudications) != disagreements:
        raise RuntimeError("adjudications do not match independent disagreements")
    lines = []
    for case_id in sorted(first):
        if case_id in disagreements:
            selected = adjudications[case_id]
            method = "disagreement_adjudication"
        else:
            selected = first[case_id]
            method = "independent_agreement"
        row = {
            "case_id": case_id,
            "split": first[case_id]["split"],
            "packet_sha256": first[case_id]["packet_sha256"],
            "annotation_method": method,
            **{
                key: value for key, value in selected.items()
                if key not in {"case_id", "split", "packet_sha256"}
            },
        }
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    content = "\n".join(lines) + "\n"
    args.output.write_text(content, encoding="utf-8")
    print(hashlib.sha256(content.encode()).hexdigest())


if __name__ == "__main__":
    main()
