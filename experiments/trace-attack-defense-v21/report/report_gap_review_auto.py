"""Deterministic gap-loss packet accounting; no endpoint selection or rescoring."""
import os, json, csv
from report_sources import PUBLIC, read, write

def main():
    assert os.environ.get('SLURM_JOB_ID')
    index=read(PUBLIC/'gap-inspection-index.json')
    rows=[]
    for item in index:
        rows.append({k:item.get(k) for k in ('arm','task_id','replicate','selection_reasons','delta_W','delta_W_train','delta_S','delta_H','delta_A','delta_W_minus_S','delta_W_minus_A','packet_path','packet_sha256')})
    rows.sort(key=lambda r:(r['arm'],r['task_id'],r['replicate']))
    write(PUBLIC/'gap-reviewed-cases.json',rows)
    with (PUBLIC/'gap-reviewed-cases.csv').open('w',newline='') as f:
        fields=list(rows[0]) if rows else ['arm','task_id']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    summary={'provider_calls':0,'inspection_packets':len(rows),'substantial_A_loss_cases':sum(float(r.get('delta_A') or 0)<=-5 for r in rows),'selection':'top task contributors plus every flagged case; no endpoint exclusions'}
    write(PUBLIC/'gap-case-review-summary.json',summary)
    (PUBLIC/'gap-case-review.md').write_text('# Gap contributor and quality-loss packet accounting\n\nPackets are selected deterministically from the complete paired table. This report preserves post-treatment score differences and public-artifact receipts; it does not claim mediation or rewrite any outcome judgment.\n\n'+json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))
if __name__=='__main__': main()
