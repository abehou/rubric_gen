"""Import exact current-format semantic judgments; retain raw artifacts unchanged."""
import json
import shutil
import threading
from pathlib import Path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation import rubric_score, score_execution, jobs

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
 ROOT/'runs/autonomous-dev3-20260907/isolation-cachefix-smoke/audit/biomnibench-da-factorial-r3-3686c8965c2e',
 ROOT/'runs/autonomous-dev3-20260907/baseline-da11/audit/biomnibench-da-factorial-r3-ac929d893d67',
]
_lock = threading.Lock()
_rubric = rubric_score.RubricScoreStage._run_job
_quality = score_execution.RubricFreeScoreStage._run_structured_judgment

def _log(root, source, key):
 with (root/'imported-requests.jsonl').open('a') as f:
  f.write(json.dumps({'source':str(source),'key':key})+'\n')
 print('SEMANTIC REUSED',key,flush=True)

def rubric(self, job):
 destination = self.output.path('records',job.key+'.json')
 with _lock:
  if not destination.exists():
   identity = jobs._rubric_score_judgment_identity(job)
   for base in SOURCES:
    source = base/'rubric_score/records'/destination.name
    if not source.exists():continue
    record=json.loads(source.read_text())
    if any(record.get(k)!=v for k,v in identity.items()):
     raise RuntimeError('Exact rubric cache identity mismatch')
    source_raw=Path(record['validation_path']).parent
    source_raw.resolve().relative_to((base/'rubric_score/artifacts').resolve())
    judge=self._judge_for_job(job)
    target_raw=judge._evaluation_root(job.submission,rubric_score._rubric_score_attempt_id(job))
    if target_raw.exists():raise RuntimeError('Interrupted rubric import requires inspection')
    if source_raw.is_symlink() or any(p.is_symlink() for p in source_raw.rglob('*')):
     raise RuntimeError('Rubric cache contains a symlink')
    target_raw.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source_raw,target_raw)
    artifacts=judge.validate(job.submission,rubric_score._rubric_score_attempt_id(job))
    # Only local artifact references change. Raw responses, scores, identities and hashes stay exact.
    record['validation_path']=str(artifacts.score_validation_path)
    record['evaluation_path']=str(artifacts.evaluation_path)
    rubric_score._validate_rubric_score_record(job=job,record=record,artifacts=artifacts,validation=json.loads(artifacts.score_validation_path.read_text()))
    self.output.ensure_directory('records')
    write_json_atomic(destination,record)
    _log(self.output.root,source,job.key)
    break
 return _rubric(self,job)

def quality(self, **kwargs):
 output=self._output_for(kwargs['instrument'])
 destination=output.path('records',kwargs['key']+'.json')
 with _lock:
  if not destination.exists():
   stage='absolute_score' if kwargs['instrument']=='absolute' else 'pairwise_preference'
   for base in SOURCES:
    source=base/stage/'records'/destination.name
    if not source.exists():continue
    record=json.loads(source.read_text())
    score_execution._validate_record(record=record,identity=kwargs['identity'],validator=kwargs['validator'],model=kwargs['model'],max_attempts=score_execution.JUDGE_MAX_ATTEMPTS)
    output.ensure_directory('records')
    shutil.copyfile(source,destination)
    _log(output.root,source,kwargs['key'])
    break
 return _quality(self,**kwargs)

def install():
 rubric_score.RubricScoreStage._run_job=rubric
 score_execution.RubricFreeScoreStage._run_structured_judgment=quality
