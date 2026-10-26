# SPDX-License-Identifier: GPL-2.0-only
"""Check published evidence integrity, arithmetic and privacy boundaries."""
import hashlib
import json
from pathlib import Path
import re
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

    def test_windows_evidence_manifest_and_privacy(self):
        directory = ROOT / "docs/evidence/rtx4090-windows-2026-10-24"
        expected = {"README.md", "provenance.json", "run08-diagnostics.txt",
                    "run09-transaction.txt", "baseline-windows.json", "baseline-wsl2.json",
                    "unlock-v10-run09-windows.json", "unlock-v10-run09-wsl2.json"}
        listed = set()
        for line in (directory / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            self.assertIn(name, expected)
            self.assertNotIn(name, listed)
            listed.add(name)
            data = (directory / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)
            text = data.decode("utf-8")
            # UUIDs, Windows/WSL host paths and PCI locations are unnecessary
            # for this public evidence. Firmware/image binaries stay private.
            self.assertIsNone(re.search(r"(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", text), name)
            self.assertIsNone(re.search(r"(?i)\b[A-Z]:[\\/]|/home/|/mnt/[a-z]/", text), name)
            self.assertIsNone(re.search(r"(?i)\b(?:[0-9a-f]{4,8}:)?[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\b", text), name)
        self.assertEqual(listed, expected)
        self.assertEqual({p.name for p in directory.iterdir()}, expected | {"SHA256SUMS"})

    def test_windows_workload_evidence_arithmetic(self):
        directory = ROOT / "docs/evidence/rtx4090-windows-2026-10-24"
        reports = [json.loads((directory / name).read_text()) for name in
                   ("baseline-windows.json", "baseline-wsl2.json",
                    "unlock-v10-run09-windows.json", "unlock-v10-run09-wsl2.json")]
        settings = ("gpu", "cubin_sha256", "iters", "reps", "blocks", "threads", "warps", "chains")
        for report in reports:
            self.assertEqual(report["gpu"], {"name": "NVIDIA GeForce RTX 4090",
                                            "driver": "616.56", "power_limit_watts": 450.0})
            for key in settings:
                self.assertEqual(report[key], reports[0][key], key)
            self.assertTrue(report["power_limit_verified"])
            self.assertEqual(report["expected_power_limit_watts"], 450.0)
            self.assertEqual(report["warps"] * 32, report["blocks"] * report["threads"])
            self.assertEqual(set(report["modes"]), {"f16_f32", "bf16_f32", "tf32", "u4_s32"})
            for mode in report["modes"].values():
                self.assertEqual(mode["mismatches"], 0)
                self.assertEqual(mode["cells_checked"], report["blocks"] * report["threads"])
                self.assertEqual(mode["expected_cell"], 4 * report["chains"] * report["iters"] * mode["k"])
                self.assertEqual(len(mode["times_ms"]), report["reps"])
                self.assertEqual(len(mode["rates_Top_per_s"]), report["reps"])
                ops = report["warps"] * report["iters"] * report["chains"] * 16 * 8 * mode["k"] * 2
                for ms, rate in zip(mode["times_ms"], mode["rates_Top_per_s"]):
                    self.assertGreater(ms, 0)
                    self.assertAlmostEqual(rate, ops / (ms * 1e9), places=8)
                self.assertEqual(mode["best_Top_per_s"], max(mode["rates_Top_per_s"]))
        total = sum(m["cells_checked"] for report in reports[2:] for m in report["modes"].values())
        self.assertEqual(total, 2162688)
        provenance = json.loads((directory / "provenance.json").read_text())
        self.assertEqual(provenance["total_unlocked_output_cells_checked"], total)
        self.assertFalse(provenance["controlled_speedup_established"])
        self.assertFalse(provenance["cold_boot_persistence_tested"])
        self.assertFalse(provenance["post_windows_driver_register_readback_performed"])
