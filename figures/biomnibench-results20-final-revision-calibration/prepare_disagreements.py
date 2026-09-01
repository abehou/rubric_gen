from __future__ import annotations

import argparse
import json
from pathlib import Path


def _rows(path: Path) -> dict[str, dict[str, object]]:
    return {
        row["case_id"]: row
        for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet_dir", type=Path)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    first = _rows(args.first)
    second = _rows(args.second)
    if set(first) != set(second) or len(first) != 317:
        raise RuntimeError("independent annotation passes are incomplete")
    source_index = {
        row["case_id"]: row
        for row in json.loads(
            (args.packet_dir / "index.json").read_text(encoding="utf-8")
        )
    }
    disagreements = [
        case_id for case_id in sorted(first)
        if first[case_id]["label"] != second[case_id]["label"]
    ]
    if not disagreements:
        raise RuntimeError("annotation passes have no disagreements")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for case_id in disagreements:
        packet = json.loads(
            (args.packet_dir / f"{case_id}.json").read_text(encoding="utf-8")
        )
        packet["independent_annotation_A"] = {
            key: value for key, value in first[case_id].items()
            if key not in {"case_id", "split", "packet_sha256"}
        }
        packet["independent_annotation_B"] = {
            key: value for key, value in second[case_id].items()
            if key not in {"case_id", "split", "packet_sha256"}
        }
        text = json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n"
        (args.output_dir / f"{case_id}.json").write_text(text, encoding="utf-8")
        index.append({
            **source_index[case_id],
            "packet_chars": len(text),
        })
    (args.output_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
