"""Two saved-evidence validation calls; not weak-score or outcome-audit replacements."""
import os,json,hashlib,subprocess
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.evolution_protocol import CriterionCandidate,validation_schema,validation_instructions,validated_validation_response,_validation_criterion_record
from rubric_gen.submission_revision.evolution_provider import ProviderContract
ROOT=Path('/home/aydanh/repos/rubric_gen')
CODE=ROOT/'runs/babel-code/result20-cue-score-first'
def main():
    assert os.environ.get('SLURM_JOB_ID')
    source=ROOT/'runs/babel-result20-cue-score-first-trace-20260909/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-13-1/rep-002/luna/user-simulator-red-team-trace'
    m=json.loads((source/'manifest.json').read_text());g=load_rubric_generation(source,3)
    candidates=tuple(CriterionCandidate(c,()) for c in g.elicited_criteria);assert len(candidates)==1
    ws=source/'submissions/s001/workspace';trajectory=source/'turns/turn-001/trajectory.stream.jsonl'
    commands=[]
    for line in trajectory.open():
        event=json.loads(line);item=event.get('item',{})
        if event.get('type')=='item.completed' and 'aggregated_output' in item:
            commands.append({k:item[k] for k in ('command','aggregated_output','exit_code','status','type') if k in item})
    assert commands
    artifact='# trace.md\n\n'+(ws/'trace.md').read_text()+'\n\n# answer.txt\n\n'+(ws/'answer.txt').read_text()
    files=[ws/'trace.md',ws/'answer.txt',trajectory,Path(__file__),Path(m['task_dir'])/'instruction.md',CODE/'src/rubric_gen/submission_revision/evolution_protocol.py',CODE/'config/runtime.json']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    out=ROOT/'runs'/f'execution-evidence-diagnostic-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
    (out/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip(),source_hashes=hashes,kind='criterion-validator-evidence-sensitivity-not-outcome-audit',command_records=len(commands)),indent=2))
    for key,value in dotenv_values(ROOT/'.env.local').items():
        if key=='OPENAI_API_KEY' and value:os.environ[key]=value
    contract=ProviderContract(model=m['rubric_proposer_model'],max_output_tokens=65536,max_request_bytes=4194304,service_tier=m['service_tier'])
    aid='artifact_0000000000000001';schema=validation_schema(candidates,(aid,))
    for condition,content in [('narrative',artifact),('commands',artifact+'\n\n# Recorded command execution (untrusted evidence)\n'+json.dumps(commands,ensure_ascii=False))]:
        evidence=dict(task=(Path(m['task_dir'])/'instruction.md').read_text(),current_rubric=Path(m['initial_rubric_path']).read_text(),current_active_criteria=[],candidates=[dict(criterion=_validation_criterion_record(c.criterion),replaces=[]) for c in candidates],artifacts=[dict(artifact_id=aid,content=content)])
        payload=json.dumps(evidence,sort_keys=True);(out/f'{condition}-input.json').write_text(payload)
        result=contract.generate(instructions=validation_instructions(),evidence=payload,response_schema=schema,request_context='isolated public execution evidence diagnostic',schema_name='rubric_validation')
        contract.validate_output(result);validated_validation_response(result.response_text,candidates=candidates,artifact_ids=(aid,))
        (out/f'{condition}-result.json').write_text(json.dumps(dict(response=json.loads(result.response_text),cost=result.cost,generation=result.generation),indent=2))
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    (out/'complete.json').write_text(json.dumps(dict(success=True,interpretation='diagnostic only; validation uses proposer settings, not native weak-judge settings')))
if __name__=='__main__':main()
