"""Archive the actual dirty source and selected public data, excluding secrets."""
import json
from pathlib import Path
import subprocess
import tarfile

from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'output/healthbench-result20-preparation'


def main():
    receipt={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True).splitlines(),
             'description':'Actual source archive plus dirty diff; not a clean-commit claim'}
    (HERE/'source-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (HERE/'source.diff').write_bytes(subprocess.check_output(['git','diff','--binary','HEAD'],cwd=ROOT))
    with tarfile.open(OUT/'source.tar.gz','w:gz') as tar:
        for name in ['src','config','scripts','tests','pyproject.toml','uv.lock','README.md',
                     'experiments/healthbench-hard-result20','data/healthbench-hard/challenge20-20260926']:
            tar.add(ROOT/name,arcname=name,filter=lambda info:None if '__pycache__' in Path(info.name).parts else info)
    print(OUT/'source.tar.gz')


if __name__=='__main__': main()
