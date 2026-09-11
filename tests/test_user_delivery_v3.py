import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rubric_gen.submission_revision.feedback import (
    ProjectedFeedback,
    derive_base_requirement_status,
    project_rubric_simulated_user_feedback,
    render_revision_prompt,
)
from rubric_gen.submission_revision.rubric_generation import ElicitedCriterion
from rubric_gen.submission_revision.user_delivery_v3 import (
    persist_private_delivery,
    select_private_delivery,
)
from rubric_gen.submission_revision.user_simulator import (
    _feedback_request_v3,
    _validate_feedback_output,
)


def _criterion(title="Learned check", points=0, source=2):
    return ElicitedCriterion.create(
        title=title,
        requirement="Check the public result and repair only this scoped issue.",
        levels=(("A", 0, "Pass."), ("B", points or -5, "Moderate."), ("C", -10, "Material.")),
        provenance_pair_ids=("pair_" + "0" * 16,),
        source_generation=source,
    )


def _generation(criteria, round=2):
    return SimpleNamespace(
        generation_round=round,
        generation_sha256="a" * 64,
        elicited_criteria=tuple(criteria),
        rubric=SimpleNamespace(content="base rubric", content_sha256="b" * 64),
    )


class UserDeliveryV3Tests(unittest.TestCase):
    def test_v3_output_has_private_origin_and_is_stripped_for_solver(self):
        value = {
            "decision": "revise",
            "concerns": [{"category": "task_fulfillment", "feedback": "Complete the requested table.", "origin": "base_requirement"}],
        }
        parsed = _validate_feedback_output(value, max_concerns=3, allow_origin=True)
        self.assertEqual(parsed["concerns"][0]["origin"], "base_requirement")
        with tempfile.TemporaryDirectory() as td:
            # The projection only needs a score composition; use a patched native scorer.
            score = Path(td) / "score.json"
            score.write_text("{}")
            generation = _generation(())
            with patch("rubric_gen.submission_revision.feedback.compose_rubric_score", return_value=SimpleNamespace(score=80.0)):
                projected = project_rubric_simulated_user_feedback(
                    generation, score, parsed, task_instruction="Do task", first_revision=True,
                    reference_score=80.0,
                )
        self.assertNotIn("origin", projected.payload["concerns"][0])
        self.assertNotIn("base_requirement", projected.prompt)
        self.assertLessEqual(len(projected.payload["concerns"]), 3)

    def test_v3_prompt_contains_budget_policy_and_private_inputs(self):
        request = _feedback_request_v3(
            instruction="Compute the requested table.", full_feedback_text="{}",
            current_artifact="answer", history_context="[]", max_concerns=3,
            max_output_tokens=1024,
            focused_dynamic_check={"mode": "corrective", "requirement": "Check X", "newly_admitted": True, "currently_violated": True},
            base_requirement_status=[{"title": "Table", "point_loss": 5}],
        )
        self.assertIn("Choose at most three concerns TOTAL", request.instructions)
        self.assertIn("Repair locally rather than deleting useful work", request.instructions)
        self.assertIn("<focused_dynamic_check>", request.evidence)
        self.assertIn("<base_requirement_status>", request.evidence)
        self.assertEqual(request.schema_name, "submission_simulated_user_feedback_trace_v3")
        self.assertEqual(request.schema["properties"]["concerns"]["maxItems"], 3)

    def test_private_selection_uses_same_priority_and_receipt_has_no_fourth_message(self):
        criterion = _criterion()
        generation = _generation((criterion,))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "trace-defense-reminders").mkdir()
            score_path = root / "score.json"
            score_path.write_text("{}")
            with patch(
                "rubric_gen.submission_revision.user_delivery_v3._validate_score_record",
                return_value=(0.0, 0.0, {}, {"criterion_1": 0.0, "criterion_2": -5.0}),
            ):
                selected, skipped = select_private_delivery(
                    generation=generation, score_validation_path=score_path, root=root,
                    submission_id="s000", instruction="Compute the requested table.",
                )
                self.assertIsNotNone(selected)
                user_feedback = {"decision": "revise", "concerns": [{
                    "category": "calculation_correctness", "feedback": "Repair X.", "origin": "dynamic_corrective",
                }]}
                record = persist_private_delivery(
                    root=root, submission_id="s000", generation=generation,
                    selection=selected, skipped=skipped, ordinary_prompt="ordinary",
                    allow_generation=True, user_feedback=user_feedback,
                )
            self.assertTrue(record["emitted"])
            self.assertEqual(record["message_component"], "")
            self.assertEqual(record["ordinary_prompt_sha256"], record["final_prompt_sha256"])
            self.assertEqual(json.loads((root / "trace-defense-reminders/s000.json").read_text())["delivery_mode"], "user_simulator_private")

    def test_proactive_accept_is_not_forced_to_revise(self):
        criterion = _criterion(points=0, source=1)
        generation = _generation((criterion,), round=2)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "trace-defense-reminders").mkdir()
            score_path = root / "score.json"
            score_path.write_text("{}")
            with patch(
                "rubric_gen.submission_revision.user_delivery_v3._validate_score_record",
                return_value=(0.0, 0.0, {}, {"criterion_1": 0.0, "criterion_2": 0.0}),
            ):
                selected, skipped = select_private_delivery(
                    generation=generation, score_validation_path=score_path, root=root,
                    submission_id="s000", instruction="Compute the requested table.",
                )
                record = persist_private_delivery(
                    root=root, submission_id="s000", generation=generation,
                    selection=selected, skipped=skipped, ordinary_prompt="ordinary",
                    allow_generation=True, user_feedback={"decision": "accept", "concerns": []},
                )
        self.assertFalse(record["emitted"])
        self.assertEqual(record["omission_reason"], "proactive check not currently actionable")

    def test_legacy_solver_prompt_has_no_v3_origin_or_fourth_message(self):
        payload = {"decision": "revise", "concerns": [{"category": "task_fulfillment", "feedback": "Finish the table."}]}
        prompt = render_revision_prompt("user_simulator", payload, task_instruction="Do task", first_revision=True)
        self.assertIn("Finish the table.", prompt)
        self.assertNotIn("dynamic_corrective", prompt)
        self.assertNotIn("Focused review check", prompt)

    def test_base_status_is_deterministic_and_loss_ranked(self):
        first = SimpleNamespace(title="Base one", levels=(SimpleNamespace(points=10),))
        second = SimpleNamespace(title="Base two", levels=(SimpleNamespace(points=10),))
        fake_rubric = SimpleNamespace(criteria=(first, second))
        feedback = {"criteria": {
            "criterion_1": {"level": "B", "points": 5, "judge_reason": "first"},
            "criterion_2": {"level": "C", "points": 0, "judge_reason": "second"},
        }}
        with patch("rubric_gen.submission_revision.feedback.parse_autorubric_rubric", return_value=fake_rubric):
            status = derive_base_requirement_status(feedback, "frozen")
        self.assertEqual([item["title"] for item in status], ["Base two", "Base one"])
        self.assertEqual(status[0]["point_loss"], 10.0)

    def test_v3_registry_reuses_v21_learning_path(self):
        from rubric_gen.submission_revision.trace_defense_registry import recipe
        v3 = recipe("attack_defense_v3")
        v21 = recipe("attack_defense_v2.1")
        self.assertEqual(v3.learning_module, v21.learning_module)
        self.assertEqual(v3.attack_module, v21.attack_module)

    def test_v3_prompt_protects_satisfied_work_and_no_hidden_targets(self):
        request = _feedback_request_v3(
            instruction="Task", full_feedback_text="points hidden", current_artifact="artifact",
            history_context="history", max_concerns=3, max_output_tokens=1024,
            focused_dynamic_check=None, base_requirement_status=[],
        )
        self.assertIn("Preserve already satisfied requested outputs", request.instructions)
        self.assertIn("Never expose expected answers, target values, scores, points", request.instructions)

    def test_v3_receipt_records_omission_reason_when_budget_is_full(self):
        criterion = _criterion(points=-5)
        generation = _generation((criterion,))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "trace-defense-reminders").mkdir()
            score_path = root / "score.json"
            score_path.write_text("{}")
            with patch(
                "rubric_gen.submission_revision.user_delivery_v3._validate_score_record",
                return_value=(0.0, 0.0, {}, {"criterion_1": 0.0, "criterion_2": -5.0}),
            ):
                selected, skipped = select_private_delivery(
                    generation=generation, score_validation_path=score_path, root=root,
                    submission_id="s000", instruction="Task",
                )
                record = persist_private_delivery(
                    root=root, submission_id="s000", generation=generation, selection=selected,
                    skipped=skipped, ordinary_prompt="ordinary", allow_generation=True,
                    user_feedback={"decision": "revise", "concerns": [
                        {"category": "task_fulfillment", "feedback": "1", "origin": "base_requirement"},
                        {"category": "method_choice", "feedback": "2", "origin": "general_task"},
                        {"category": "result_reporting", "feedback": "3", "origin": "base_requirement"},
                    ]},
                )
        self.assertFalse(record["emitted"])
        self.assertEqual(record["omission_reason"], "higher-priority base/task concerns filled the concern budget")


if __name__ == "__main__":
    unittest.main()
