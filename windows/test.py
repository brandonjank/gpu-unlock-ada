#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run Windows/WSL profile, read-only probe and retained kernel component tests."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UEFI = ROOT / "windows/uefi"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--wsl", help="cross-compile Linux component tests and run in this WSL2 distro")
    args = parser.parse_args()
    def run_binary(path):
        command = [str(path)]
        if args.wsl:
            linux_path = subprocess.check_output(["wsl", "-d", args.wsl, "--", "wslpath", "-a", str(path)], text=True).strip()
            command = ["wsl", "-d", args.wsl, "--", linux_path]
        return subprocess.run(command, capture_output=True, text=True)
    target = ["-target", "x86_64-linux-gnu"] if args.wsl else []
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "windows/tests"), "-v"], check=True)
    build = ROOT / "build/windows/tests"
    build.mkdir(parents=True, exist_ok=True)
    # Temporary outputs stay inside the workspace and never replace a USB build.
    with tempfile.TemporaryDirectory(dir=build) as d:
        assert Path(d).resolve().is_relative_to(build.resolve())
        binary = Path(d) / ("probe-tests.exe" if sys.platform == "win32" else "probe-tests")
        includes = [UEFI, UEFI / "compat", UEFI / "edk2/MdePkg/Include", UEFI / "edk2/MdePkg/Include/X64"]
        subprocess.run([args.zig, "cc", *target, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fshort-wchar",
                        "-DGU_PROBE_ONLY", "-D__KERNEL__", *(f"-I{p}" for p in includes),
                        str(ROOT / "windows/tests/test_probe.c"),
                        *(str(UEFI / (s + ".c")) for s in ["probe", "boot_tests", "checks", "ownership", "research", "sha256", "vendor/vbios_610", "vendor/gfw_eval"]),
                        "-o", str(binary)], check=True)
        result = run_binary(binary)
        print(result.stdout + result.stderr, end="")
        result.check_returncode()
        binary = Path(d) / ("blob-tests.exe" if sys.platform == "win32" else "blob-tests")
        subprocess.run([args.zig, "cc", *target, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fshort-wchar",
                        "-DGU_PROBE_ONLY", *(f"-I{p}" for p in includes),
                        str(ROOT / "windows/tests/test_blob_io.c"), str(UEFI / "format.c"), str(UEFI / "sha256.c"),
                        "-o", str(binary)], check=True)
        result = run_binary(binary)
        print(result.stdout + result.stderr, end="")
        result.check_returncode()
        spec = importlib.util.spec_from_file_location("windows_fixtures", ROOT / "windows/tests/test_windows.py")
        fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixtures)
        run = Path(d) / "fixture"
        run.mkdir()
        profile = fixtures.build.board_profile(fixtures.fixture(run))
        (Path(d) / "board_profile.h").write_text(fixtures.build.profile_header(profile))
        subprocess.run([sys.executable, str(ROOT / "windows/build.py"), "unlock", "--zig", args.zig,
                        "--run", str(run), "--output", str(Path(d) / "compile-only")], check=True)
        print("Unlock image compile-checked with synthetic data; no hardware validation.")
        binary = Path(d) / ("config-tests.exe" if sys.platform == "win32" else "config-tests")
        subprocess.run([args.zig, "cc", *target, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fshort-wchar",
                        "-Wno-misleading-indentation", f"-I{d}", *(f"-I{p}" for p in includes),
                        str(ROOT / "windows/tests/test_config.c"), str(UEFI / "port.c"), str(UEFI / "checks.c"),
                        "-o", str(binary)], check=True)
        result = run_binary(binary)
        print(result.stdout + result.stderr, end="")
        result.check_returncode()
        binary = Path(d) / ("transaction-tests.exe" if sys.platform == "win32" else "transaction-tests")
        subprocess.run([args.zig, "cc", *target, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-fshort-wchar", "-ffunction-sections", "-fdata-sections",
                        "-Wl,--gc-sections", "-DGU_PROBE_ONLY", "-DGU_UEFI_PORT", "-D__KERNEL__",
                        *(f"-I{p}" for p in includes),
                        str(ROOT / "windows/tests/test_transaction.c"), str(UEFI / "vendor/gfw_eval.c"),
                        str(UEFI / "vendor/prep_610.c"),
                        "-o", str(binary)], check=True)
        result = run_binary(binary)
        print(result.stdout + result.stderr, end="")
        result.check_returncode()
        binary = Path(d) / ("uefi-gfw-tests.exe" if sys.platform == "win32" else "uefi-gfw-tests")
        subprocess.run([args.zig, "cc", *target, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        f"-I{UEFI / 'vendor'}", str(UEFI / "vendor/gfw_eval.c"),
                        str(ROOT / "tests/test_gfw_eval.c"), "-o", str(binary)], check=True)
        result = run_binary(binary)
        print(result.stdout + result.stderr, end="")
        result.check_returncode()
        spec = importlib.util.spec_from_file_location("release", ROOT / "tests/test_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        for name, sources in release.CASES.items():
            if sys.platform == "win32" and not args.wsl and name in release.SHIMS:
                print(f"Retained Linux shim test: {name} requires --wsl DISTRO")
                continue
            binary = Path(d) / (name + (".exe" if sys.platform == "win32" else ""))
            subprocess.run([args.zig, "cc", *target, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-parameter", "-I", str(release.KERNEL), *release.SHIMS.get(name, []),
                            *(str(release.KERNEL / s) for s in sources), str(ROOT / "tests" / f"test_{name}.c"),
                            "-o", str(binary)], check=True)
            result = run_binary(binary)
            if result.returncode:
                print(result.stdout + result.stderr)
                result.check_returncode()
            print(f"Retained kernel component: {name} PASS")


if __name__ == "__main__": main()
