import json

from rubric_gen.submission_revision import (
    execution_verified_complete_public_prompts as complete_public_prompts,
)
from rubric_gen.submission_revision.task_required_enforced_schema import (
    EnforcementContract,
    enforcement_schema,
)
from rubric_gen.submission_revision.task_required_enforcement import (
    EXECUTION_VERIFIED_PROACTIVE_PROVENANCE_COMPLETE_PUBLIC_VERSION,
    EXECUTION_VERIFIED_PROACTIVE_PROVENANCE_VERSION,
    _public_execution_status_summary,
)
from rubric_gen.submission_revision.trace_defense_evidence_v2 import PublicDocument
from rubric_gen.submission_revision.trace_defense_registry import recipe


def test_complete_public_changes_only_enforcement_review():
    resolved = recipe(
        EXECUTION_VERIFIED_PROACTIVE_PROVENANCE_COMPLETE_PUBLIC_VERSION
    )
    base = recipe(EXECUTION_VERIFIED_PROACTIVE_PROVENANCE_VERSION)

    assert resolved.prompts.PROMPT_VERSION == (
        EXECUTION_VERIFIED_PROACTIVE_PROVENANCE_COMPLETE_PUBLIC_VERSION
    )
    assert resolved.prompts.DIAGNOSIS_V2 == base.prompts.DIAGNOSIS_V2
    assert (
        resolved.prompts.SOLVER_EXECUTION_TRUTHFULNESS
        == base.prompts.SOLVER_EXECUTION_TRUTHFULNESS
    )
    assert "inspect every deliverable" in complete_public_prompts.ENFORCEMENT_V2
    assert "named external database" in complete_public_prompts.ENFORCEMENT_V2


def test_status_summary_surfaces_conflicting_public_claims():
    summary = json.loads(_public_execution_status_summary(
        "# trace.md\nThe current analysis completed successfully.\n"
        "# answer.txt\nThe fresh rerun did not complete.\n"
    ))
    lines = [item["text"] for item in summary["status_candidates"]]

    assert "The current analysis completed successfully." in lines
    assert "The fresh rerun did not complete." in lines


def test_unresolved_issue_reuses_saved_instruction_without_retry():
    prior_issue = {
        "requirement": "Run the required analysis.",
        "defect": "The saved output contradicts the answer.",
        "corrective_action": "Synchronize the answer with fresh output.",
        "preserve_supported_work": "Preserve the valid data inspection.",
        "if_execution_unavailable": "Withdraw unsupported numerical claims.",
    }
    documents = {
        "task": PublicDocument("task", "The analysis and answer are required."),
        "artifact": PublicDocument(
            "artifact",
            "# trace.md\nCompleted.\n# answer.txt\nThe rerun did not complete.",
        ),
        "prior_issue": PublicDocument("prior_issue", json.dumps(prior_issue)),
    }
    contract = EnforcementContract(
        stage="enforcement",
        schema=enforcement_schema(documents, execution_verified=True),
        documents=documents,
        native_ids={name: name for name in documents},
        execution_verified=True,
        prior_issue=prior_issue,
    )
    response = {
        "decision": "correct",
        "prior_issue_status": "unresolved",
        "requirement": "The task still requires running the analysis.",
        "defect": "The artifact still contradicts the output.",
        "public_evidence": "The answer still says the rerun did not complete.",
        "corrective_action": "Make every public file agree.",
        "preserve_supported_work": "Keep correct work.",
        "if_execution_unavailable": "Say it is incomplete.",
        "evidence_refs": [
            {"source_id": "prior_issue", "start_line": 1, "end_line": 1},
            {"source_id": "artifact", "start_line": 1, "end_line": 4},
        ],
        "reason": "The same contradiction remains in the complete artifact.",
    }

    contract.validate(response)

    for field, expected in prior_issue.items():
        assert response[field] == expected
