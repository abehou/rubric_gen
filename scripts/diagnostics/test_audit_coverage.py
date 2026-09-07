"""Read-only regression checks against the preserved current-format acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from check_audit_coverage import check, check_semantic_records

REPO = Path(__file__).resolve().parents[2]
STUDY = REPO / "runs/biomnibench-redteam-2026-09-05/acceptance/study"
AUDIT = REPO / "runs/biomnibench-redteam-2026-09-05/acceptance/audit"
STAGES = ("rubric_score", "absolute_score", "pairwise_preference")


class CoverageChecks(unittest.TestCase):
    def summary(self, stage):
        return json.loads((AUDIT / stage / "summary.json").read_text())

    def test_preserved_acceptance_passes(self):
        self.assertEqual(check(STUDY, AUDIT)["semantic_judgments"], 153)

    def test_missing_semantic_reference_rejected(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                summary = self.summary(stage)
                key = summary["records"][0]["judgment_key"]
                summary["records"] = [r for r in summary["records"] if r["judgment_key"] != key]
                with self.assertRaises(AssertionError):
                    check_semantic_records(AUDIT / stage, stage, summary)

    def test_duplicate_plan_key_rejected(self):
        summary = self.summary("rubric_score")
        summary["predispatch_plan"]["jobs"].append(deepcopy(summary["predispatch_plan"]["jobs"][0]))
        with self.assertRaises(AssertionError):
            check_semantic_records(AUDIT / "rubric_score", "rubric_score", summary)

    def test_changed_summary_outcome_rejected(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                summary = self.summary(stage)
                if stage == "rubric_score":
                    summary["records"][0]["score"] += 1
                else:
                    summary["records"][0]["verdict"]["explanation"] = "changed in memory only"
                with self.assertRaises(AssertionError):
                    check_semantic_records(AUDIT / stage, stage, summary)

    def test_changed_saved_record_rejected_without_disk_mutation(self):
        original_read = Path.read_bytes
        for stage in STAGES:
            with self.subTest(stage=stage):
                summary = self.summary(stage)
                target = AUDIT / stage / "records" / (summary["records"][0]["judgment_key"] + ".json")

                def changed_read(path):
                    contents = original_read(path)
                    if path == target:
                        payload = json.loads(contents)
                        if stage == "rubric_score":
                            payload["score"] += 1
                        else:
                            payload["raw_response"] += " "
                        return json.dumps(payload).encode()
                    return contents

                with patch.object(Path, "read_bytes", changed_read):
                    with self.assertRaises(AssertionError):
                        check_semantic_records(AUDIT / stage, stage, summary)


if __name__ == "__main__":
    unittest.main()
