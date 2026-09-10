"""Read-only acceptance of frozen recovery gates and actual interrupted receipts."""
import importlib.util,json,os,subprocess
from pathlib import Path
from types import SimpleNamespace
from rubric_gen.submission_revision.controller_recovery import RevisionRecovery, _FailedTurnCheckpoint
from rubric_gen.submission_revision.models import RevisionState
root=Path('/home/aydanh/repos/rubric_gen')
bundle=root/'investigation/result20-checkpoint-recovery-20260908'
spec=importlib.util.spec_from_file_location('recovery_dispatcher',bundle/'condition_launch.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.smoke_gate()
configs={mode:m.config_for(mode,'result20').experiment_id for mode in m.OLD_JOBS}
rejected=[]
terminal=[]
for mode in m.OLD_JOBS:
 try:m.old_owner_gate(mode)
 except RuntimeError as exc:
  if 'still present' not in str(exc):raise
  rejected.append(mode)
 else:terminal.append(mode)
study=next((root/'runs/babel-result20-current-20260908/full-trace/study').glob('*/study.json'))
records=json.loads(study.read_text())['records'];records=records.values() if isinstance(records,dict) else records
verified=[]
for rec in records:
 if rec.get('error')!='failed revision state has inconsistent solver identity':continue
 d=study.parent/rec['experiment_dir'];state_bytes=(d/'state.json').read_bytes();manifest_bytes=(d/'manifest.json').read_bytes()
 state=RevisionState.from_json(json.loads(state_bytes));manifest=json.loads(manifest_bytes);events=[]
 turn=d/'turns'/f'turn-{state.next_turn_index:03d}';status=json.loads((turn/'status.json').read_text())
 checkpoint=_FailedTurnCheckpoint(state.next_turn_index,turn,turn/'status.json',turn/'trajectory.stream.jsonl')
 recovery=object.__new__(RevisionRecovery)
 # No stores or providers are initialized. These callbacks only inspect the
 # in-memory recovery decision; original files must remain byte-identical.
 def record(s,model):s.effective_solver_model=model
 recovery.store=SimpleNamespace(record_effective_solver_model=record,append_event=events.append)
 recovery.config=SimpleNamespace(agent=SimpleNamespace(model='gpt-5.6-luna',retries=status['max_retries']))
 recovery._recover_reported_solver_model(state,Path(manifest['live_workspace_dir']),manifest,checkpoint)
 recovery._validate_solver_identity(state,manifest)
 assert state.effective_solver_model=='gpt-5.6-luna' and len(events)==1
 assert (d/'state.json').read_bytes()==state_bytes and (d/'manifest.json').read_bytes()==manifest_bytes
 verified.append(rec['assignment_id'])
assert len(verified)==13,verified
out=root/'runs/babel-result20-current-20260908'/f'checkpoint-validation-{os.environ["SLURM_JOB_ID"]}'
out.mkdir(exist_ok=False)
(out/'result.json').write_text(json.dumps(dict(success=True,configs=configs,active_owners_rejected=rejected,terminal_owners_verified=terminal,actual_receipts_verified=verified,source_commit=subprocess.check_output(['git','-C',str(m.CODE_ROOT),'rev-parse','HEAD'],text=True).strip()),indent=2)+'\n')
print('PASS: four frozen configurations/owner gates and13 actual completed receipts; no scientific files modified')
