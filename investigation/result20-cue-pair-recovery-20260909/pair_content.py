import os,json,hashlib,difflib
from pathlib import Path
assert os.environ.get("SLURM_JOB_ID")
base=Path("/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/pair-orientation-v1")
x=json.loads((base/"evidence.json").read_text());h=x["files"]["artifact-history.json"]["data"]
pair=next(p for p in h["pairs"] if p["pair_id"]=="pair_c94a2cf8125fe4dc")
ids=pair["artifact_ids"]
if int(hashlib.sha256(("assessment-order\0"+pair["pair_id"]).encode()).hexdigest(),16)%2:ids=ids[::-1]
a={a["artifact_id"]:a for a in h["artifacts"]}
result={"job_id":os.environ["SLURM_JOB_ID"],"A":ids[0],"B":ids[1],"artifacts":[]}
for i in ids:
 c=a[i]["content"]; result["artifacts"].append({"id":i,"sha256":hashlib.sha256(c.encode()).hexdigest(),"saved_sha256":a[i]["content_sha256"],"count_mentions":[{"line":n,"text":s[:1200]} for n,s in enumerate(c.splitlines(),1) if any(t in s for t in ["6,436","6,437","6436","6437","3,490","3,491"])]})
result["diff"]=list(difflib.unified_diff(a[ids[0]]["content"].splitlines(),a[ids[1]]["content"].splitlines(),fromfile="A",tofile="B",n=2))
(base/"content-check.json").write_text(json.dumps(result,indent=2))
Path("/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-pair-content.json").write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
