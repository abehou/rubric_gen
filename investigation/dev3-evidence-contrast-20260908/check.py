import ast, hashlib, json, os, subprocess, sys
from pathlib import Path
root=Path.cwd(); parent=root.parent/'dev3-evidence-sidecar'
relative=Path('src/rubric_gen/submission_revision/evolution_protocol.py')
changes=subprocess.check_output(['git','diff','--name-only','4a8cebe'],text=True).splitlines()
assert changes==[str(relative)], changes
before=ast.parse((parent/relative).read_text()); after=ast.parse((root/relative).read_text())
for tree in (before,after):
    tree.body=[x for x in tree.body if not isinstance(x,ast.FunctionDef) or x.name!='induction_instructions']
assert ast.dump(before)==ast.dump(after), 'Non-induction behavior changed'
from rubric_gen.submission_revision.evolution_protocol import induction_instructions
assert 'Defects shared equally by both' in induction_instructions()
assert 'Independent validation' in induction_instructions()
source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'src').rglob('*.py')}
out=Path('/home/aydanh/repos/rubric_gen/runs')/('dev3-evidence-contrast-check-'+os.environ['SLURM_JOB_ID']);out.mkdir(exist_ok=False)
with (out/'tests.log').open('w') as stream:
    result=subprocess.run([sys.executable,'-m','pytest','-q','tests/test_rubric_evolution.py','tests/test_red_team.py','tests/test_pretreatment_reuse.py','tests/test_rubric_generation.py','tests/test_architecture.py'],stdout=stream,stderr=subprocess.STDOUT)
unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in source.items())
(out/'result.json').write_text(json.dumps(dict(job=os.environ['SLURM_JOB_ID'],changes=changes,non_induction_ast_equal=True,test_exit=result.returncode,source_unchanged=unchanged,source_hashes=source),indent=2)+'\n')
sys.exit(result.returncode or int(not unchanged))
