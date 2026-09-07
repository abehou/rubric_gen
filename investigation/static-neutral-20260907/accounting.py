"""Count persisted work and exact imports without issuing model requests."""
import json
from pathlib import Path
from collections import Counter
HERE=Path(__file__).resolve().parent

def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

def main():
    manifest=json.loads((HERE/'manifest.json').read_text());rows=[];import_sources=Counter();training=[]
    for run in manifest['configs']:
        root=Path(run['audit']);study=Path(run['study'])
        for stage in ['rubric_score','absolute_score','pairwise_preference']:
            saved=list((root/stage/'records').glob('*.json'));imports={r['key']:r for r in records(root/stage/'imported-requests.jsonl')}
            assert set(imports).issubset({p.stem for p in saved})
            for r in imports.values():import_sources['historical' if '/runs/autonomous-dev3-' in r['source'] else 'current-comparison']+=1
            rows.append(dict(tag=run['tag'],stage=stage,completed=len(saved),exact_imports=len(imports),new_completed=len(saved)-len(imports)))
        for stage in ['direct_full_trajectory','direct_post_update','direct_final_artifact','direct_final_revision']:
            saved=list((root/stage).glob('evaluations/*/cases/*/*/score.json'))
            rows.append(dict(tag=run['tag'],stage=stage,completed=len(saved)))
        cache=study/'shared-judgments/judge';entries=[p for p in (cache/'entries').iterdir() if p.is_dir() and not p.name.startswith('.')]
        imports={r['key']:r for r in records(cache/'imported-requests.jsonl')}
        training.append(dict(tag=run['tag'],completed_cache_entries=len(entries),exact_imports=len(imports),new_completed=len(entries)-len(imports)))
    chunks=Counter()
    for p in (HERE/'direct-chunk-cache').glob('*.json'):
        chunks[json.loads(p.read_text())['identity']['model']]+=1
    assignments=[]
    for run in manifest['configs']:
        assignments.extend(json.loads((Path(run['study'])/'study.json').read_text())['records'])
    result=dict(assignment_status=dict(Counter(r['status'] for r in assignments)),assignment_attempt_counts=dict(Counter(r['attempt_count'] for r in assignments)),
                audit_records=rows,audit_completed=sum(r['completed'] for r in rows),semantic_import_sources=dict(import_sources),
                training_cache_entries=training,successful_cached_direct_chunks=dict(chunks),
                note='Record counts are persisted measurement slots; exact imports can refer to the same semantic judgment across studies. Chunk counts are successful authentic responses, not total attempted HTTP requests. SDK/transport retries are not treated as new completed judgments.')
    (HERE/'accounting.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
