# SPDX-License-Identifier: GPL-2.0-only
"""Exercise RPM path handling and cleanup without installing or building GPU code."""
import hashlib
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
HELPER = ROOT / 'packaging/build_rpm.py'
VERSION = '1.1.1'
BUILDER = '''#!/usr/bin/env python3
import json, os, pathlib, sys, time
top = pathlib.Path(sys.argv[sys.argv.index('--define')+1].removeprefix('_topdir '))
assert pathlib.Path.cwd() == top
assert 'committed-spec' in pathlib.Path(sys.argv[-1]).read_text()
assert (top/'SOURCES/input archive.tar.xz').is_symlink()
assert (top/'SOURCES/input archive.tar.xz').read_bytes() == b'pinned fixture'
if os.environ.get('BARRIER'):
    barrier=pathlib.Path(os.environ['BARRIER'])
    (barrier/str(os.getpid())).touch()
    deadline=time.monotonic()+10
    while len(list(barrier.iterdir())) < 2:
        assert time.monotonic()<deadline, 'second build never started'
        time.sleep(0.02)
if os.environ.get('FAIL_BUILD'):
    sys.exit(7)
record=json.dumps({'cwd':str(top), 'input':str((top/'SOURCES/input archive.tar.xz').resolve())})
for kind in ('dkms', 'firmware'):
    if kind == 'firmware' and os.environ.get('MISSING_OUTPUT'):
        continue
    target=top/f'RPMS/noarch/gpu-unlock-{kind}-1.1.1-1.test.noarch.rpm'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(record)
source=top/'SRPMS/gpu-unlock-1.1.1-1.test.nosrc.rpm'
source.parent.mkdir()
source.write_text(record)
'''


class RpmBuildTests(unittest.TestCase):
    def fixture(self, base):
        archive = base / 'source archive.tar.xz'
        manifest = {'source_artifacts': [{'filename': 'input archive.tar.xz',
                    'sha256': hashlib.sha256(b'pinned fixture').hexdigest()}]}
        with tarfile.open(archive, 'w:xz') as tar:
            for name, data in [('packaging/rpm/gpu-unlock.spec', b'# committed-spec\n'),
                               ('firmware/artifacts-610.43.03.json', json.dumps(manifest).encode())]:
                member = tarfile.TarInfo(f'gpu-unlock-{VERSION}/{name}')
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        inputs = base / 'inputs with spaces'
        inputs.mkdir()
        (inputs / 'input archive.tar.xz').write_bytes(b'pinned fixture')
        cache = base / 'cache'
        cache.mkdir()
        (cache / 'unrelated').write_text('keep')
        bindir = base / 'bin'
        bindir.mkdir()
        builder = bindir / 'rpmbuild'
        builder.write_text(BUILDER)
        builder.chmod(0o755)
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        return archive, inputs, cache, env

    def command(self, archive, inputs, cache, output):
        return [sys.executable, str(HELPER), '--archive', str(archive), '--inputs', str(inputs),
                '--build-root', str(cache), '--output', str(output), '--version', VERSION]

    def test_parallel_builds_use_private_directories_and_preserve_unrelated_files(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive, inputs, cache, env = self.fixture(base)
            barrier = base / 'barrier'
            barrier.mkdir()
            env['BARRIER'] = str(barrier)
            outputs = [base / f'output with spaces {i}' for i in range(2)]
            processes = [subprocess.Popen(self.command(archive, inputs, cache, output), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for output in outputs]
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            records = [json.loads(next((output / 'RPMS/noarch').glob('*dkms*')).read_text())
                       for output in outputs]
            self.assertNotEqual(records[0]['cwd'], records[1]['cwd'])
            self.assertTrue(all(record['input'] == str(inputs / 'input archive.tar.xz') for record in records))
            self.assertEqual(sorted(path.name for path in cache.iterdir()), ['unrelated'])
            self.assertTrue(all(len(list(output.rglob('*.rpm'))) == 3 for output in outputs))
            self.assertTrue(all(not list(output.glob('.gpu-unlock-publish-*')) for output in outputs))

    def test_failures_preserve_previous_packages_and_clean_only_private_directory(self):
        for failure in ('FAIL_BUILD', 'MISSING_OUTPUT', 'BAD_INPUT'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as name:
                base = Path(name)
                archive, inputs, cache, env = self.fixture(base)
                env[failure] = '1'
                if failure == 'BAD_INPUT':
                    (inputs / 'input archive.tar.xz').write_bytes(b'changed input')
                output = base / 'previous output'
                previous = output / 'RPMS/noarch/gpu-unlock-dkms-1.1.1-1.test.noarch.rpm'
                previous.parent.mkdir(parents=True)
                previous.write_text('previous successful build')
                result = subprocess.run(self.command(archive, inputs, cache, output), env=env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(previous.read_text(), 'previous successful build')
                self.assertEqual(sorted(path.name for path in cache.iterdir()), ['unrelated'])

    def test_whitespace_in_private_rpm_root_is_rejected_clearly(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive, inputs, _, env = self.fixture(base)
            cache = base / 'unsupported build root'
            result = subprocess.run(self.command(archive, inputs, cache, base / 'output'), env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('RPMBUILD_ROOT', result.stderr)
            self.assertIn('without whitespace', result.stderr)
            self.assertFalse(cache.exists())

    def test_make_rpm_and_install_from_spaced_paths_uses_committed_spec(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive, inputs, cache, env = self.fixture(base)
            checkout = base / 'checkout with spaces'
            checkout.mkdir()
            for directory in ('packaging', 'firmware'):
                (checkout / directory).mkdir()
            shutil.copyfile(ROOT / 'Makefile', checkout / 'Makefile')
            shutil.copyfile(HELPER, checkout / 'packaging/build_rpm.py')
            with tarfile.open(archive) as tar:
                for member in tar:
                    relative = Path(member.name).relative_to(f'gpu-unlock-{VERSION}')
                    target = checkout / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(tar.extractfile(member).read())
            (checkout / 'VERSION').write_text(VERSION)
            (checkout / 'firmware/fetch_artifacts.py').write_text('import sys\n')
            subprocess.run(['git', 'init', '-q'], cwd=checkout, check=True)
            subprocess.run(['git', 'add', '.'], cwd=checkout, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '-qm', 'fixture'], cwd=checkout, check=True)
            (checkout / 'packaging/rpm/gpu-unlock.spec').write_text('# uncommitted spec must not build\n')
            # Capture the actual install argv instead of running sudo or DNF.
            sudo = base / 'bin/sudo'
            sudo.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                            'with open(os.environ["INSTALL_LOG"], "a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n')
            sudo.chmod(0o755)
            log = base / 'install.jsonl'
            env['INSTALL_LOG'] = str(log)
            result = subprocess.run(['make', 'install-rpm', f'PYTHON={sys.executable}',
                                     f'INPUTS={inputs}', 'DISTDIR=output with spaces',
                                     f'RPMBUILD_ROOT={cache}'], cwd=checkout, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            install = json.loads(log.read_text().splitlines()[-1])
            self.assertEqual(install[:3], ['dnf', 'install', '-y'])
            self.assertEqual(len(install[3:]), 2)
            self.assertTrue(all((checkout / item).is_file() for item in install[3:]))
            self.assertTrue(all('output with spaces/' in item for item in install[3:]))
