"""Two live checkpoint smokes; preserve the original 5/10 stopping configuration."""
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.models import SubmissionRevisionConfig
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.paraphrase_validation import resolve_paraphrase_selection
from rubric_gen.submission_revision.controller import SubmissionRevisionController
from rubric_gen.submission_revision.judgment_reuse import exact_judgment_request, load_judgment_copy
from rubric_gen.submission_revision.artifacts import sha256_file

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/selected-reference-wiring-smoke-20260907-attempt02'
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / 'runs/autonomous-dev3-20260907/isolation-cachefix-smoke/study/biomnibench-da-factorial-r3-3686c8965c2e/experiments/da-3-4/rep-001/luna/full-static'

class CheckpointReached(Exception):
    pass


def run(mode):
    experiment = load_experiment(ROOT / 'experiments/biomnibench-dev-exposure-da-3-4.yaml')
    seed = ROOT / 'runs/autonomous-dev3-20260907/isolation-readers-smoke/seeds'
    paraphrases = ROOT / 'runs/autonomous-dev3-20260907/isolation-readers-smoke/paraphrases'
    assignment = next(a for a in experiment.assignments if a.replicate == 1 and a.condition_id == mode)
    selection = resolve_paraphrase_selection(paraphrases, experiment, 'da-3-4')
    manifest = json.loads((SOURCE / 'manifest.json').read_text())
    policy = FeedbackPolicy(experiment.condition(mode)['feedback_policy'])
    destination = OUT / ('full-static-live04' if mode == 'full-static' else mode)
    config = SubmissionRevisionConfig(
        task_dir=experiment.task_dir('da-3-4'), experiment_dir=destination,
        max_revisions=10, min_revisions=5, seed_run_dir=seed,
        pretreatment_rubric_dir=Path(manifest['pretreatment_rubric_dir']),
        agent=experiment.solver_config('luna', quiet=True),
        seed_agent=experiment.seed_agent_config(quiet=True), red_team_agent=experiment.red_team_agent_config(quiet=True),
        solver_id='luna', experiment_id='selected-reference-wiring-smoke-20260907',
        assignment_id=assignment.assignment_id, condition_id=mode, replicate=1,
        elicitation_seed_replicates=3, execution_order=assignment.execution_order,
        optimizer_rubric_path=selection.optimizer_path, development_rubric_path=selection.development_path,
        master_rubric_name='rubric.txt', feedback_policy=policy,
        feedback_simulator=experiment.feedback_simulator_config(policy),
        judge_model='gpt-5.6-luna', show_progress=False, resume=destination.exists(),
    )
    controller = SubmissionRevisionController(config, judgment_reuse_root=OUT / 'reuse')
    calls = {'new_judgments':0, 'reused_judgments':0}
    # Route exact compatible historical judgments into the new cache without changing them.
    for judge in [controller.dependencies.judge, controller.scoring.master_judge]:
        original = judge.evaluate
        def evaluate(submission_dir, attempt_id, judge=judge, original=original):
            review, answer = judge.review_inputs(submission_dir)
            identity = judge.scoring_identity()
            request = exact_judgment_request(task_id='da-3-4', replicate=1,
                rubric_sha256=identity['rendered_rubric_sha256'], review_text=review, answer_text=answer,
                scoring_identity=identity)
            try:
                saved = load_judgment_copy(experiment_dir=SOURCE, submission_id=submission_dir.name,
                    rubric_sha256=identity['rendered_rubric_sha256'], expected_request=request)
            except RuntimeError:
                calls['new_judgments'] += 1
                print(mode, 'new judgment', submission_dir.name, flush=True)
                return original(submission_dir, attempt_id)
            calls['reused_judgments'] += 1
            print(mode, 'exact reused judgment', submission_dir.name, flush=True)
            return saved
        judge.evaluate = evaluate
    checkpoint = controller.scoring.run_judge_checkpoint
    def bounded(state):
        checkpoint(state)
        if len(state.scores) == 2:
            raise CheckpointReached()
    controller.scoring.run_judge_checkpoint = bounded
    print(datetime.now().astimezone().isoformat(), 'START', mode, flush=True)
    try:
        controller.run()
    except CheckpointReached:
        pass
    else:
        raise AssertionError('Smoke did not reach its bounded checkpoint')
    # Load through production recovery, with generation disabled by the resume validator.
    resumed = SubmissionRevisionController(replace(config, resume=True), judgment_reuse_root=OUT / 'reuse')
    try:
        state, live_root, workspace = resumed.recovery.load_resume()
        resumed.scoring.validate_latest_checkpoint(state)
        assert state.phase.value == 'ready_for_turn' and len(state.scores) == 2
        assert state.next_prompt
        for sid in ['s000','s001']:
            record = json.loads((config.experiment_dir / 'rubric-evaluations' / f'{sid}.json').read_text())
            assert record['feedback_reference']['rubric_sha256'] == sha256_file(config.optimizer_rubric_path)
            assert record['score'] == record['reference_score']
        result = dict(mode=mode, status='checkpoint-smoke-passed', configured_min_revisions=5,
                      configured_max_revisions=10, solver_turns=1, checkpoints=2,
                      scores=state.scores, master_scores=state.fixed_original_scores,
                      resume_validated=True, live_workspace=str(workspace), calls=calls,
                      remaining_study_turns='intentionally not dispatched; this is a checkpoint acceptance test')
        (config.experiment_dir / 'smoke-result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('PASS', json.dumps(result), flush=True)
        return result
    finally:
        resumed.dependencies.session.close()


def main():
    from dotenv import dotenv_values
    key = dotenv_values(ROOT / '.env.local').get('OPENAI_API_KEY')
    if key:
        os.environ['OPENAI_API_KEY'] = key
    assert os.environ.get('OPENAI_API_KEY'), 'Existing OpenAI credential unavailable'
    OUT.mkdir(exist_ok=True)
    source_hashes = {str(p.relative_to(ROOT)):sha256_file(p) for p in (ROOT/'src').rglob('*.py')}
    (HERE/'smoke-launch-04.json').write_text(json.dumps(dict(started_at=datetime.now().astimezone().isoformat(), pid=os.getpid(),
        concurrency=2, output=str(OUT), source_hashes=source_hashes,
        command='PYTHONPATH=/Users/yuenanhuang/Desktop/rubric_gen/src .venv/bin/python investigation/selected-reference-wiring-20260907/smoke.py'),indent=2)+'\n')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [(mode, pool.submit(run, mode)) for mode in ['full-static','user-simulator-static']]
        results = []
        for mode, future in futures:
            try: results.append(future.result())
            except Exception as exc:
                import traceback
                traceback.print_exc()
                results.append(dict(mode=mode, status='failed', error_type=type(exc).__name__, error=str(exc)))
    assert all(sha256_file(ROOT/p)==h for p,h in source_hashes.items())
    (HERE/'smoke-results.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__ == '__main__': main()
