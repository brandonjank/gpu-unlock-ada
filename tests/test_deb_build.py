# SPDX-License-Identifier: GPL-2.0-only
"""Execute the package wrapper with fake builders; never install a package."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "packaging/build_deb.py"
VERSION = "1.1.1"
BUILDER = """#!/usr/bin/env python3
import json, os, pathlib, stat, sys, time
here = pathlib.Path.cwd()
assert stat.S_IMODE((here/'debian/clean').stat().st_mode) == 0o644
assert stat.S_IMODE((here/'debian/rules').stat().st_mode) == 0o755
if os.environ.get('BARRIER'):
    barrier=pathlib.Path(os.environ['BARRIER'])
    (barrier/str(os.getpid())).touch()
    deadline=time.monotonic()+10
    while len(list(barrier.iterdir())) < 2:
        assert time.monotonic()<deadline, 'second build never started'
        time.sleep(0.02)
if os.environ.get('FAIL_BUILD'):
    sys.exit(7)
data=json.dumps({'cwd':str(here),'inputs':os.environ['GPU_UNLOCK_INPUTS']})
for kind in ('dkms','firmware'):
    if kind=='firmware' and os.environ.get('MISSING_OUTPUT'):
        continue
    (here.parent/f'gpu-unlock-{kind}_1.1.1_all.deb').write_text(data)
(here.parent/'gpu-unlock_1.1.1_all.buildinfo').write_text('metadata')
"""


class DebianBuildTests(unittest.TestCase):
    def fixture(self, base):
        archive = base / "checkout with spaces" / "source archive.tar.xz"
        archive.parent.mkdir()
        with tarfile.open(archive, "w:xz") as tar:
            for name, data, mode in (("debian/rules", b"#!/usr/bin/make -f\n", 0o755),
                                     ("debian/clean", b"debian/tmp\n", 0o644)):
                member = tarfile.TarInfo(f"gpu-unlock-{VERSION}/{name}")
                member.mode, member.size = mode, len(data)
                tar.addfile(member, io.BytesIO(data))
        inputs = base / "inputs with spaces"
        inputs.mkdir()
        cache = base / "cache with spaces"
        cache.mkdir()
        (cache / "unrelated").write_text("keep")
        bindir = base / "bin"
        bindir.mkdir()
        builder = bindir / "dpkg-buildpackage"
        builder.write_text(BUILDER)
        builder.chmod(0o755)
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        return archive, inputs, cache, env

    def command(self, archive, inputs, cache, output):
        return [sys.executable, str(HELPER), "--archive", str(archive),
                "--inputs", str(inputs), "--build-root", str(cache),
                "--output", str(output), "--version", VERSION]

    def test_parallel_builds_preserve_modes_paths_and_unrelated_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive, inputs, cache, env = self.fixture(base)
            barrier = base / "barrier"
            barrier.mkdir()
            env["BARRIER"] = str(barrier)
            outputs = [base / f"output {i}" for i in range(2)]
            processes = [subprocess.Popen(self.command(archive, inputs, cache, output),
                                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True) for output in outputs]
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            records = [json.loads((output / f"gpu-unlock-dkms_{VERSION}_all.deb").read_text())
                       for output in outputs]
            self.assertNotEqual(records[0]["cwd"], records[1]["cwd"])
            self.assertTrue(all(record["inputs"] == str(inputs.resolve()) for record in records))
            self.assertEqual(sorted(path.name for path in cache.iterdir()), ["unrelated"])
            self.assertEqual((cache / "unrelated").read_text(), "keep")
            self.assertTrue(all(not list(output.glob(".gpu-unlock-publish-*")) for output in outputs))

    def test_failure_and_missing_output_leave_previous_products_untouched(self):
        for failure in ("FAIL_BUILD", "MISSING_OUTPUT"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                archive, inputs, cache, env = self.fixture(base)
                env[failure] = "1"
                output = base / "previous output"
                output.mkdir()
                package = output / f"gpu-unlock-dkms_{VERSION}_all.deb"
                package.write_text("previous successful build")
                result = subprocess.run(self.command(archive, inputs, cache, output),
                                        env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(package.read_text(), "previous successful build")
                self.assertEqual(sorted(path.name for path in cache.iterdir()), ["unrelated"])

    def test_archive_escape_is_rejected_and_only_private_directory_is_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive, inputs, cache, env = self.fixture(base)
            with tarfile.open(archive, "w:xz") as tar:
                member = tarfile.TarInfo("../outside")
                member.size = 1
                tar.addfile(member, io.BytesIO(b"x"))
            result = subprocess.run(self.command(archive, inputs, cache, base / "output"),
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported source archive entry", result.stderr)
            self.assertFalse((cache / "outside").exists())
            self.assertEqual(sorted(path.name for path in cache.iterdir()), ["unrelated"])

    def test_make_deb_from_spaced_checkout_and_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _, inputs, cache, env = self.fixture(base)
            checkout = base / "real checkout with spaces"
            checkout.mkdir()
            for name in ("packaging", "firmware", "debian"):
                (checkout / name).mkdir()
            shutil.copyfile(ROOT / "Makefile", checkout / "Makefile")
            shutil.copyfile(HELPER, checkout / "packaging/build_deb.py")
            (checkout / "VERSION").write_text(VERSION)
            (checkout / "debian/clean").write_text("debian/tmp\n")
            (checkout / "debian/rules").write_text("#!/usr/bin/make -f\n")
            (checkout / "debian/rules").chmod(0o755)
            (checkout / "firmware/fetch_artifacts.py").write_text("import sys\n")
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            subprocess.run(["git", "add", "."], cwd=checkout, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                            "commit", "-qm", "fixture"], cwd=checkout, check=True)
            # On a mode-less filesystem the checkout can report every file
            # executable, while Git's committed archive retains correct modes.
            for path in (checkout / "debian").iterdir():
                path.chmod(0o777)
            result = subprocess.run(["make", "deb", f"PYTHON={sys.executable}",
                                     f"INPUTS={inputs}", "DISTDIR=output with spaces",
                                     f"DEBBUILD_ROOT={cache}"], cwd=checkout, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            package = checkout / "output with spaces/deb" / f"gpu-unlock-firmware_{VERSION}_all.deb"
            self.assertTrue(package.is_file())
            self.assertEqual(sorted(path.name for path in cache.iterdir()), ["unrelated"])
