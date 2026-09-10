"""Private launch guard for the approved frozen cue recovery composition."""
import hashlib,subprocess
from pathlib import Path
BASE='0fbe0bbd9acfb8846bb62dbdefa3cfc646c3aa1a'
REQUIRED={
 'src/rubric_gen/submission_revision/pretreatment_reuse.py':'314ea3ddf60796f4dc705920a7828466b2f6be2c',
 'src/rubric_gen/submission_revision/contrasts.py':'30ae38e71f0bd9ed37311ac70dd4a85c72b0fc0e',
}
def verify(code):
 code=Path(code)
 names=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'--','src','config','uv.lock','pyproject.toml'],cwd=code,text=True).splitlines()
 expected=set(n for n in names if n.startswith('src/'))
 actual={str(p.relative_to(code)) for p in (code/'src').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
 if actual!=expected:raise RuntimeError('frozen cue source inventory changed')
 hashes={}
 for name in names:
  ref=REQUIRED.get(name,BASE)
  want=subprocess.check_output(['git','show',f'{ref}:{name}'],cwd=code)
  path=code/name
  if path.read_bytes()!=want:raise RuntimeError(f'frozen cue required correctness/source mismatch: {name}; expected {ref}')
  hashes[str(path)]=hashlib.sha256(want).hexdigest()
 return hashes
