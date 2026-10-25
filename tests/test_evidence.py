# SPDX-License-Identifier: GPL-2.0-only
"""Keep attributed upstream evidence byte-exact in clones and source archives."""
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class EvidenceTests(unittest.TestCase):
    def test_published_4090_evidence_manifests(self):
        for name in ("rtx4090-610.57.04", "rtx4090-48g-modded"):
            directory = ROOT / "docs/evidence" / name
            lines = (directory / "SHA256SUMS").read_text().splitlines()
            self.assertEqual(len(lines), 17)
            for line in lines:
                digest, name = line.split(maxsplit=1)
                path = (directory / name.lstrip("*")).resolve()
                self.assertTrue(path.is_relative_to(directory.resolve()))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, str(path))
