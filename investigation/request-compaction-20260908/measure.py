"""Read-only pair-payload byte measurement; no model calls or outcome selection."""
import hashlib,json,os
from pathlib import Path
from rubric_gen.submission_revision.evolution_artifacts import ArtifactPair
from rubric_gen.submission_revision.evolution_assessment import assessment_artifact_ids,pair_text_difference
from rubric_gen.submission_revision.evolution_serialization import canonical_json
root=Path('runs/babel-result20-capacity-v3-20260908/user-trace/study')
rows=[]
for folder in sorted(root.glob('*/experiments/*/rep-*/luna/*/rubric-generations')):
    paths=sorted(folder.glob('generation-*/artifact-history.json'))
    if not paths:continue
    p=paths[-1];raw=p.read_bytes();v=json.loads(raw)
    artifacts={a['artifact_id']:{k:a[k] for k in ['artifact_id','content']} for a in v['artifacts']}
    pairs=[];compact=[];used=set()
    for rec in v['pairs']:
        pair=ArtifactPair(rec['pair_id'],tuple(rec['artifact_ids']))
        a,b=assessment_artifact_ids(pair);used.update([a,b])
        diff=pair_text_difference(artifacts[a]['content'],artifacts[b]['content'])
        pairs.append(dict(pair_id=pair.pair_id,artifact_A=artifacts[a],artifact_B=artifacts[b],visible_difference=diff))
        compact.append(dict(pair_id=pair.pair_id,artifact_A={'artifact_id':a},artifact_B={'artifact_id':b},visible_difference=diff))
    table=[artifacts[a] for a in sorted(used)]
    expanded=[{**r,'artifact_A':artifacts[r['artifact_A']['artifact_id']],'artifact_B':artifacts[r['artifact_B']['artifact_id']]} for r in compact]
    assert expanded==pairs
    old=len(canonical_json({'pairs':pairs}).encode());new=len(canonical_json({'pairs':compact,'artifacts':table}).encode())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==hashlib.sha256(raw).hexdigest()
    rows.append(dict(path=str(p),sha256=hashlib.sha256(raw).hexdigest(),pairs=len(pairs),unique_artifacts=len(used),old_bytes=old,new_bytes=new,saved_bytes=old-new))
output=Path(f'runs/request-compaction-measure-{os.environ["SLURM_JOB_ID"]}');output.mkdir(exist_ok=False)
a=sum(r['old_bytes'] for r in rows);b=sum(r['new_bytes'] for r in rows)
result=dict(scope='Latest sealed generation per assignment; pair/artifact payload only, excludes unchanged task/rubric/schema. Byte savings are not measured provider latency.',assignments=len(rows),old_bytes=a,new_bytes=b,reduction_fraction=1-b/a,rows=rows,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
