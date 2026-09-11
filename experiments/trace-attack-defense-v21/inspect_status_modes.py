import json,os,stat
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
B=Path(__file__).resolve().parent; E=load_experiment(B/'result20.yaml'); root=Path(str(E.dag['revise']['output_dir']))
for status in list(root.glob('experiments/*/*/*/*/submissions/*/status.json'))[:8]:
 st=status.stat(); par=status.parent.stat(); raw=json.loads(status.read_bytes()); print(status, 'status_mode',oct(stat.S_IMODE(st.st_mode)),'dir_mode',oct(stat.S_IMODE(par.st_mode)),'uid',st.st_uid,par.st_uid,'workspace',raw.get('workspace_dir'))
