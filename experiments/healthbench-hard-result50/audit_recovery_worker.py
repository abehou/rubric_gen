"""Apply native input-bound output allowances to the four truncated judgments."""
import json
import os
from pathlib import Path
import sys

from rubric_gen.runtime.process_environment import install_controlled_process_environment


def install_allowances(path):
    from rubric_gen.submission_revision.evaluation import rubric_judge
    allowances = json.loads(Path(path).read_text())
    fields = ('rubric_sha256', 'review_input_sha256', 'answer_input_sha256')
    original = rubric_judge.output_recovery_limit
    native_env = 'RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY'
    if os.environ.get(native_env):
        raise ValueError('Unexpected additional output allowance')
    limits = {}
    try:
        for allowance in allowances:
            os.environ[native_env] = json.dumps(allowance)
            limit = original(allowance)
            assert limit == 8192
            limits[tuple(allowance[f] for f in fields)] = limit
    finally:
        os.environ.pop(native_env, None)

    # Pure lookup after startup: no process-global environment changes in workers.
    def scoped_limit(binding):
        return limits.get(tuple(binding.get(f) for f in fields))

    rubric_judge.output_recovery_limit = scoped_limit
    return scoped_limit


if __name__ == '__main__':
    install_controlled_process_environment()
    install_allowances(sys.argv[1])
    from rubric_gen.cli import main
    raise SystemExit(main(sys.argv[2:]))
