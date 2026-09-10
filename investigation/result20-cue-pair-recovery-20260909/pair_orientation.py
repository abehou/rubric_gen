import os,json,hashlib
from pathlib import Path
assert os.environ.get("SLURM_JOB_ID")
root=Path("/home/aydanh/repos/rubric_gen")
rows=json.loads((root/"docs/reports/2026-09-09/cue-proposal-rejections-v2.json").read_text())
g=Path(next(r["path"] for r in rows if r["task"]=="da-15-1" and r["generation"]=="generation-0002"))
out={"job_id":os.environ["SLURM_JOB_ID"],"generation":str(g),"files":{}}
for name in ["artifact-history.json","pairwise-assessment-rubric-free.json","pairwise-assessment-active-rubric.json","pairwise-assessment-development-rubric.json"]:
 p=g/name;raw=p.read_bytes();out["files"][name]={"sha256":hashlib.sha256(raw).hexdigest(),"data":json.loads(raw)}
dest=Path("/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/pair-orientation-v1")
dest.mkdir(exist_ok=False);(dest/"evidence.json").write_text(json.dumps(out,indent=2))
h=out["files"]["artifact-history.json"]["data"]
summary={"job_id":out["job_id"],"evidence":str(dest/"evidence.json"),"history_fields":list(h),"assessments":{}}
for name,f in out["files"].items():
 if name!="artifact-history.json":
  summary["assessments"][name]=[a for a in f["data"]["assessments"] if a["pair_id"]=="pair_c94a2cf8125fe4dc"]
summary["pairs"]=[p for p in h.get("pairs",[]) if p.get("pair_id")=="pair_c94a2cf8125fe4dc"]
summary["artifact_fields"]=[list(a) for a in h.get("artifacts",[])][:1]
(root/"docs/reports/2026-09-09/cue-pair-orientation.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
