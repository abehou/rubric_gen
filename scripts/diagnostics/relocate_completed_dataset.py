"""One-off, explicitly scoped relocation requested on 2026-09-06.

Prepare writes inventories outside source trees. Move refuses overwrite and uses
the exact source/destination pairs below. Verify compares every saved byte.
"""
from datetime import datetime
import json
from pathlib import Path
import sys

from artifact_locations import file_digest, verify_location

REPO = Path(__file__).resolve().parents[2]
DEST = REPO / 'runs/biomnibench-redteam-2026-09-05'
FORMAL = 'biomnibench-da-factorial-r10-8ab12c898ae7'
SMALL = 'biomnibench-da-factorial-r3-b07888ff76df'
PAIRS = [
    (REPO / 'runs/studies/20260905-redteam-v7' / FORMAL, DEST / 'study'),
    (REPO / 'runs/detections/20260905-redteam-v7-audit-v2' / FORMAL, DEST / 'audit'),
    (REPO / 'runs/reports/20260905-redteam-v7', DEST / 'reports'),
    (REPO / 'runs/provenance/20260905-redteam-v7', DEST / 'provenance'),
    (REPO / 'runs/preflights/provider-availability-v7' / SMALL, DEST / 'acceptance/study'),
    (REPO / 'runs/preflight-detections/provider-availability-v7-audit-v2' / SMALL,
     DEST / 'acceptance/audit'),
]


def prepare():
    for source, target in PAIRS:
        assert source.is_dir() and not source.is_symlink() and not target.exists()
        inventory = {'original_root': str(source), 'files': {}}
        for path in sorted(source.rglob('*')):
            assert not path.is_symlink(), path
            if path.is_file():
                inventory['files'][path.relative_to(source).as_posix()] = file_digest(path)
        folder = target.parent / 'inventories'
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f'{target.name}.json'
        with p.open('x') as stream:
            json.dump(inventory, stream, indent=2)
            stream.write('\n')
        receipt = {'kind': 'completed-artifact-relocation-v1',
                   'created_at': datetime.now().astimezone().isoformat(),
                   'original_root': str(source), 'destination_name': target.name,
                   'inventory_sha256': file_digest(p)}
        with (target.parent / f'{target.name}.location.json').open('x') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
        print(json.dumps({'prepared': str(target), 'files': len(inventory['files'])}), flush=True)


def move():
    for source, target in PAIRS:
        assert source.is_dir() and not source.is_symlink() and not target.exists()
        receipt = json.loads((target.parent / f'{target.name}.location.json').read_text())
        assert receipt['original_root'] == str(source)
        source.rename(target)
        result = verify_location(target)
        print(json.dumps({'moved': str(target), **result}), flush=True)


def verify():
    print(json.dumps({str(target.relative_to(DEST)): verify_location(target)
                      for _, target in PAIRS}, indent=2))


if __name__ == '__main__':
    actions = {'prepare': prepare, 'move': move, 'verify': verify}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit('Supply prepare, move or verify for this one-off dataset relocation')
    actions[sys.argv[1]]()
