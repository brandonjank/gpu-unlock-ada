#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check delivered firmware RPMs, then rebuild with deliberately bad staging modes.

Disposable Fedora CI only. Extract payloads privately; never install a package.
"""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def expected_contents(root):
    manifest = json.loads((root / 'firmware/artifacts-610.43.03.json').read_text())
    binary = manifest['source_artifacts'][2]
    firmware = dict(manifest['derived_assets'])
    firmware['gsp_ga10x.bin'] = binary['firmware'][0]['sha256']
    for key in ('generated_payload', 'generated_ad102_payload'):
        item = manifest[key]
        firmware[item['filename']] = item['sha256']
    fwdir = '/usr/lib/firmware/gpu-unlock/610.43.03'
    licensedir = '/usr/share/licenses/gpu-unlock-firmware'
    files = {f'{fwdir}/{name}': digest for name, digest in firmware.items()}
    files.update({f'{licensedir}/NVIDIA-LICENSE': binary['notice']['sha256'],
                  f'{licensedir}/NOTICE.md': sha256(root / 'firmware/NOTICE.md'),
                  f'{licensedir}/GPL-2.0.txt': sha256(root / 'licenses/GPL-2.0.txt')})
    return files, {'/usr/lib/firmware/gpu-unlock', fwdir, licensedir}


def validate_metadata(rows, files, directories):
    seen = set()
    for line in rows.splitlines():
        name, mode, user, group, digest = line.split('\t')
        if name in seen or name not in files.keys() | directories:
            raise ValueError(f'unexpected or duplicate RPM entry: {name}')
        seen.add(name)
        expected_mode = stat.S_IFDIR | 0o755 if name in directories else stat.S_IFREG | 0o644
        if int(mode, 8) != expected_mode or (user, group) != ('root', 'root'):
            raise ValueError(f'incorrect RPM permissions/ownership: {name}: {mode} {user}:{group}')
        if name in files and digest != files[name]:
            raise ValueError(f'RPM digest differs from pinned input: {name}')
    missing = (files.keys() | directories) - seen
    if missing:
        raise ValueError(f'missing RPM entries: {sorted(missing)}')


def validate_payload(directory, files):
    for name, digest in files.items():
        path = directory / name.lstrip('/')
        if path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise ValueError(f'RPM payload differs from pinned input: {name}')


def check_package(package):
    identity = subprocess.check_output(['rpm', '-qp', '--qf', '%{ARCH}\t%{FILEDIGESTALGO}',
                                        str(package)], text=True)
    if identity != 'noarch\t8':
        raise ValueError(f'expected noarch package with SHA-256 digests: {identity}')
    files, directories = expected_contents(ROOT)
    rows = subprocess.check_output(['rpm', '-qp', '--qf',
        '[%{FILENAMES}\t%{FILEMODES:octal}\t%{FILEUSERNAME}\t%{FILEGROUPNAME}\t%{FILEDIGESTS}\n]',
        str(package)], text=True)
    # Validate the exact path set and regular-file/directory types before extraction.
    validate_metadata(rows, files, directories)
    with tempfile.TemporaryDirectory(prefix='gpu-unlock-rpm-payload-') as name:
        with subprocess.Popen(['rpm2cpio', str(package)], stdout=subprocess.PIPE) as archive:
            subprocess.run(['cpio', '--extract', '--make-directories', '--quiet',
                            '--no-absolute-filenames', '--no-preserve-owner'],
                           stdin=archive.stdout, cwd=name, check=True)
            archive.stdout.close()
            if archive.wait() != 0:
                raise ValueError('rpm2cpio failed')
        validate_payload(Path(name), files)
    print(f'Checked {package.name}: noarch; 0644 files, 0755 directories, root:root; '
          f'{len(files)} metadata and extracted-payload SHA-256 checks passed.', flush=True)


def one_firmware_package(top):
    packages = list(top.glob('RPMS/noarch/gpu-unlock-firmware-*.rpm'))
    if len(packages) != 1:
        raise ValueError(f'expected exactly one firmware RPM under {top}')
    return packages[0].resolve()


def main():
    top = ROOT / 'build/rpm'
    check_package(one_firmware_package(top))
    spec = (ROOT / 'packaging/rpm/gpu-unlock.spec').read_text()
    marker = '\n%files dkms\n'
    if spec.count(marker) != 1:
        raise ValueError('cannot locate end of RPM install section')
    # Keep the real source, generators and standard RPM postprocessing. Change
    # staging modes only; the firmware manifest must repair the delivered modes.
    paths = ('%{buildroot}%{_prefix}/lib/firmware/gpu-unlock '
             '%{buildroot}%{_defaultlicensedir}/gpu-unlock-firmware')
    fixture = (f'\n# CI-only simulation of a filesystem ignoring install -m644.\n'
               f'find {paths} -type f -exec chmod 0755 {{}} +\n'
               f'find {paths} -type d -exec chmod 0700 {{}} +\n')
    with tempfile.TemporaryDirectory(prefix='gpu-unlock-rpm-modes-') as name:
        temporary = Path(name)
        variant = temporary / 'permissions.spec'
        variant.write_text(spec.replace(marker, fixture + marker))
        # The normal package build already ran %check. This build changes only
        # fixture modes and reuses its verified inputs, without replacing outputs.
        subprocess.run(['rpmbuild', '-bb', '--nocheck', '--define', f'_topdir {temporary}',
                        '--define', f'_sourcedir {top / "SOURCES"}', str(variant)], check=True)
        check_package(one_firmware_package(temporary))


if __name__ == '__main__':
    main()
