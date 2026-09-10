from pathlib import Path
import json,hashlib,os
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_artifacts import ArtifactHistory,BlindedArtifact,ArtifactPair
from rubric_gen.submission_revision.rubric_generation import RubricPolicy,CompleteRubric
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import resolve_paraphrase_selection
from rubric_gen.benchmarks import SubmissionBenchmarkId
ROOT=Path('/home/aydanh/repos/rubric_gen')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def forbidden(**kwargs):raise AssertionError('provider call forbidden')
assert os.environ.get('SLURM_JOB_ID')
exp=load_experiment(ROOT/'investigation/result20-cue-contrast-20260908/trace-results20.yaml')
pool=ROOT/'runs/babel-result20-cue-contrast-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/pretreatment-rubrics'
paths=sorted(pool.rglob('pretreatment.json'));assert len(paths)==20
rows=[]
for p in paths:
 meta=read(p);root=p.parent;record=root/'rubric-generations/generation-0001/evolution.json';hist=read(root/'rubric-generations/generation-0001/artifact-history.json');assert not hist['red_team_evidence']
 history=ArtifactHistory(tuple(BlindedArtifact(**a) for a in hist['artifacts']),tuple(ArtifactPair(q['pair_id'],tuple(q['artifact_ids'])) for q in hist['pairs']),())
 selection=resolve_paraphrase_selection(Path(exp.dag['paraphrase']['output_dir']),exp,meta['task_id'])
 dev=CompleteRubric.from_content(selection.development_path.read_text());initial=load_rubric_generation(root,0,expected_policy=RubricPolicy.OFFLINE_ELICITATION)
 assert initial.rubric.content_sha256==sha(selection.optimizer_path)==meta['initial_rubric_sha256']
 assert dev.content_sha256==meta['development_rubric_sha256']
 instruction=exp.task_dir(meta['task_id'])/'instruction.md';assert sha(instruction)==meta['instruction_sha256']
 before={str(f):sha(f) for f in root.rglob('*') if f.is_file()}
 proposer=RubricProposer(benchmark=SubmissionBenchmarkId(meta['benchmark']),model=meta['proposer']['model'],max_retries=meta['max_retries'],service_tier=meta['proposer']['service_tier'],run_proposer=forbidden)
 assert proposer.proposer_contract.record()==meta['proposer']
 result=proposer.validate_frozen_pretreatment_input(instruction=instruction.read_text(),original_rubric=initial.rubric,development_rubric=dev,current_generation=initial,artifact_history=history,output_dir=root,source_evolution_sha256=sha(record))
 assert result.generation_sha256==meta['generation_sha256'];assert before=={str(f):sha(f) for f in root.rglob('*') if f.is_file()}
 rows.append(dict(task=meta['task_id'],generation_sha256=result.generation_sha256,source_hashes=before))
out=ROOT/f'runs/cue-frozen-input-validation-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False);(out/'result.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],tasks=len(rows),rows=rows),indent=2)+'\n');print('validated',len(rows),'frozen inputs; no providers; no mutations')
