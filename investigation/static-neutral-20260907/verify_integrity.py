"""Verify frozen production/config identities and original historical files."""
import json,hashlib
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    launch=json.loads((HERE/'revise-01-launch.json').read_text());manifest=json.loads((HERE/'manifest.json').read_text())
    source_changed=[name for name,want in launch['source_hashes'].items() if sha(ROOT/name)!=want]
    config_changed=[r['tag'] for r in manifest['configs'] if sha(Path(r['config']))!=r['config_sha256']]
    historical=json.loads((HERE.parent/'selected-reference-wiring-20260907/historical-before.json').read_text())
    changed=[];missing=[]
    for name,want in historical.items():
        p=ROOT/name
        if not p.is_file():missing.append(name)
        elif sha(p)!=want:changed.append(name)
    result=dict(checked_at=datetime.now().astimezone().isoformat(),production_files=len(launch['source_hashes']),source_changed=source_changed,
                config_changed=config_changed,manifest_unchanged=sha(HERE/'manifest.json')==launch['manifest_sha256'],
                historical_files=len(historical),historical_changed=changed,historical_missing=missing)
    (HERE/'integrity.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));assert not(source_changed or config_changed or changed or missing) and result['manifest_unchanged']
if __name__=='__main__':main()
