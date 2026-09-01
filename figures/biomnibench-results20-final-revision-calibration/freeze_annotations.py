from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet_dir", type=Path)
    parser.add_argument("annotation_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    index = json.loads((args.packet_dir / "index.json").read_text(encoding="utf-8"))
    if not isinstance(index, list) or len(index) != 317:
        raise RuntimeError("packet index is incomplete")
    expected = {str(row["case_id"]): row for row in index}
    annotations: dict[str, dict[str, object]] = {}
    for value in sorted(glob.glob(str(args.annotation_dir / "batch-*.json"))):
        batch = json.loads(Path(value).read_text(encoding="utf-8"))
        rows = batch.get("annotations")
        if not isinstance(rows, list):
            raise RuntimeError(f"annotation batch is invalid: {value}")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
                raise RuntimeError(f"annotation row is invalid: {value}")
            case_id = row["case_id"]
            if case_id in annotations:
                raise RuntimeError(f"duplicate annotation: {case_id}")
            annotations[case_id] = row
    if set(annotations) != set(expected):
        missing = sorted(set(expected) - set(annotations))
        extra = sorted(set(annotations) - set(expected))
        raise RuntimeError(f"annotation mismatch; missing={missing}, extra={extra}")
    lines = []
    for case_id in sorted(expected):
        source = expected[case_id]
        row = {
            "case_id": case_id,
            "split": source["split"],
            "packet_sha256": source["packet_sha256"],
            **{key: value for key, value in annotations[case_id].items() if key != "case_id"},
        }
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    content = "\n".join(lines) + "\n"
    args.output.write_text(content, encoding="utf-8")
    print(hashlib.sha256(content.encode()).hexdigest())


if __name__ == "__main__":
    main()
