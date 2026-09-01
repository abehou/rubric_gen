from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.evidence import _revision_prompt


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID = "biomnibench-da-factorial-r10-4f4d5d178756"
TASKS_DIR = Path("/juice2/u/nlp/data/abe_models/rubric_gen/data/biomnibench-da")
SUMMARY_GLOB = str(
    ROOT
    / "runs"
    / "detections"
    / EXPERIMENT_ID
    / "direct_final_revision"
    / "evaluations"
    / "*"
    / "summary.json"
)
SPLIT_SEED = "biomnibench-results20-final-revision-calibration-20260901"


def _split(case_id: str) -> str:
    digest = hashlib.sha256(f"{SPLIT_SEED}:{case_id}".encode()).digest()
    return "calibration" if int.from_bytes(digest[:8], "big") % 5 < 3 else "validation"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    paths = [Path(value) for value in glob.glob(SUMMARY_GLOB)]
    if len(paths) != 1:
        raise RuntimeError(f"expected one final-revision summary, found {len(paths)}")
    summary = json.loads(paths[0].read_text(encoding="utf-8"))
    records = summary.get("records")
    if not isinstance(records, list) or len(records) != 951:
        raise RuntimeError("final-revision panel is incomplete")
    sources: dict[str, Path] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("invalid panel record")
        case_id = record.get("case_id")
        source_path = record.get("source_path")
        if not isinstance(case_id, str) or not isinstance(source_path, str):
            raise RuntimeError("panel record lacks a case source")
        source = Path(source_path)
        previous = sources.setdefault(case_id, source)
        if previous != source:
            raise RuntimeError(f"inconsistent source for {case_id}")
    if len(sources) != 317:
        raise RuntimeError(f"expected 317 cases, found {len(sources)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for case_id, source in sorted(sources.items()):
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        task_id = manifest.get("task_id")
        if not isinstance(task_id, str):
            raise RuntimeError(f"case has no task: {case_id}")
        prompt = _revision_prompt(
            source,
            TASKS_DIR,
            "rh",
            RevisionDetectionWindow.FINAL_REVISION,
        )
        packet = {
            "case_id": case_id,
            "task_instruction": (TASKS_DIR / task_id / "instruction.md").read_text(
                encoding="utf-8"
            ),
            "final_revision_evidence_jsonl": prompt.evidence,
        }
        text = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        packet_path = args.output_dir / f"{case_id}.json"
        packet_path.write_text(text + "\n", encoding="utf-8")
        index.append({
            "case_id": case_id,
            "split": _split(case_id),
            "packet_sha256": hashlib.sha256((text + "\n").encode()).hexdigest(),
            "packet_chars": len(text),
        })
    (args.output_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
