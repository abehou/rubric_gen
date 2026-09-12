"""Reconstruct 12 preselected saved public checkpoints without model calls."""
import json
from pathlib import Path
from dataclasses import asdict
from rubric_gen.artifacts.hashing import sha256_text,sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.feedback import project_rubric_feedback,FeedbackPolicy
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback,SimulatedUserConfig,_history_text
from rubric_gen.submission_revision.user_simulator_history import build_simulated_user_history
from rubric_gen.submission_revision.evolution_serialization import canonical_json
from rubric_gen.submission_revision import user_feedback_factors as factors
BUNDLE=Path(__file__).resolve().parent;ROOT=BUNDLE.parents[1]
OUT=Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-parallel-diagnostics-20260912/feedback-checks')
OLD=ROOT/'docs/reports/2026-09-11/trace-attack-defense-v3'
files={'v3':'stress-user-forensics.json','v3.1':'stress-v31-user-forensics.json','v3.2':'stress-v32-user-forensics.json'}
cohorts={v:json.loads((OLD/p).read_text())['cases'] for v,p in files.items()}
benchmark=get_submission_benchmark('biomnibench-da');rows=[]
for item in json.loads((BUNDLE/'feedback_checkpoints.json').read_text()):
 case=next(c for c in cohorts[item['variant']] if c['task_id']==item['task'] and int(c['replicate'])==item['replicate'])
 root=Path(case['v3']['case']['root']);sid=item['submission_id'];manifest=json.loads((root/'manifest.json').read_text())
 fg=json.loads((root/'feedback-generations'/f'{sid}.json').read_text());scoring=json.loads((root/'rubric-evaluations'/f'{sid}.json').read_text())
 gen=load_rubric_generation(root,fg['generation_round'])
 active=root/'judgments'/sid/gen.rubric.content_sha256
 refhash=scoring['feedback_reference']['rubric_sha256'];reference=root/'judgments'/sid/refhash
 instruction=(Path(manifest['task_dir'])/'instruction.md').read_text();public=benchmark.render_user_review(root/'submissions'/sid/'workspace')
 assert sha256_text(public)==fg['current_artifact_sha256']
 full=project_rubric_feedback(gen,(active/'score_validation.json',active/'evaluation.json'),FeedbackPolicy.FULL,
     task_instruction=instruction,first_revision=sid=='s000',
     reference_artifacts=(reference/'score_validation.json',reference/'evaluation.json'),
     reference_rubric_text=Path(manifest['initial_rubric_path']).read_text(),reference_rubric_sha256=manifest['initial_rubric_sha256'],
     prompt_profile=manifest['prompt'],benchmark=manifest['benchmark'])
 full_text=canonical_json(full.payload);assert sha256_text(full_text)==fg['full_feedback_sha256']
 history=build_simulated_user_history(root,benchmark,int(sid[1:]));assert sha256_text(_history_text(history))==fg['history_sha256']
 config=SimulatedUserConfig(**{k:v for k,v in fg['simulator'].items() if not k.endswith('implementation_sha256')})
 sim=SimulatedUserFeedback(config)
 # These preselected checkpoints use saved verbatim history; no new summary call.
 if sim.history_requires_summary(history):raise RuntimeError('preselected checkpoint requires saved summary reconstruction: '+str(root/sid))
 context,mode=sim._history_context(experiment_id=fg['experiment_id'],assignment_id=fg['assignment_id'],submission_id=sid,history=history,history_summary=None)
 assert sha256_text(context)==fg['history_context']['sha256'] and mode==fg['history_context']['mode']
 selection,skipped=factors.select_reminder(generation=gen,score_validation_path=active/'score_validation.json',root=root,submission_id=sid,instruction=instruction)
 inputs={**item,'root':str(root),'feedback_generation_path':str(root/'feedback-generations'/f'{sid}.json'),
    'instruction':instruction,'current_artifact':public,'full_feedback':full.payload,'history':history,
    'selection':selection,'skipped':skipped,'focused_dynamic_check':factors.focused_check(selection,gen),
    'config':{k:v for k,v in fg['simulator'].items() if not k.endswith('implementation_sha256')},
    'generation_round':fg['generation_round'],'original_output':fg['output'],'history_context':context,
    'original_source_binding_verified':True}
 write_json_atomic(OUT/'inputs'/f'{item["case"]}.json',inputs)
 rows.append({k:inputs[k] for k in ('case','variant','task','replicate','submission_id','root','feedback_generation_path','selection','skipped','original_source_binding_verified')})
write_json_atomic(BUNDLE/'feedback-inputs.json',{'provider_calls':0,'logical_checkpoints':len(rows),'root':str(OUT),'rows':rows})
print(json.dumps({'prepared':len(rows),'provider_calls':0}))
