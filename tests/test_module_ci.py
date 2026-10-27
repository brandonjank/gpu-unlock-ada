# SPDX-License-Identifier: GPL-2.0-only
"""Exercise CI kernel enumeration and failure handling without loading a module."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/ci/module-build.sh"
MAKE = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["MAKE_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
module = pathlib.Path("kernel/gpu_unlock/gpu_unlock.ko")
if "clean" in args:
    module.unlink(missing_ok=True)
elif os.environ.get("FAIL_BUILD"):
    sys.exit(5)
elif not os.environ.get("OMIT_OUTPUT"):
    assert "KCFLAGS=-Werror" in args
    assert not module.exists(), "stale module was not cleaned"
    module.touch()
"""

@unittest.skipUnless(HELPER.is_file(), "CI helper is excluded from source-only archives")
@unittest.skipUnless(os.name == "posix", "Linux CI helper requires POSIX tools")
class ModuleCITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "checkout with spaces"
        self.module = self.checkout / "kernel/gpu_unlock/gpu_unlock.ko"
        self.module.parent.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, source in (("make", MAKE), ("gcc", "#!/bin/sh\nexit 0\n"),
                             ("gcc-11", "#!/bin/sh\nexit 0\n"),
                             ("gcc-13", "#!/bin/sh\nexit 0\n")):
            path = self.bin / name
            path.write_text(source)
            path.chmod(0o755)
        self.log = self.root / "make.jsonl"
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        MAKE_LOG=str(self.log), CC="gcc", MIN_KERNEL_BUILDS="1")

    def header(self, name, compiler="gcc-11"):
        path = self.root / name
        path.mkdir()
        (path / "Makefile").touch()
        (path / ".config").write_text(
            f'CONFIG_CC_VERSION_TEXT="x86_64-linux-gnu-{compiler} (distribution compiler)"\n')
        return path

    def run_helper(self, *headers, **env):
        return subprocess.run(["sh", str(HELPER), *(str(p) for p in headers)],
                              cwd=self.checkout, env=dict(self.env, **env),
                              capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_builds_every_unique_tree_cleanly_with_matching_compiler(self):
        ga = self.header("GA headers")
        hwe = self.header("HWE headers", "gcc-13")
        alias = self.root / "build-alias"
        alias.symlink_to(ga, target_is_directory=True)
        result = self.run_helper(self.root / "missing-*", alias, ga, hwe, MIN_KERNEL_BUILDS="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        for offset, (header, compiler) in enumerate(((ga, "gcc-11"), (hwe, "gcc-13"))):
            clean, build = calls[2 * offset:2 * offset + 2]
            self.assertIn("clean", clean)
            self.assertNotIn("clean", build)
            for call in (clean, build):
                self.assertIn(f"KDIR={header.resolve()}", call)
                self.assertIn(f"CC={compiler}", call)
            self.assertIn("KCFLAGS=-Werror", build)
        self.assertTrue(self.module.is_file())

    def test_alias_cannot_satisfy_required_second_kernel(self):
        ga = self.header("GA")
        alias = self.root / "same-kernel"
        alias.symlink_to(ga, target_is_directory=True)
        result = self.run_helper(ga, alias, MIN_KERNEL_BUILDS="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("built 1", result.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_failed_build_stops_without_reusing_stale_module(self):
        first, second = self.header("first"), self.header("second")
        self.module.touch()
        result = self.run_helper(first, second, FAIL_BUILD="1")
        self.assertEqual(result.returncode, 5)
        self.assertEqual(len(self.calls()), 2)
        self.assertFalse(self.module.exists())

    def test_successful_make_must_produce_module(self):
        self.module.touch()
        result = self.run_helper(self.header("GA"), OMIT_OUTPUT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.module.exists())

    def test_missing_matching_compiler_fails_before_make(self):
        result = self.run_helper(self.header("GA", "gcc-999"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required compiler unavailable: gcc-999", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_no_headers_fails(self):
        result = self.run_helper(self.root / "missing-*")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("built 0", result.stderr)

    def test_unversioned_config_uses_default_compiler(self):
        result = self.run_helper(self.header("GA", "gcc"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CC=gcc", self.calls()[1])

    def test_invalid_minimum_fails(self):
        for minimum in ("0", "-1", "invalid"):
            with self.subTest(minimum=minimum):
                result = self.run_helper(MIN_KERNEL_BUILDS=minimum)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
