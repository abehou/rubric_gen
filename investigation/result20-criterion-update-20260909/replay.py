"""No-provider replay of complete feedback projection on a sealed checkpoint."""
import os,json,hashlib
from pathlib import Path
from rubric_gen.submission_revision.feedback import project_rubric_simulated_user_feedback
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
ROOT=Path('/home/aydanh/repos/rubric_gen')
def main():
    assert os.environ.get('SLURM_JOB_ID')
    r=ROOT/'runs/babel-result20-cue-score-first-trace-20260909/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-13-1/rep-002/luna/user-simulator-red-team-trace'
    g=load_rubric_generation(r,3);m=json.loads((r/'manifest.json').read_text())
    score=json.loads((r/'rubric-evaluations/s003.json').read_text());feedback=json.loads((r/'feedback/s003.json').read_text())
    validation=r/'judgments/s003'/g.rubric.content_sha256/'score_validation.json'
    old=(r/'turns/turn-004/prompt.txt').read_text()
    result=project_rubric_simulated_user_feedback(g,validation,feedback,task_instruction=(Path(m['task_dir'])/'instruction.md').read_text(),first_revision=False,reference_score=score['reference_score'])
    assert result.score==score['score']
    assert result.payload==feedback
    assert result.prompt.startswith(old)
    delta=result.prompt[len(old):]
    assert delta.count('## Rubric update')==1
    assert g.elicited_criteria[0].requirement in delta
    assert 'does not itself assert' in delta
    out=ROOT/'runs'/f'criterion-update-replay-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
    (out/'prompt.txt').write_text(result.prompt)
    (out/'result.json').write_text(json.dumps(dict(success=True,score_unchanged=True,payload_unchanged=True,original_prompt_prefix_unchanged=True,added_text=delta,original_prompt_sha256=hashlib.sha256(old.encode()).hexdigest(),generation_sha256=g.generation_sha256,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2))
if __name__=='__main__':main()
