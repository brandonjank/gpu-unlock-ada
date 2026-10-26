#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build committed Debian sources on a filesystem that preserves Unix modes.

Adapts Zagitta/gpu-unlock PR #154, 16d9a6bfa6de607742e59f90b8fa0fd5c18dce9f.
Each invocation owns one temporary directory; the caller's cache is never removed.
"""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile


def extract_source(archive, destination, version):
    prefix = f"gpu-unlock-{version}"
    with tarfile.open(archive) as source:
        for member in source:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or not name.parts or
                    name.parts[0] != prefix or not (member.isdir() or member.isfile())):
                raise ValueError(f"unsupported source archive entry: {member.name}")
            target = destination.joinpath(*name.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    project = destination / prefix
    if not (project / "debian/rules").is_file():
        raise ValueError("source archive has no Debian build rules")
    return project


def build(archive, inputs, output, build_root, version):
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+~:-]*", version):
        raise ValueError("invalid package version")
    archive, inputs = archive.resolve(strict=True), inputs.resolve(strict=True)
    if not inputs.is_dir():
        raise ValueError("inputs must be a directory")
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-", dir=build_root.resolve()) as name:
        work = Path(name)
        # Test behavior rather than guessing from a filesystem's name. DrvFS
        # without metadata and FAT can report every metadata file executable.
        probe = work / ".unix-mode-check"
        probe.touch()
        for mode in (0o600, 0o644):
            probe.chmod(mode)
            if stat.S_IMODE(probe.stat().st_mode) != mode:
                raise ValueError("DEBBUILD_ROOT must preserve Unix file modes; use a Linux home/cache filesystem")
        project = extract_source(archive, work, version)
        print(f"Debian build directory: {project}", flush=True)
        env = dict(os.environ, GPU_UNLOCK_INPUTS=str(inputs))
        subprocess.run(["dpkg-buildpackage", "-us", "-uc"], cwd=project, env=env, check=True)
        required = [work / f"gpu-unlock-{kind}_{version}_all.deb" for kind in ("dkms", "firmware")]
        if any(not item.is_file() or item.is_symlink() for item in required):
            raise ValueError("build did not produce both expected Debian packages")
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        # Publish only complete build products. Preserve unrelated files and
        # previous successful packages when the build fails.
        with tempfile.TemporaryDirectory(prefix=".gpu-unlock-publish-", dir=output) as stage:
            for item in work.glob("gpu-unlock*_*.*"):
                if not item.is_file() or item.is_symlink():
                    continue
                temporary = Path(stage) / item.name
                shutil.copyfile(item, temporary)
                os.replace(temporary, output / item.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        build(args.archive, args.inputs, args.output, args.build_root, args.version)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f"Debian build failed: {error}\n")


if __name__ == "__main__":
    main()
