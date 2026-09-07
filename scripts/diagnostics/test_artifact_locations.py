"""Offline relocation integrity tests; fixtures never touch real experiment data."""
import json
from pathlib import Path
import tempfile
import unittest

from artifact_locations import file_digest, recorded_root, regular_file, verify_location


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'original'
        self.source.mkdir()
        (self.source / 'record.json').write_bytes(b'{"value":1}\r\n')
        self.target = self.base / 'renamed'
        inventory = {'original_root': str(self.source),
                     'files': {'record.json': file_digest(self.source / 'record.json')}}
        (self.base / 'inventories').mkdir()
        p = self.base / 'inventories/renamed.json'
        p.write_text(json.dumps(inventory))
        self.receipt = self.base / 'renamed.location.json'
        self.receipt.write_text(json.dumps({
            'kind': 'completed-artifact-relocation-v1', 'original_root': str(self.source),
            'destination_name': 'renamed', 'inventory_sha256': file_digest(p)}))
        self.source.rename(self.target)

    def test_renamed_bytes_and_original_identity(self):
        self.assertEqual(verify_location(self.target)['files'], 1)
        self.assertEqual(recorded_root(self.target), self.source)
        self.assertFalse(self.source.exists())

    def test_changed_bytes_rejected(self):
        (self.target / 'record.json').write_bytes(b'{"value":1}\n')
        with self.assertRaises(AssertionError):
            verify_location(self.target)

    def test_missing_and_extra_files_rejected(self):
        path = self.target / 'record.json'
        path.rename(self.target / 'other.json')
        with self.assertRaises(AssertionError):
            verify_location(self.target)

    def test_symlink_rejected(self):
        (self.target / 'link').symlink_to(self.target / 'record.json')
        with self.assertRaises(AssertionError):
            verify_location(self.target)

    def test_escape_rejected(self):
        for value in ('../record.json', '/tmp/record.json'):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                regular_file(self.target, value)

    def test_altered_inventory_rejected(self):
        (self.base / 'inventories/renamed.json').write_text('{}')
        with self.assertRaises(AssertionError):
            verify_location(self.target)

    def test_wrong_destination_rejected(self):
        data = json.loads(self.receipt.read_text())
        data['destination_name'] = 'not-renamed'
        self.receipt.write_text(json.dumps(data))
        with self.assertRaises(AssertionError):
            verify_location(self.target)


if __name__ == '__main__':
    unittest.main()
