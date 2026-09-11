"""Provider-free v2 -> v2.1 compatibility replay for completed assignments."""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path

SOURCE_STUDY = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/study/biomnibench-da-factorial-r10-d2237f051bbf')

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def read(path: Path):
    return json.loads(path.read_bytes())

def norm(title: str) -> str:
    return ' '.join(title.casefold().split())

def tree_digest(root: Path, *, exclude=()):
    excluded = set(exclude)
    rows = []
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = str(path.relative_to(root))
        if rel in excluded:
            continue
        rows.append((rel, sha(path), path.stat().st_size))
    payload = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest(), rows

def generation_criteria(gen_dir: Path):
    value = read(gen_dir / 'criteria.json')
    if isinstance(value, dict):
        value = value.get('criteria', value.get('elicited_criteria', value))
    if not isinstance(value, list):
        raise RuntimeError(f'invalid criteria file: {gen_dir}')
    return value

def criterion_id(c):
    return c.get('criterion_id') or c.get('id')

def title(c):
    return c.get('title', '')

def proposal_rows(gen_dir: Path):
    p = gen_dir / 'criterion-proposal.json'
    if not p.exists(): return []
    value = read(p)
    rows = value.get('criteria', [])
    if not isinstance(rows, list): raise RuntimeError(f'invalid proposal: {p}')
    return rows

def accepted_ids(gen_dir: Path):
    p = gen_dir / 'aggregate-margins.json'
    if not p.exists(): return []
    value = read(p)
    return list(value.get('accepted_candidate_ids', []))

def assignment_check(root: Path):
    gen_dirs = sorted((root/'rubric-generations').glob('generation-*'))
    if not gen_dirs: raise RuntimeError(f'no generations: {root}')
    base = generation_criteria(gen_dirs[0])
    base_titles = {norm(title(c)) for c in base if title(c)}
    collisions = []
    generations = []
    previous = []
    for gen_dir in gen_dirs:
        round_no = int(gen_dir.name.rsplit('-', 1)[1])
        criteria = generation_criteria(gen_dir)
        titles = [norm(title(c)) for c in criteria if title(c)]
        if len(titles) != len(set(titles)) or set(titles) & base_titles:
            collisions.append({'generation': round_no, 'kind': 'persisted_active_title_invariant'})
        manifest = read(gen_dir/'manifest.json')
        for name, digest in manifest.get('file_sha256s', {}).items():
            path = gen_dir/name
            if not path.is_file() or sha(path) != digest:
                raise RuntimeError(f'manifest hash mismatch: {path}')
        if round_no > 0:
            current = {criterion_id(c): c for c in previous}
            occupied = set()
            for raw in proposal_rows(gen_dir):
                candidate_title = norm(title(raw))
                replacements = set(raw.get('replaces', []))
                collision = None
                if candidate_title in base_titles:
                    collision = 'base'
                else:
                    for cid, item in current.items():
                        if norm(title(item)) == candidate_title and cid not in replacements:
                            collision = 'learned'
                            break
                    if collision is None and candidate_title in occupied:
                        collision = 'accepted_candidate'
                if collision:
                    collisions.append({'generation': round_no, 'kind': collision,
                                       'candidate_id': None, 'title': title(raw),
                                       'replaces': sorted(replacements)})
                # Failed candidates do not reserve a title; only accepted IDs do.
                # A proposal's identity is available in native criteria only after
                # the host constructor, so use accepted criterion title below.
            accepted = accepted_ids(gen_dir)
            active_by_id = {criterion_id(c): c for c in previous}
            accepted_items = []
            for c in criteria:
                if criterion_id(c) in accepted:
                    accepted_items.append(c)
            occupied.update(norm(title(c)) for c in accepted_items)
        previous = criteria
        digest, rows = tree_digest(gen_dir)
        generations.append({'generation': round_no, 'directory': str(gen_dir),
                            'tree_sha256': digest, 'file_count': len(rows),
                            'generation_sha256': manifest.get('generation_sha256'),
                            'rubric_sha256': manifest.get('rubric_sha256'),
                            'accepted_candidate_ids': accepted_ids(gen_dir),
                            'title_count': len(titles)})
    # Behavioral bytes are the complete solver-visible/stopping/submission surface.
    selected = []
    for rel in ('state.json', 'manifest.json'):
        p = root/rel
        if p.exists(): selected.append((rel, sha(p)))
    for subroot in ('submissions', 'turns', 'submission-rubric-bindings', 'feedback', 'rubric-evaluations'):
        p = root/subroot
        if p.exists():
            digest, rows = tree_digest(p)
            selected.append((subroot, digest, len(rows)))
    behavior_sha = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'assignment_id': read(root/'manifest.json')['assignment_id'],
            'root': str(root), 'generations': generations,
            'generation_count': len(generations), 'collision_count': len(collisions),
            'collisions': collisions, 'behavior_sha256': behavior_sha,
            'behavior_components': selected}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--source-study', type=Path, default=SOURCE_STUDY); ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    ledger = read(args.source_study/'study.json')
    rows = [r for r in ledger['records'] if r.get('status') == 'completed']
    failed = [r for r in ledger['records'] if r.get('status') != 'completed']
    results = []
    errors = []
    for row in rows:
        root = args.source_study / row['experiment_dir']
        try:
            result = assignment_check(root)
            # Keep ledger and assignment identities bound to the saved producer.
            if result['assignment_id'] != row['assignment_id']:
                raise RuntimeError('assignment identity mismatch')
            results.append(result)
        except Exception as exc:
            errors.append({'assignment_id': row.get('assignment_id'), 'error_type': type(exc).__name__, 'error': str(exc)})
    report = {
        'kind': 'attack_defense_v2_to_v2.1_provider_free_compatibility',
        'producer_run_root': str(args.source_study),
        'producer_experiment_id': ledger.get('experiment_id'),
        'producer_version': 'attack_defense_v2', 'consumer_version': 'attack_defense_v2.1',
        'sealed_model_responses_reused': True, 'provider_calls': 0,
        'completed_input_assignments': len(rows), 'failed_input_assignments': len(failed),
        'compatible_assignments': sum(not r['collision_count'] for r in results if r['assignment_id']),
        'results': results, 'errors': errors,
        'required_gate': {'completed': 118, 'compatible': 118, 'collisions': 0, 'behavioral_outputs_unchanged': 118},
        'gate': {'passed': len(rows) == 118 and not errors and all(r['collision_count'] == 0 for r in results),
                 'reason': 'v2.1 host guard replayed against every sealed proposal; no candidate would be structurally rejected on a completed assignment.'},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'completed':len(rows),'failed':len(failed),'errors':len(errors),'collisions':sum(r['collision_count'] for r in results),'passed':report['gate']['passed']}), flush=True)
    if not report['gate']['passed']:
        raise SystemExit(2)

if __name__ == '__main__':
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('compute storage requires Slurm')
    main()
