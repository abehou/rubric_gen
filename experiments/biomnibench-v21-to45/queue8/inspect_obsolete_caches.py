"""Read-only inspection of the exact obsolete cache allowlist."""
from __future__ import annotations
import json, os
from pathlib import Path
ROOT=Path('/data/user_data/aydanh/rubric_gen/cache/environments')
ACTIVE=ROOT/'trace-repair-10381602'
TARGETS=(ROOT/'a5f86d3f89f6256c-be8151e15cce-10380168',ROOT/'a5f86d3f89f6256c-d61735ca9b4a-10380169')
KNOWN=TARGETS[1]/'lib/python3.12/site-packages/statsmodels/tsa/statespace/tests/results/frbny_nowcast/Nowcasting/data/US/__init__.py'
OUT=Path(__file__).resolve().parent/'obsolete-cache-inspection.json'
def stat_record(path):
    try:
        s=path.stat()
    except OSError as exc:
        return {'path':str(path),'exists':False,'error':f'{type(exc).__name__}: {exc}'}
    return {'path':str(path),'exists':True,'is_dir':path.is_dir(),'size':s.st_size,'mode':oct(s.st_mode&0o777),'uid':s.st_uid,'gid':s.st_gid}
def main():
    result={'root':stat_record(ROOT),'active':stat_record(ACTIVE),'targets':[],'known_failure_path':stat_record(KNOWN)}
    for target in TARGETS:
        row={'root':stat_record(target),'top_entries':[]}
        try: row['top_entries']=[stat_record(p) for p in sorted(target.iterdir())]
        except OSError as exc: row['list_error']=f'{type(exc).__name__}: {exc}'
        count=total=0; errors=[]
        try:
            for current, dirs, files in os.walk(target):
                count += len(dirs)+len(files)
                for name in files:
                    try: total += (Path(current)/name).stat().st_size
                    except OSError as exc:
                        if len(errors)<5: errors.append(f'{Path(current)/name}: {type(exc).__name__}: {exc}')
                if count>=50000: break
        except OSError as exc: errors.append(f'walk: {type(exc).__name__}: {exc}')
        row.update({'bounded_entry_count':count,'bounded_bytes':total,'errors':errors,'census_complete':count<50000})
        result['targets'].append(row)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'out':str(OUT),'active_exists':ACTIVE.exists(),'target_exists':[p.exists() for p in TARGETS]}),flush=True)
if __name__=='__main__': main()
