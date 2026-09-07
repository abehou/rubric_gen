"""Read-only replay of six sealed selected judgments; never calls a provider."""
import json
from pathlib import Path
from rubric_gen.submission_revision.feedback import project_rubric_feedback, FeedbackPolicy
from rubric_gen.submission_revision.rubric_generation import CompleteRubric, RubricGeneration
from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig, SimulatedUserFeedback, SimulatedUserGeneration
from rubric_gen.submission_revision.user_simulator_history import build_simulated_user_history
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.artifacts import sha256_file

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

def main():
    ledger = json.loads((ROOT / 'investigation/autonomous-dev3-20260907/resumption-20260907/selected-training-preparation/ledger.json').read_text())
    assert {(r['task'], r['replicate']) for r in ledger} == {(t, r) for t in ['da-3-4', 'da-11-1'] for r in [1,2,3]}
    results = []
    benchmark = get_submission_benchmark('biomnibench-da')
    for row in ledger:
        source = ROOT / row['source']
        manifest = json.loads((source / 'manifest.json').read_text())
        rubric = CompleteRubric.from_content(Path(manifest['initial_rubric_path']).read_text())
        generation = RubricGeneration(0, None, rubric, (), 0)
        judgment = source / 'judgments/s000' / rubric.content_sha256
        artifacts = judgment / 'score_validation.json', judgment / 'evaluation.json'
        validation = json.loads(artifacts[0].read_text())
        evaluation = json.loads(artifacts[1].read_text())
        assert validation['evaluation_sha256'] == sha256_file(artifacts[1])
        args = dict(task_instruction=(ROOT / 'data/biomnibench-da' / row['task'] / 'instruction.md').read_text(), first_revision=True,
                    reference_artifacts=artifacts, reference_rubric_text=rubric.content, reference_rubric_sha256=rubric.content_sha256)
        projection = project_rubric_feedback(generation, artifacts, FeedbackPolicy.FULL, **args)
        assert projection.score == validation['score'] == row['selected_score']
        assert projection.payload['rubric_text'] == rubric.content
        for key, criterion in projection.payload['criteria'].items():
            assert criterion['level'] == validation['criterion_levels'][key]
            assert criterion['points'] == validation['criterion_scores'][key]
            assert criterion['judge_reason'] == evaluation['criteria'][key]['reason']
        expected = ROOT / 'investigation/autonomous-dev3-20260907/resumption-20260907/selected-training-preparation' / row['task'] / f"rep-{row['replicate']:03d}" / 'selected-feedback.json'
        assert projection.payload == json.loads(expected.read_text())
        # Bind the actual simulator request and persisted replay validation to that payload.
        captured = []
        def fake_provider(config, request):
            captured.append(request)
            start = request.evidence.index('<full_evaluator_feedback>') + len('<full_evaluator_feedback>')
            end = request.evidence.index('</full_evaluator_feedback>')
            assert json.loads(request.evidence[start:end]) == projection.payload
            return SimulatedUserGeneration(text='{"decision":"accept","concerns":[]}', provider='openai', requested_model=config.model,
                                           effective_model=config.model, response_id='offline-replay', request_parameters={"max_output_tokens": config.max_output_tokens}, provider_metadata={})
        simulator = SimulatedUserFeedback(SimulatedUserConfig(model='gpt-5.6-luna'), generator=fake_provider)
        history = build_simulated_user_history(source, benchmark, 0)
        params = dict(experiment_id='selected-reference-binding-check', assignment_id=manifest['assignment_id'], submission_id='s000', generation_round=0,
                      generation=generation, full_feedback=projection.payload,
                      current_artifact=benchmark.render_user_review(source / 'submissions/s000/workspace'), history=history, history_summary=None)
        record = simulator.generate(**params, instruction=args['task_instruction'], failure_dir=OUT / 'unexpected-failures')
        assert simulator.validate(record, **params) == {'decision':'accept','concerns':[]}
        mismatch = dict(params, full_feedback=json.loads((source / 'feedback/s000.json').read_text()))
        try: simulator.validate(record, **mismatch)
        except ValueError: pass
        else: raise AssertionError('Mixed-reference simulator replay accepted')
        master = Path(manifest['task_dir']) / 'tests' / manifest['master_rubric_name']
        try:
            project_rubric_feedback(generation, artifacts, FeedbackPolicy.FULL,
                                   **dict(args, reference_rubric_text=master.read_text(), reference_rubric_sha256=sha256_file(master)))
        except ValueError: pass
        else: raise AssertionError('Mismatched base reference accepted')
        results.append(dict(task=row['task'], replicate=row['replicate'], selected_score=projection.score, historical_master_score=row['master_score'],
                            criteria_checked=len(projection.payload['criteria']), simulator_requests_checked=len(captured), mismatch_rejected=True))
    (OUT / 'saved-binding-results.json').write_text(json.dumps({'provider_calls':0,'cases':results},indent=2)+'\n')
    print(json.dumps(results,indent=2))

if __name__ == '__main__': main()
