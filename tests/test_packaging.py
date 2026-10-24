# SPDX-License-Identifier: GPL-2.0-only
"""Check the generated payload and the shared install layout."""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(os.environ.get("GPU_UNLOCK_ASSETS", "/nonexistent"))
sys.path.insert(0, str(ROOT / "firmware"))
import generate_v67  # noqa: E402


class PackageTests(unittest.TestCase):
    def test_debian_rebuilds_on_install_and_removal_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "update-initramfs"
            wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$REBUILD_LOG"\n')
            wrapper.chmod(0o755)
            log = root / "rebuild.log"
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}", REBUILD_LOG=str(log))
            for script, action in (("postinst", "configure"), ("postrm", "upgrade"), ("postrm", "remove")):
                subprocess.run(["sh", str(ROOT / f"debian/gpu-unlock-dkms.{script}"), action],
                               env=env, check=True)
            self.assertEqual(log.read_text().splitlines(), ["-u -k all", "-u -k all"])

    def test_arch_recipe_ships_both_early_load_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gpu-unlock").symlink_to(ROOT, target_is_directory=True)
            env = dict(os.environ, startdir=str(ROOT / "packaging/arch"),
                       pkgdir=str(root / "package"), pkgname="gpu-unlock-dkms")
            subprocess.run(["bash", "-c", 'set -e; source "$1"; package_gpu-unlock-dkms',
                            "arch-layout", str(ROOT / "packaging/arch/PKGBUILD")],
                           cwd=root, env=env, check=True, capture_output=True, text=True)
            package = root / "package"
            for path, source in (
                ("usr/lib/dracut/dracut.conf.d/gpu-unlock.conf", "dracut.conf"),
                ("etc/mkinitcpio.conf.d/zz-gpu-unlock.conf", "mkinitcpio.conf"),
            ):
                self.assertEqual((package / path).read_bytes(),
                                 (ROOT / "packaging/boot" / source).read_bytes())

    def test_debian_recipe_and_file_selection_ship_both_configs(self):
        # Run the real install recipe in a disposable source layout, with
        # fixture assets. Verify the binary package's own file selection too.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("Makefile", "VERSION", "README.md", "kernel", "packaging", "licenses", "debian", "firmware"):
                source = ROOT / path
                if source.is_dir():
                    shutil.copytree(source, root / path)
                else:
                    shutil.copy2(source, root / path)
            assets = root / "assets"
            assets.mkdir()
            for name in set(self.manifest()["derived_assets"]) | {"gsp_ga10x.bin", "v67-ga102-610.43.03.bin", "v67-ad102-610.43.03-four-plm.bin", "NVIDIA-LICENSE"}:
                (assets / name).write_bytes(b"fixture")
            # The staging target does not use dpkg's version metadata. Let a
            # minimal host omit that include; native CI builds use real dpkg.
            result = subprocess.run(["make", "-s", "-f", "debian/rules",
                                     "--eval=/usr/share/dpkg/pkg-info.mk: ;", "override_dh_auto_install",
                                     f"ASSETS={assets}"], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            stage = root / "debian/tmp"
            selectors = (root / "debian/gpu-unlock-dkms.install").read_text().splitlines()
            for path in ("usr/lib/dracut/dracut.conf.d/gpu-unlock.conf",
                         "usr/share/initramfs-tools/modules.d/gpu-unlock.conf"):
                self.assertTrue((stage / path).is_file(), path)
                self.assertTrue(any(Path(selector) in Path(path).parents for selector in selectors), path)

    @unittest.skipUnless((ASSETS / "booter_load_ad102.bin").is_file(),
                         "set GPU_UNLOCK_ASSETS to the pinned GA/Ada asset directory")
    def test_firmware_package_contains_pinned_ada_assets_and_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["make", "-s", f"DESTDIR={directory}", f"ASSETS={ASSETS}",
                            "install-firmware"], cwd=ROOT, check=True)
            installed = Path(directory) / "usr/lib/firmware/gpu-unlock/610.43.03"
            manifest = json.loads((ROOT / "firmware/ada-610.43.03.json").read_text())
            for name, digest in manifest["derived_assets"].items():
                self.assertEqual(hashlib.sha256((installed / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(hashlib.sha256((installed / "gsp_ga10x.bin").read_bytes()).hexdigest(),
                             manifest["shared_gsp"]["sha256"])
            payload_pin = self.manifest()["generated_ad102_payload"]
            self.assertEqual(hashlib.sha256((installed / payload_pin["filename"]).read_bytes()).hexdigest(),
                             payload_pin["sha256"])

    def test_v67_payload_matches_pin(self):
        digest = hashlib.sha256(generate_v67.build_payload()).hexdigest()
        self.assertEqual(digest, generate_v67.PAYLOAD_SHA256)
        self.assertEqual(digest, self.manifest()["generated_payload"]["sha256"])

    def test_install_uses_standard_paths(self):
        version = (ROOT / "VERSION").read_text().strip()
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["make", "-s", f"DESTDIR={directory}", "install-dkms",
                            "install-mkinitcpio", "install-initramfs-tools",
                            "install-dracut"],
                           cwd=ROOT, check=True)
            root = Path(directory)
            paths = {path.relative_to(root).as_posix() for path in root.rglob("*")
                     if path.is_file()}
            for expected in (f"usr/src/gpu-unlock-{version}/dkms.conf",
                             f"usr/src/gpu-unlock-{version}/main.c",
                             "etc/mkinitcpio.conf.d/zz-gpu-unlock.conf",
                             "usr/share/initramfs-tools/modules.d/gpu-unlock.conf",
                             "usr/lib/dracut/dracut.conf.d/gpu-unlock.conf",
                             "usr/share/doc/gpu-unlock/README.md"):
                self.assertIn(expected, paths)
            self.assertFalse(any(path.endswith(".mod.c") for path in paths))
            # Another package's "softdep nvidia" line would silently win over
            # ours (kmod honours only the first), so the order comes from the
            # initramfs instead: gpu_unlock goes right before nvidia.
            self.assertFalse(any("modprobe.d" in path for path in paths))
            dropin = root / "etc/mkinitcpio.conf.d/zz-gpu-unlock.conf"
            for before, after in (("zfs nvidia nvidia_drm", "zfs gpu_unlock nvidia nvidia_drm"),
                                  ("zfs", "zfs gpu_unlock"),
                                  ("zfs gpu_unlock? nvidia", "zfs gpu_unlock nvidia")):
                result = subprocess.run(["bash", "-c", f"MODULES=({before}); . {dropin}; echo ${{MODULES[*]}}"],
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout.strip(), after)

    def test_pkgbuild_pins_match_manifest(self):
        manifest = json.loads((ROOT / "firmware/artifacts-610.43.03.json").read_text())
        pkgbuild = (ROOT / "packaging/arch/PKGBUILD").read_text()
        for index in (0, 2):
            artifact = manifest["source_artifacts"][index]
            self.assertIn(artifact["sha256"], pkgbuild)
            self.assertIn(artifact["url"].rsplit("/", 1)[0], pkgbuild)
        self.assertIn(f"pkgver={(ROOT / 'VERSION').read_text().strip()}\n", pkgbuild)

    def test_native_versions_match(self):
        version = (ROOT / "VERSION").read_text().strip()
        spec = (ROOT / "packaging/rpm/gpu-unlock.spec").read_text()
        self.assertIn(f"Version: {version}\n", spec)
        for index in (0, 2):
            self.assertIn(self.manifest()["source_artifacts"][index]["sha256"], spec)
        changelog = (ROOT / "debian/changelog").read_text()
        self.assertTrue(changelog.startswith(f"gpu-unlock ({version}) "))

    @staticmethod
    def manifest():
        return json.loads((ROOT / "firmware/artifacts-610.43.03.json").read_text())
