"""Bounded same-allocation native revision recovery; unknown failures stop."""
import hashlib
import json
from pathlib import Path
import re

TRANSIENT_TYPES = {'APITimeoutError', 'APIConnectionError', 'TimeoutError', 'ConnectionError'}


def revision_retry_evidence(study_root):
    path = Path(study_root) / 'study.json'
    if not path.is_file():
        return None
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get('status') not in {'failed', 'failed_scope'}:
        return None
    scope = manifest.get('execution_conditions')
    records = [r for r in manifest['records'] if scope is None or r['condition_id'] in scope]
    ids = manifest.get('execution_assignment_ids')
    if ids is not None:
        records = [r for r in records if r['assignment_id'] in ids]
    if not records or any(r['status'] not in {'completed', 'failed'} for r in records):
        return None
    failures = [r for r in records if r['status'] == 'failed']
    if not failures:
        return None
    summary = []
    for record in failures:
        error_type = record.get('error_type')
        if error_type == 'RubricProposerProviderError':
            match = re.search(r'last error: ([A-Za-z]+)\)$', record.get('error', ''))
            cause = match.group(1) if match else None
        else:
            cause = error_type
        if cause not in TRANSIENT_TYPES:
            return None
        summary.append({'assignment_id': record['assignment_id'], 'error_class': cause})
    return {'study_manifest': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
            'completed': len(records) - len(failures), 'failures': summary}


def run_revision_attempts(run_once, *, study_root, receipt, label, stop,
                          verify_source, maximum_attempts=3):
    """Child must be joined by run_once; native CLI revalidates before each resume."""
    if not 1 <= maximum_attempts <= 3:
        raise ValueError('revision recovery allows at most three stage invocations')
    for attempt in range(1, maximum_attempts + 1):
        if stop.is_set():
            return 143
        verify_source()
        code = run_once(attempt)
        if code == 0 or stop.is_set() or code < 0 or attempt == maximum_attempts:
            return code
        evidence = revision_retry_evidence(study_root)
        if evidence is None:
            return code
        record = {'attempt': attempt, 'exit_code': code, 'next_attempt': attempt + 1,
                  'reason': 'All unfinished selected assignments have known transient transport failures',
                  'evidence': evidence}
        path = Path(receipt) / f'{label}-recovery-{attempt}.json'
        with path.open('x') as stream:
            json.dump(record, stream, indent=2)
        if stop.wait(10):
            return 143
    raise AssertionError('unreachable')
