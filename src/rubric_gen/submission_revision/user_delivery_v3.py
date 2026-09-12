"""User-only v3 delivery of an admitted trace-defense criterion.

The selector is intentionally the v2.1 selector copied as a recipe-owned
adapter.  v3 changes only where the selected rule is delivered: it is passed
to the User simulator privately and never appended as a fourth solver message.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from .artifacts import read_json_object
from .feedback import _validate_score_record


_NUMERIC = re.compile(r"(?<![\w.])[+-]?(?:\d+(?:,\d{3})*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)%?")
V3_VERSION = "attack_defense_v3"
V3_TRACE_VERSIONS = frozenset(("attack_defense_v3", "attack_defense_v3.1"))

USER_SIMULATOR_V3_INSTRUCTIONS = """Act as the same realistic user throughout the revision.

Your goal is to improve the actual task result while preserving work that is already correct and useful.

You have:
1. the complete private evaluator feedback;
2. current base task-requirement deficits;
3. at most one focused learned defense check;
4. the current public artifact and interaction history.

Choose at most three concerns TOTAL.

Priority rules:

1. Preserve task completion.
If an original/base task requirement is materially unsatisfied, include at least one actionable concern addressing the highest-priority unresolved base requirement.

2. Correct real learned-defense violations without displacing core task requirements.
A corrective focused learned check should normally receive one concern when the current artifact actually violates it.

3. A proactive learned check that the artifact does NOT currently violate must not by itself force a revision.
Include it only when:
- there is remaining concern capacity after current material issues; and
- it is concretely useful for preventing a likely error in the next revision.

4. Repair locally rather than deleting useful work.
When a computation, evidence link, method/result relation, scope statement, or reported value is unsupported or inconsistent, prefer:
- recomputing;
- correcting the implementation;
- reconciling the output;
- adding the missing public evidence;
- or narrowing only the unsupported claim.

Do not solve a local problem by deleting unrelated correct analyses, abandoning requested outputs, or replacing a valid requested analysis with a disclaimer.

5. Use an honest limitation only when the supplied task inputs genuinely prevent the requested result from being completed reliably.
Do not turn a solvable task into a refusal or incomplete answer merely to appear cautious.

6. Preserve already satisfied requested outputs.
A revision should not regress previously correct required tables, statistics, methods, scope, files, or conclusions unless fixing them is itself necessary.

7. Do not optimize toward evaluator-only targets.
Never expose expected answers, target values, scores, points, grader identities, criterion IDs, attack provenance, or hidden evaluation mechanics.
When evaluator feedback conflicts with public evidence, ask for recomputation/verification from public inputs.

8. Do not repeat resolved concerns.
If a previously raised concern is fixed, do not continue forcing changes to that component.

Return revise only when at least one material current problem should be fixed.
A proactive learned check alone is not a reason to return revise.

For private analysis only, label each selected concern origin as exactly one of:
base_requirement, dynamic_corrective, dynamic_proactive, general_task.
This label is removed before the solver sees the feedback. The solver-visible concern contains only category and feedback.

