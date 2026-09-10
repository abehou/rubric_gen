"""Read-only canonical count/arithmetic verification; no provider calls."""
import json,os
from pathlib import Path
import pandas as pd
from scipy.stats import fisher_exact
from rubric_gen.submission_revision.experiment import load_experiment
ROOT=Path('/home/aydanh/repos/rubric_gen')
def main():
    assert os.environ.get('SLURM_JOB_ID')
    exp=load_experiment(ROOT/'investigation/result20-cue-score-first-trace-20260909/trace-results20.yaml')
    data=exp.task_dir('da-12-2')/'environment/data'
    frame=pd.read_excel(data/'TS7.xlsx',header=None,dtype=str).iloc[2:]
    def symbols(col):return {str(x).strip() for x in frame.iloc[:,col].dropna() if str(x).strip()}
    op=symbols(0);kd=symbols(4)
    def flagged(symbol_col,flag_col):
        return {str(row.iloc[symbol_col]).strip() for _,row in frame.iterrows()
                if pd.notna(row.iloc[symbol_col]) and str(row.iloc[flag_col]).strip().lower()=='v'}
    shared=flagged(0,2);shared_kd=flagged(4,6)
    sets={}
    for line in (data/'GSEA_gmt.gmt').read_text().splitlines():
        cells=line.split('\t');sets[cells[0]]={x.strip() for x in cells[2:] if x.strip()}
    pathway=sets['HALLMARK_G2M_CHECKPOINT'];out={}
    for label,u in [('overexpression',op),('union',op|kd)]:
        q=shared&u;g=pathway&u;a=len(q&g);table=[[a,len(q-g)],[len(g-q),len(u-(q|g))]];odds,p=fisher_exact(table,alternative='greater')
        out[label]=dict(universe=len(u),query=len(q),pathway_in_universe=len(g),table=table,odds=float(odds),p=float(p))
    out['pathways']=len(sets);out['gmt_g2m_size']=len(pathway)
    out['flag_sets_equal']=shared==shared_kd
    out['unflagged_intersection']=sorted((op&kd)-shared)
    import hashlib
    out['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [data/'TS7.xlsx',data/'GSEA_gmt.gmt',Path(__file__)]}
    dest=ROOT/'runs'/f'input-provenance-count-check-{os.environ["SLURM_JOB_ID"]}';dest.mkdir(exist_ok=False);(dest/'result.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
if __name__=='__main__':main()
