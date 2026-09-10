"""Archive only two known incompatible failed attempts after terminal ownership."""
import hashlib,json,os,subprocess
from pathlib import Path
from rubric_gen.submission_revision.study import _exclusive_study_lease
ROOT=Path('/home/aydanh/repos/rubric_gen')
BASE=ROOT/'runs/babel-result20-cue-contrast-20260908'
EXPECTED={'da-10-1--rep-003--solver-luna--user-simulator-static':'live workspace changed after the last checkpoint','da-15-8--rep-002--solver-luna--user-simulator-static':'failed solver turn artifacts are incomplete'}
def main():
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm required')
    live=subprocess.check_output(['squeue','-h','-u','aydanh','-o','%i'],text=True).split()
    if {'10364363','10364765'} & set(live):raise RuntimeError('prior owner active')
    accounting=subprocess.check_output(['sacct','-n','-P','-j','10364765','--format=JobIDRaw,State'],text=True)
    if not any(r.strip().split('|')[:2]==['10364765','FAILED'] for r in accounting.splitlines()):raise RuntimeError('expected failed terminal owner not verified')
    owner=BASE/'owners/static-results20';study=BASE/'static/study/biomnibench-da-factorial-r10-f0203f5d69f3'
    with _exclusive_study_lease(owner),_exclusive_study_lease(study):
        manifest=study/'study.json';raw=manifest.read_bytes();d=json.loads(raw)
        records=[r for r in d['records'] if r['condition_id']=='user-simulator-static']
        failed={r['assignment_id']:r for r in records if r['status']=='failed'}
        if set(failed)!=set(EXPECTED) or sum(r['status']=='completed' for r in records)!=58:raise RuntimeError('unexpected scope state')
        moves=[]
        for aid,error in EXPECTED.items():
            if failed[aid].get('error')!=error:raise RuntimeError('unexpected failure')
            task,rep,_,condition=aid.split('--');src=study/'experiments'/task/rep/'luna'/condition
            if not src.is_dir() or src.is_symlink():raise RuntimeError('invalid source')
            moves.append((aid,src))
        archive=BASE/'invalid-attempts'/f'pre-fresh-{os.environ["SLURM_JOB_ID"]}';archive.mkdir(parents=True,exist_ok=False)
        (archive/'study-before.json').write_bytes(raw)
        journal={'reason':'Native resume rejected two infrastructure-invalid attempts; fresh assignment runs required','prior_owner':'10364765','study_sha256':hashlib.sha256(raw).hexdigest(),'moves':[]}
        for aid,src in moves:
            dst=archive/aid;src.rename(dst);journal['moves'].append({'assignment_id':aid,'from':str(src),'to':str(dst)})
            (archive/'manifest.json').write_text(json.dumps(journal,indent=2)+'\n')
        if manifest.read_bytes()!=raw:raise RuntimeError('study changed unexpectedly')
        print(archive)
if __name__=='__main__':main()
