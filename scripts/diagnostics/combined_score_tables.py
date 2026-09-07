"""Private union of two independently validated, disjoint Results20 cohorts."""
from pathlib import Path
import json
import sys

from model_score_tables import rows, render, CONDITIONS, MODELS
from check_audit_coverage import source_records

APPROVED_CONDITIONS = tuple(
    f'{feedback}-{policy}'
    for feedback in ('full', 'user-simulator')
    for policy in ('static', 'offline-rubric', 'red-team-artifact', 'red-team-trace')
)


def combine(old_study, old_audit, new_study, new_audit, *, expected_conditions=APPROVED_CONDITIONS,
            expected_models=MODELS):
    assert expected_conditions and set(expected_conditions) <= set(CONDITIONS)
    def blocks(study):
        records = source_records(study)
        return {(r['task_id'], r['replicate'], r['solver_id'], r['condition_id'])
                for r in records}
    old, new = blocks(old_study), blocks(new_study)
    assert not old & new, 'duplicate assignment across cohorts'
    all_blocks = old | new
    tasks = {r[0] for r in all_blocks}
    assert len(tasks) == 20
    expected = {(task, replicate, 'luna', condition)
                for task in tasks for replicate in (1, 2, 3) for condition in expected_conditions}
    assert all_blocks == expected, 'missing or unexpected Results20 assignments'
    previous = {key: value for key, value in rows(old_study, old_audit).items()
                if key[0] in expected_models}
    current = rows(new_study, new_audit, expected_models=expected_models)
    assert not previous.keys() & current.keys(), 'conditions overlap across cohorts'
    result = previous | current
    assert set(result) == {(m, c) for m in expected_models for c in expected_conditions}
    return render(result)


if __name__ == '__main__':
    if len(sys.argv) != 5:
        raise SystemExit('Supply original study/audit and remaining study/audit paths')
    print(combine(*(Path(p).resolve() for p in sys.argv[1:])))
