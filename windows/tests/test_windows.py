# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import tarfile
import io
import tempfile
import json
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load("windows_build", ROOT / "windows/build.py")
runner = load("tensor_runner", ROOT / "diagnostics/bench/tensor_modes_driver_runner.py")
generator = load("windows_generate_v67", ROOT / "firmware/generate_v67.py")
inspector = load("capture_inspector", ROOT / "windows/inspect_capture.py")


def boot_fixture_hash():
    data = bytearray((i * 17 + 31) & 255 for i in range(1048593))
    data[:2] = b"MZ"
    return hashlib.sha256(data).hexdigest()


class BootProfileTests(unittest.TestCase):
    def profile(self):
        return dict(esp_partition_guid="12345678-1234-5678-9abc-0123456789ab",
                    boot_manager_bytes=1048593, boot_manager_sha256="ab" * 32)

    def test_validated_pin_and_guid_byte_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pin.json"
            data = self.profile()
            data["boot_manager_sha256"] = data["boot_manager_sha256"].upper()
            p.write_text(json.dumps(data))
            parsed = build.boot_profile(p)
            self.assertEqual(parsed["boot_manager_sha256"], "ab" * 32)
            header = build.boot_profile_header(parsed)
            self.assertIn("{0x12345678,0x1234,0x5678,{0x9a,0xbc,0x01,0x23,0x45,0x67,0x89,0xab}}", header)

    def test_bad_private_pins_rejected(self):
        bad = [("esp_partition_guid", value) for value in
               ("not a guid", "00000000-0000-0000-0000-000000000000", None, 1)]
        bad += [("boot_manager_bytes", value) for value in (0, 1048575, 8388609, True, "1048593", 1048593.0)]
        bad += [("boot_manager_sha256", value) for value in ("0" * 64, "a" * 63, "a" * 65, "g" * 64, "ab\n" * 32, None)]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pin.json"
            for key, value in bad:
                with self.subTest(key=key, value=value):
                    data = self.profile(); data[key] = value
                    p.write_text(json.dumps(data))
                    with self.assertRaises((ValueError, TypeError, AttributeError)):
                        build.boot_profile(p)

    def test_duplicate_missing_unknown_fields_and_template_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pin.json"
            data = self.profile()
            variants = [json.dumps({}), "[]", json.dumps(dict(data, extra=1)),
                        json.dumps(data)[:-1] + ',"boot_manager_bytes":1048593}',
                        (ROOT / "windows/boot-profile.example.json").read_text()]
            for text in variants:
                p.write_text(text)
                with self.assertRaises(ValueError): build.boot_profile(p)

    def test_unlock_missing_pin_rejected_before_output_or_compiler(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "output"
            with patch.object(sys, "argv", ["build.py", "unlock", "--run", d, "--output", str(out)]), \
                    patch.object(build.subprocess, "run", side_effect=AssertionError("compiler called")):
                with self.assertRaises(SystemExit): build.main()
            self.assertFalse(out.exists())

    def test_probe_does_not_require_private_pin(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "probe"
            def compiler(command, **kwargs):
                self.assertNotIn("app.c", " ".join(command))
                image = out / "EFI/BOOT/BOOTX64.EFI"
                image.write_bytes(b"synthetic")
            with patch.object(sys, "argv", ["build.py", "probe", "--output", str(out)]), \
                    patch.object(build.subprocess, "run", side_effect=compiler), \
                    patch.object(build.subprocess, "check_output", return_value="test"), \
                    patch.object(build, "inspect_pe", return_value={"sha256": "test"}):
                build.main()
            self.assertFalse((out / "boot_profile.h").exists())


def fixture(directory):
    run = Path(directory)
    config = [0] * 64
    config[0], config[1], config[2], config[4], config[11] = 0x268410DE, 2, 0x030000A1, 0x80000000, 0x123410DE
    files = {"config": struct.pack("<64I", *config), "rom": b"\x55\xaa" + bytes(510),
             "prom": b"\x55\xaa" + bytes(1048574)}
    values = dict(segment=0, bus=2, device=0, function=0, bar_base=0x80000000,
                  bar_size=0x1000000, bar_granularity=32, chip=0x192000A1, vram_mib=24576,
                  rom_bytes=512, wpr2_hi=0, ss0=0x44023025, ss1=7)
    for key, data in files.items():
        (run / (key.upper() + ".BIN")).write_bytes(data)
        values[key + "_sha256"] = hashlib.sha256(data).hexdigest()
    report = ("PROBE ONLY:\n" + "\n".join(f"PROFILE {k}={v}" for k, v in values.items()) +
              "\nPROFILE complete=1\nPROBE FINAL status=0 GPU writes=0 DMA maps=0\n")
    (run / "REPORT.TXT").write_text(report)
    return run


class ProfileTests(unittest.TestCase):
    def test_observed_ss1_three_accepted_and_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            run = fixture(d)
            report = run / "REPORT.TXT"
            report.write_text(report.read_text().replace("ss1=7", "ss1=3"))
            profile = build.board_profile(run)
            self.assertEqual(profile["ss1"], 3)
            self.assertIn("GU_COLD_SS1 0x3U", build.profile_header(profile))

    def test_enabled_or_unreadable_ss1_rejected(self):
        for value in (8, 15, 0xFFFFFFFF, 0xBADF5620):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as d:
                run = fixture(d)
                report = run / "REPORT.TXT"
                report.write_text(report.read_text().replace("ss1=7", f"ss1={value}"))
                with self.assertRaises(ValueError): build.board_profile(run)

    def test_non_default_bus_and_board_pins(self):
        with tempfile.TemporaryDirectory() as d:
            profile = build.board_profile(fixture(d))
            self.assertEqual(profile["bus"], 2)
            self.assertEqual(profile["board_subsystem"], 0x123410DE)
            header = build.profile_header(profile)
            self.assertIn("GU_BOARD_CHIP 0x192000a1U", header)
            self.assertIn("GU_PROM_SHA256", header)

    def test_tampered_missing_or_incomplete_capture_rejected(self):
        for mode in ("tamper", "missing", "incomplete", "duplicate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                run = fixture(d)
                if mode == "tamper": (run / "PROM.BIN").write_bytes(bytes(1048576))
                if mode == "missing": (run / "ROM.BIN").unlink()
                p = run / "REPORT.TXT"
                if mode == "incomplete": p.write_text(p.read_text().replace("PROFILE complete=1", ""))
                if mode == "duplicate": p.write_text(p.read_text() + "PROFILE bus=1\n")
                with self.assertRaises((OSError, ValueError)):
                    build.board_profile(run)

    def test_wrong_chip_warm_gpu_and_bad_bar_rejected(self):
        for old, new in [("chip=421527713", "chip=422576289"), ("wpr2_hi=0", "wpr2_hi=256"),
                         ("bar_base=2147483648", "bar_base=2164260864")]:
            with self.subTest(old=old), tempfile.TemporaryDirectory() as d:
                run = fixture(d)
                p = run / "REPORT.TXT"
                self.assertIn(old, p.read_text())
                p.write_text(p.read_text().replace(old, new))
                with self.assertRaises(ValueError): build.board_profile(run)

    def test_host_executable_rejected(self):
        with self.assertRaises((ValueError, struct.error)):
            build.inspect_pe(bytes(512))


class CaptureTests(unittest.TestCase):
    def test_hash_verification_and_matching_prom_copies(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            data = b"\x55\xaa" + bytes(510)
            lines = []
            for name in ("PROM.BIN", "PROM2.BIN"):
                (run/name).write_bytes(data)
                lines.append(f"CAPTURE file={name} bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()} verified=1")
            (run/"REPORT.TXT").write_text("\n".join(lines))
            result = inspector.inspect(run)
            self.assertTrue(result["prom_repeat_identical"])
            self.assertFalse(result["full_spi_flash_backup_established"])
            (run/"PROM2.BIN").write_bytes(bytes(512))
            with self.assertRaises(ValueError): inspector.inspect(run)

    def test_register_transport_status_preserved_and_bounds_checked(self):
        data = struct.pack("<4I", 0x31525547, 1, 1, 16) + struct.pack("<IIQ", 0x823818, 0xFFFFFFFF, 0x8000000000000007)
        self.assertEqual(inspector.registers(data)[0]["status"], "0x8000000000000007")
        with self.assertRaises(ValueError): inspector.registers(data[:-1])


class RunnerTests(unittest.TestCase):
    def test_windows_driver_calling_convention_and_search_path(self):
        with patch.object(runner.os, "name", "nt"), patch.object(runner.C, "WinDLL", create=True) as loader:
            runner.cuda_library()
            loader.assert_called_once_with("nvcuda.dll", winmode=0x800)

    def test_wsl_projected_driver_fallback(self):
        with patch.object(runner.os, "name", "posix"), patch.object(runner.platform, "release", return_value="6.18-microsoft-standard-WSL2"), patch.object(runner.C, "CDLL", side_effect=[OSError("missing"), "loaded"]) as loader:
            self.assertEqual(runner.cuda_library(), "loaded")
            self.assertEqual(loader.call_args.args[0], "/usr/lib/wsl/lib/libcuda.so.1")

    @patch.object(runner, "nvidia_smi", return_value="nvidia-smi")
    def test_identity_and_power_checks(self, smi):
        for output, allowed, passes in [
            ("GPU-abc, RTX 4090, 02:00.0, 616.56, 450", False, True),
            ("GPU-wrong, RTX 4090, 02:00.0, 616.56, 450", False, False),
            ("GPU-abc, RTX 4090, 02:00.0, 616.56, 400", False, False),
            ("GPU-abc, RTX 4090, 02:00.0, 616.56, [N/A]", False, False),
            ("GPU-abc, RTX 4090, 02:00.0, 616.56, [N/A]", True, True),
            ("GPU-abc, RTX 4090, 02:00.0, 616.56, nan", True, False),
        ]:
            with self.subTest(output=output, allowed=allowed), patch.object(runner.subprocess, "run") as proc:
                proc.return_value.stdout = output
                if passes:
                    _, verified = runner.gpu_info("GPU-abc", 450, allowed)
                    self.assertEqual(verified, "[N/A]" not in output)
                else:
                    with self.assertRaises(ValueError): runner.gpu_info("GPU-abc", 450, allowed)


class ZstdTests(unittest.TestCase):
    @unittest.skipIf(sys.version_info < (3, 14), "native zstd requires Python 3.14")
    def test_extract_zstd_package_without_external_executable(self):
        with tempfile.TemporaryDirectory() as d:
            package = Path(d) / "fixture.tar.zst"
            with tarfile.open(package, "w:zst") as archive:
                entry = tarfile.TarInfo(".PKGINFO")
                data = b"pkgver = 610.43.03-1\n"
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            with patch.object(generator.subprocess, "Popen", side_effect=AssertionError("external zstd executed")):
                self.assertEqual(generator.extract_member(package, ".PKGINFO"), data)


if __name__ == "__main__": unittest.main()
