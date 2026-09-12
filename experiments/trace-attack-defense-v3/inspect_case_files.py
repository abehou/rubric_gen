import json, os
from pathlib import Path

RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/study/biomnibench-da-factorial-r10-5115fffdd1c0/experiments')
TASKS=('da-15-1','da-13-6','da-18-5','da-19-1','da-15-2','da-12-4','da-14-8','da-14-1','da-12-2','da-15-7','da-19-6')
def shape(path):
    try:
        value=json.loads(path.read_text())
    except Exception as exc: return {'path':str(path),'error':type(exc).__name__}
    if isinstance(value,dict): return {'path':str(path),'keys':sorted(value),'sample':{k:value[k] for k in sorted(value) if k in {'status','feedback','concerns','messages','criterion_id','submission_id','active_generation_round','source_checkpoint','solver_turn','category','corrective','selected','rejection_reason','reason'}}}
    return {'path':str(path),'type':type(value).__name__}
def main():
    out=[]
    for task in TASKS:
        for rep in range(1,4):
            root=RUN/task/f'rep-{rep:03d}'/'luna'/'user-simulator-red-team-trace'
            files=[]
            if root.is_dir():
                for top in sorted(root.iterdir()):
                    if not top.is_dir():
                        if top.is_file(): files.append(top)
                        continue
                    for child in sorted(top.iterdir()):
                        if child.is_file(): files.append(child)
                        elif child.is_dir():
                            for grandchild in sorted(child.iterdir()):
                                if grandchild.is_file(): files.append(grandchild)
                                if len(files) >= 50: break
                        if len(files) >= 50: break
                    if len(files) >= 50: break
            out.append({'task':task,'replicate':rep,'root_exists':root.is_dir(),'bounded_file_count':len(files),'top_entries':sorted(p.name for p in root.iterdir()) if root.is_dir() else [],'examples':[shape(p) for p in files[:30]]})
    print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
