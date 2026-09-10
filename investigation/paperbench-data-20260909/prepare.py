"""Pinned native PaperBench data only, with pre-download storage gate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from rubric_gen.benchmarks.paperbench_code_dev import dataset as d

ROOT = Path('/home/aydanh/repos/rubric_gen')
assert os.environ.get('SLURM_JOB_ID')
OUT = ROOT / ('runs/paperbench-data-prepare-' + os.environ['SLURM_JOB_ID'])
OUT.mkdir(exist_ok=False)
DEST = Path('/data/user_data/aydanh/rubric_gen/data') / ('paperbench-' + d.PAPERBENCH_REVISION[:12])
DEST.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024**2):
            h.update(chunk)
    return h.hexdigest()


def main():
    # Metadata only: no benchmark asset download before the capacity gate.
    url = f'https://api.github.com/repos/{d.PAPERBENCH_REPOSITORY}/git/trees/{d.PAPERBENCH_REVISION}?recursive=1'
    with urllib.request.urlopen(urllib.request.Request(url, headers=d._github_headers()), timeout=60) as response:
        tree = json.load(response)
    assert not tree.get('truncated'), 'Incomplete source inventory'
    papers = set(d.PAPERBENCH_DEV_PAPERS + d.PAPERBENCH_RESULTS_PAPERS)
    files = []
    prefix = 'project/paperbench/data/papers/'
    for entry in tree['tree']:
        path = entry['path']
        if entry['type'] != 'blob' or not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split('/')
        if parts[0] not in papers or len(parts) < 2:
            continue
        if parts[1] not in (*d._ROOT_FILES, 'judge.addendum.md', 'assets'):
            continue
        size = entry['size']
        # Small Git blobs can be LFS pointers; resolve declared hydrated size.
        if size <= 1024:
            raw = f'https://raw.githubusercontent.com/{d.PAPERBENCH_REPOSITORY}/{d.PAPERBENCH_REVISION}/{path}'
            with urllib.request.urlopen(urllib.request.Request(raw, headers=d._github_headers()), timeout=60) as response:
                content = response.read(1025)
            assert hashlib.sha1(f'blob {len(content)}\0'.encode() + content).hexdigest() == entry['sha']
            if content.startswith(d._LFS_PREFIX):
                size = int(next(line[5:] for line in content.decode().splitlines() if line.startswith('size ')))
        files.append(dict(path=path, git_blob_sha1=entry['sha'], hydrated_bytes=size))
    assert {f['path'][len(prefix):].split('/')[0] for f in files} == papers
    estimate = sum(f['hydrated_bytes'] for f in files)
    # Raw temporary inputs plus converted inputs; ample allowance for rendering.
    required = 3 * estimate + 2 * 1024**3
    reserve = 180 * 1024**3  # concurrent BioMNIBench data plus working headroom
    free = shutil.disk_usage(DEST).free
    save('capacity-and-source.json', dict(repository=d.PAPERBENCH_REPOSITORY, revision=d.PAPERBENCH_REVISION,
         paper_sets={k:list(v) for k,v in d.PAPERBENCH_PAPER_SETS.items()}, source_files=files,
         estimated_hydrated_bytes=estimate, required_working_bytes=required, reserved_other_work_bytes=reserve,
         free_bytes=free, destination=str(DEST), downloader_sha256=sha(ROOT/'download_paperbench.py'),
         dataset_implementation_sha256=sha(Path(d.__file__))))
    assert free > required + reserve, 'Insufficient capacity; no dataset download started'
    completed = []
    for split in ('all', 'dev'):
        target = DEST / split
        if not target.exists():
            assert shutil.disk_usage(DEST).free > required + reserve, 'Capacity changed; stopping before next split'
            with tempfile.TemporaryDirectory(prefix='paperbench-tmp-', dir=DEST) as temporary:
                env = dict(os.environ, TMPDIR=temporary)
                with (OUT / f'{split}-download.log').open('x') as log:
                    subprocess.run([sys.executable, str(ROOT/'download_paperbench.py'), split, str(target)],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        d.validate_paperbench_code_dataset(target, source_split=split)
        hashes = []
        for path in sorted(target.rglob('*')):
            assert not path.is_symlink(), 'Unexpected dataset symlink'
            if path.is_file():
                hashes.append(dict(path=str(path.relative_to(target)), bytes=path.stat().st_size, sha256=sha(path)))
        record = dict(split=split, path=str(target), papers=list(d.paperbench_papers(split)),
                      validated=True, files=hashes, bytes=sum(f['bytes'] for f in hashes))
        save(f'{split}-validated.json', record)
        # Seal only this dataset, never historical artifacts or credentials.
        for path in target.rglob('*'):
            path.chmod(0o555 if path.is_dir() else 0o444)
        target.chmod(0o555)
        completed.append(record)
    save('result.json', dict(success=True, job_id=os.environ['SLURM_JOB_ID'], datasets=completed,
         free_bytes_after=shutil.disk_usage(DEST).free, script_sha256=sha(Path(__file__))))
    print(json.dumps(dict(success=True, papers=sum(len(r['papers']) for r in completed), output=str(OUT))))


try:
    main()
except Exception as exc:
    save('failure.json', dict(error_type=type(exc).__name__, error=str(exc)))
    raise
