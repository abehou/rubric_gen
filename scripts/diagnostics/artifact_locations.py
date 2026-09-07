"""Explicit, byte-attested relocation of completed current-format datasets.

This is an offline reader, not a runtime resume shim or an artifact migration.
Location receipts are created before moving files; saved artifacts are never edited.
"""
import hashlib
import json
from pathlib import Path


def _receipt(root):
    root = Path(root).absolute()
    path = root.parent / f'{root.name}.location.json'
    if not path.exists():
        return None
    assert not path.is_symlink(), path
    data = json.loads(path.read_text())
    assert data['kind'] == 'completed-artifact-relocation-v1'
    assert data['destination_name'] == root.name
    original = Path(data['original_root'])
    assert original.is_absolute() and '..' not in original.parts
    return data


def recorded_root(root):
    data = _receipt(root)
    return Path(data['original_root']) if data else Path(root).absolute()


def regular_file(root, relative):
    root = Path(root).absolute()
    relative = Path(relative)
    assert not relative.is_absolute() and relative.parts
    assert '..' not in relative.parts and '.' not in relative.parts
    assert root.is_dir() and not root.is_symlink(), root
    path = root
    for part in relative.parts:
        path /= part
        assert not path.is_symlink(), path
    assert path.is_file(), path
    return path


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_location(root):
    """Reject missing, additional, changed, escaping, or symlinked artifacts."""
    root = Path(root).absolute()
    data = _receipt(root)
    if data is None:
        return None
    assert root.is_dir() and not root.is_symlink(), root
    inventory = regular_file(root.parent, Path('inventories') / f'{root.name}.json')
    assert file_digest(inventory) == data['inventory_sha256'], inventory
    expected = json.loads(inventory.read_text())
    assert expected['original_root'] == data['original_root']
    files = expected['files']
    actual = set()
    for path in root.rglob('*'):
        assert not path.is_symlink(), path
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    assert actual == set(files), (root, 'missing or additional files')
    for relative, digest in files.items():
        assert file_digest(regular_file(root, relative)) == digest, relative
    return {'files': len(files), 'inventory_sha256': data['inventory_sha256']}
