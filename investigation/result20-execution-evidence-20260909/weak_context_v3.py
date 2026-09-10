"""Matched native weak-judge context diagnostic; no replacement study scores."""
import os,json,hashlib,uuid
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.submission_revision.judge import FrozenRubricJudge,FrozenRubric,SubmissionJudgeConfig
from rubric_gen.submission_revision.judging.models import RUBRIC_PATH_SOURCE
from rubric_gen.submission_revision.rubric_generation import CompleteRubric
from rubric_gen.submission_revision.artifacts import tree_sha256
ROOT=Path('/home/aydanh/repos/rubric_gen')
def main():
    assert os.environ.get('SLURM_JOB_ID')
    source=ROOT/'runs/babel-result20-cue-score-first-trace-20260909/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-13-1/rep-002/luna/user-simulator-red-team-trace'
    m=json.loads((source/'manifest.json').read_text())
    out=ROOT/'runs'/f'weak-context-diagnostic-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
    full=(source/'rubric-generations/generation-0003/rubric.txt').read_text()
    criterion=full.split('Criterion 7: ',1)[1]
    isolated='RUBRIC: Internal consistency of reported quantitative results\n\nScore normalization maximum: 100\n\nCriterion 1: '+criterion
    rubrics={'full':full,'isolated':isolated}
    CompleteRubric.from_content(full)
    # A penalty-only diagnostic is not a complete study rubric. Use the native
    # scoring parser, and verify every level/point/description against the full one.
    from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
    parsed_full=parse_autorubric_rubric(full)
    parsed_isolated=parse_autorubric_rubric(isolated)
    assert len(parsed_isolated.criteria)==1
    assert parsed_isolated.criteria[0].levels==parsed_full.criteria[-1].levels
    assert parsed_isolated.criteria[0].title==parsed_full.criteria[-1].title
    hashes={s:tree_sha256(source/'submissions'/s/'workspace') for s in ('s001','s003')}
    (out/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],kind='native-weak-context-diagnostic-not-replacement',source=str(source),workspace_hashes=hashes,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),model=m['judge_model']),indent=2))
    for key,value in dotenv_values(ROOT/'.env.local').items():
        if key=='OPENAI_API_KEY' and value:os.environ[key]=value
    results=[]
    for s in ('s001','s003'):
        for condition,text in rubrics.items():
            rubric_path=out/f'{condition}.txt';rubric_path.write_text(text)
            rubric=FrozenRubric(text,hashlib.sha256(text.encode()).hexdigest(),RUBRIC_PATH_SOURCE,None,None,None,None)
            config=SubmissionJudgeConfig(task_dir=Path(m['task_dir']),experiment_dir=out/s/condition,review=m['review'],judge_model=m['judge_model'],rubric_name=None,rubric_set=None,rubric_path=rubric_path,max_review_chars=m['max_review_chars'])
            judge=FrozenRubricJudge(config,rubric)
            if s=='s001' and condition=='full':
                previous=ROOT/'runs/weak-context-diagnostic-10369754'
                old_config=SubmissionJudgeConfig(task_dir=Path(m['task_dir']),experiment_dir=previous/s/condition,review=m['review'],judge_model=m['judge_model'],rubric_name=None,rubric_set=None,rubric_path=previous/'full.txt',max_review_chars=m['max_review_chars'])
                old_judge=FrozenRubricJudge(old_config,rubric)
                artifacts=old_judge.validate(source/'submissions'/s,'97e2325beb5246a2ac522af5a9f08ea9')
            else:
                artifacts=judge.evaluate(source/'submissions'/s,uuid.uuid4().hex)
            evaluation=json.loads(artifacts.evaluation_path.read_text())
            results.append(dict(checkpoint=s,condition=condition,evaluation_path=str(artifacts.evaluation_path),identity=judge.scoring_identity(),raw_report=evaluation.get('raw_report',dict(criteria=evaluation['criteria'],overall_reasoning=evaluation['reasoning']))))
            (out/'results.json').write_text(json.dumps(results,indent=2))
    assert all(tree_sha256(source/'submissions'/s/'workspace')==h for s,h in hashes.items())
    (out/'complete.json').write_text(json.dumps(dict(success=True,judgments=len(results))))
if __name__=='__main__':main()
