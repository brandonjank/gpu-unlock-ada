# SPDX-License-Identifier: GPL-2.0-only
"""Ensure package checks reject wrong metadata and altered payload bytes."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
# CI scripts are export-ignored; native source-package %check omits this helper.
HELPER = ROOT / '.github/ci/rpm_permissions.py'
if HELPER.is_file():
    spec = importlib.util.spec_from_file_location('rpm_permissions', HELPER)
    rpm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpm)


@unittest.skipUnless(HELPER.is_file(), 'RPM checker belongs to checkout CI')
class RpmPermissionTests(unittest.TestCase):
    def test_metadata_rejects_executable_missing_duplicate_and_wrong_owner_entries(self):
        files = {'/firmware/gsp.bin': 'pinned'}
        directories = {'/firmware'}
        valid = '/firmware\t40755\troot\troot\t\n/firmware/gsp.bin\t100644\troot\troot\tpinned\n'
        rpm.validate_metadata(valid, files, directories)
        cases = [valid.replace('100644', '100755'), valid.replace('40755', '40700'),
                 valid.replace('root\troot', 'builder\troot'), valid.replace('pinned', 'changed'),
                 valid.splitlines()[0], valid + valid,
                 valid + '/unexpected\t100644\troot\troot\tpinned\n']
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                rpm.validate_metadata(rows, files, directories)

    def test_payload_rejects_changed_and_missing_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            payload = directory / 'gsp.bin'
            payload.write_bytes(b'firmware fixture')
            files = {'/gsp.bin': hashlib.sha256(payload.read_bytes()).hexdigest()}
            rpm.validate_payload(directory, files)
            payload.write_bytes(b'changed firmware')
            with self.assertRaises(ValueError):
                rpm.validate_payload(directory, files)
            payload.unlink()
            with self.assertRaises(ValueError):
                rpm.validate_payload(directory, files)

    def test_expected_contents_covers_both_chips_and_all_notices(self):
        files, directories = rpm.expected_contents(ROOT)
        self.assertEqual(len(files), 12)
        self.assertEqual(sum(path.endswith('.bin') for path in files), 9)
        self.assertTrue(any(path.endswith('/v67-ad102-610.43.03-four-plm.bin') for path in files))
        self.assertTrue(any(path.endswith('/v67-ga102-610.43.03.bin') for path in files))
        self.assertEqual(len(directories), 3)
