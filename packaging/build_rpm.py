#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build committed RPM sources privately on a Linux filesystem, then publish results."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile


def archive_file(source, name):
    member = source.getmember(name)
    if not member.isfile():
        raise ValueError(f'expected a regular source archive file: {name}')
    with source.extractfile(member) as stream:
        return stream.read()


def build(archive, inputs, output, build_root, version, *, spec_transform=None, check=True):
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~]*', version):
        raise ValueError('invalid RPM version')
    archive, inputs = archive.resolve(strict=True), inputs.resolve(strict=True)
    if not inputs.is_dir():
        raise ValueError('inputs must be a directory')
    build_root = build_root.resolve()
    # RPM-generated shell scripts do not consistently quote their own _topdir.
    # Checkout, input and output paths can contain spaces; this private root cannot.
    if any(character.isspace() for character in str(build_root)):
        raise ValueError('RPMBUILD_ROOT must be a Linux filesystem path without whitespace')
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-', dir=build_root) as name:
        work = Path(name)
        probe = work / '.unix-mode-check'
        probe.touch()
        for mode in (0o600, 0o644):
            probe.chmod(mode)
            if stat.S_IMODE(probe.stat().st_mode) != mode:
                raise ValueError('RPMBUILD_ROOT must preserve Unix file modes; use a Linux home/cache filesystem')
        for directory in ('SOURCES', 'SPECS'):
            (work / directory).mkdir()
        prefix = f'gpu-unlock-{version}'
        with tarfile.open(archive) as source:
            spec = archive_file(source, f'{prefix}/packaging/rpm/gpu-unlock.spec').decode()
            manifest = json.loads(archive_file(source, f'{prefix}/firmware/artifacts-610.43.03.json'))
        if spec_transform is not None:
            spec = spec_transform(spec)
        spec_path = work / 'SPECS/gpu-unlock.spec'
        spec_path.write_text(spec)
        shutil.copyfile(archive, work / 'SOURCES' / f'{prefix}.tar.xz')
        for item in manifest['source_artifacts']:
            filename = item.get('filename')
            if not filename:
                continue
            if Path(filename).name != filename or filename in ('.', '..'):
                raise ValueError(f'invalid input filename: {filename}')
            path = (inputs / filename).resolve(strict=True)
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError(f'input SHA-256 mismatch: {filename}')
            (work / 'SOURCES' / filename).symlink_to(path)
        print(f'RPM build directory: {work}', flush=True)
        command = ['rpmbuild', '-ba', '--define', f'_topdir {work}']
        if not check:
            command.append('--nocheck')
        subprocess.run(command + [str(spec_path)], cwd=work, check=True)
        products = []
        for pattern in (f'RPMS/noarch/gpu-unlock-dkms-{version}-*.noarch.rpm',
                        f'RPMS/noarch/gpu-unlock-firmware-{version}-*.noarch.rpm',
                        f'SRPMS/gpu-unlock-{version}-*.nosrc.rpm'):
            matches = list(work.glob(pattern))
            if len(matches) != 1 or not matches[0].is_file() or matches[0].is_symlink():
                raise ValueError(f'build did not produce exactly one expected package: {pattern}')
            products.append(matches[0])
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        # Build failures leave previous products untouched. Publish only completed
        # packages, without deleting any caller-supplied cache or output directory.
        with tempfile.TemporaryDirectory(prefix='.gpu-unlock-publish-', dir=output) as stage:
            for product in products:
                relative = product.relative_to(work)
                staged = Path(stage) / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(product, staged)
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                staged.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'inputs', 'output', 'build-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        build(args.archive, args.inputs, args.output, args.build_root, args.version)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f'RPM build failed: {error}\n')


if __name__ == '__main__':
    main()