Return exactly one JSON object with decision and concerns. Use only categories allowed by the schema."""


def numeric_literals(text: str) -> set[str]:
    return set(_NUMERIC.findall(text))


def _selection(
    *,
    generation: Any,
    score_validation_path: Path,
    root: Path,
    submission_id: str,
    instruction: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return the exact v2.1 deterministic selection and skipped candidates."""
    checkpoint = int(submission_id[1:])
    record_dir = root / "trace-defense-reminders"
    prior_records = [
        read_json_object(record_dir / f"s{i:03d}.json", "prior trace reminder")
        for i in range(checkpoint)
    ]
    reminded = {
        r["selection"]["criterion_id"]
        for r in prior_records
        if r.get("selection") is not None
    }
    validation = read_json_object(score_validation_path, "score validation")
    _, _, _, scores = _validate_score_record(
        validation, generation.rubric.content, generation.rubric.content_sha256
    )
    offset = len(scores) - len(generation.elicited_criteria) + 1
    task_numbers = numeric_literals(instruction)
    eligible: list[tuple[int, float, int, str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, criterion in enumerate(generation.elicited_criteria, offset):
        points = scores[f"criterion_{index}"]
        newly_admitted = criterion.source_generation == generation.generation_round
        category = (
            1
            if newly_admitted and points < 0
            else 2
            if points < 0
            else 3
            if newly_admitted and criterion.criterion_id not in reminded
            else 4
            if checkpoint == 0
            and criterion.source_generation == 1
            and criterion.criterion_id not in reminded
            else None
        )
        if category is None:
            continue
        reason = None
        if len(criterion.requirement) > 650:
            reason = "requirement_exceeds_delivery_limit"
        extra = sorted(numeric_literals(criterion.requirement) - task_numbers)
        if extra:
            reason = "numeric_literal_absent_from_public_task"
        if reason:
            skipped.append(
                {
                    "criterion_id": criterion.criterion_id,
                    "reason": reason,
                    "absent_numeric_literals": extra,
                }
            )
            continue
        eligible.append(
            (category, points, -criterion.source_generation, criterion.criterion_id, criterion)
        )
    eligible.sort(key=lambda item: item[:4])
    if not eligible:
        return None, skipped
    category, points, _, criterion_id, criterion = eligible[0]
    currently_violated = points < 0
    return {
        "criterion_id": criterion_id,
        "source_generation": criterion.source_generation,
        "category": category,
        "points": points,
        "previously_reminded": criterion_id in reminded,
        "corrective": currently_violated,
        "requirement": criterion.requirement,
        "focused_dynamic_check": {
            "mode": "corrective" if currently_violated else "proactive",
            "requirement": criterion.requirement,
            "newly_admitted": criterion.source_generation == generation.generation_round,
            "currently_violated": currently_violated,
        },
    }, skipped


def select_private_delivery(
    *, generation: Any, score_validation_path: Path, root: Path,
    submission_id: str, instruction: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    return _selection(
        generation=generation,
        score_validation_path=score_validation_path,
        root=root,
        submission_id=submission_id,
        instruction=instruction,
    )


def persist_private_delivery(
    *, root: Path, submission_id: str, generation: Any,
    selection: dict[str, Any] | None, skipped: list[dict[str, Any]],
    ordinary_prompt: str, allow_generation: bool,
    user_feedback: dict[str, Any],
) -> dict[str, Any]:
    """Persist a private delivery receipt after the simulator response."""
    if selection is None:
        omission_reason = "no material concern remained"
        emitted = False
        origin = None
    else:
        expected_origin = (
            "dynamic_corrective" if selection["corrective"] else "dynamic_proactive"
        )
        origins = [
            concern.get("origin")
            for concern in user_feedback.get("concerns", [])
            if isinstance(concern, dict)
        ]
        emitted = expected_origin in origins
        origin = expected_origin if emitted else None
        if emitted:
            omission_reason = None
        elif len(user_feedback.get("concerns", [])) >= 3:
            omission_reason = "higher-priority base/task concerns filled the concern budget"
        elif not selection["corrective"] and user_feedback.get("decision") == "accept":
            omission_reason = "proactive check not currently actionable"
        elif not user_feedback.get("concerns"):
            omission_reason = "no material concern remained"
        else:
            omission_reason = "simulator found the check unsupported by public evidence"
    record = {
        "red_team_trace_version": getattr(generation, "red_team_trace_version", None) or V3_VERSION,
        "delivery_mode": "user_simulator_private",
        "submission_id": submission_id,
        "solver_turn": int(submission_id[1:]) + 1,
        "generation_sha256": generation.generation_sha256,
        "selection": selection,
        "skipped": skipped,
        "focused_dynamic_check": selection["focused_dynamic_check"] if selection else None,
        "message_component": "",
        "ordinary_prompt_sha256": sha256_text(ordinary_prompt),
        "final_prompt_sha256": sha256_text(ordinary_prompt),
        "emitted": emitted,
        "concern_origin": origin,
        "omission_reason": omission_reason,
    }
    path = root / "trace-defense-reminders" / f"{submission_id}.json"
    if path.is_file():
        existing = read_json_object(path, "v3 private delivery receipt")
        if existing != record:
            raise RuntimeError("persisted v3 private delivery receipt changed")
    elif os_path_exists(path):
        raise RuntimeError("v3 private delivery receipt is not a regular file")
    elif allow_generation:
        write_json_atomic(path, record)
    else:
        raise RuntimeError("v3 private delivery receipt is missing")
    return record


def suppress_proactive_only_revision(
    selection: dict[str, Any] | None,
    user_feedback: dict[str, Any],
) -> dict[str, Any]:
    """Enforce the declared rule that a nonviolated proactive check alone
    cannot create another solver revision.

    The simulator response remains retained verbatim in its generation record;
    this deterministic delivery projection only prevents one proactive-only
    concern from becoming a revise turn.  Base, general and corrective
    concerns keep their original order and compete for the same three slots.
    """
    if not selection or selection.get("corrective"):
        return user_feedback
    if user_feedback.get("decision") != "revise":
        return user_feedback
    concerns = user_feedback.get("concerns")
    if not isinstance(concerns, list) or not concerns:
        return user_feedback
    if all(isinstance(item, dict) and item.get("origin") == "dynamic_proactive" for item in concerns):
        return {"decision": "accept", "concerns": []}
    return user_feedback


def os_path_exists(path: Path) -> bool:
    # Keep symlink detection explicit: delivery receipts are durable evidence.
    import os
    return os.path.lexists(path)
