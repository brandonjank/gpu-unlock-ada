# SPDX-License-Identifier: GPL-2.0-only
"""Execute the real initramfs scripts with disposable module/firmware fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class InitramfsTests(unittest.TestCase):
    def test_hook_preserves_config_and_checks_module_and_firmware_copy(self):
        for case in ("normal","renamed","missing-unlock","missing-nvidia","failed-copy","silent-copy","missing-fw","config-conflict"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                base=Path(directory);dest=base/"image";bindir=base/"bin";bindir.mkdir()
                config=dest/"etc/modprobe.d";config.mkdir(parents=True)
                user=config/"gpu-unlock.conf";user.write_text("options gpu_unlock targets=0000:01:00.0\noptions nvidia_drm modeset=1\n")
                generated=config/"zz-gpu-unlock-display.conf"
                if case=="config-conflict":generated.write_text("options nvidia test=1\n")
                modinfo=bindir/"modinfo"
                modinfo.write_text("""#!/bin/sh
name=$5
[ "$CASE" != missing-unlock ] || [ "$name" != gpu_unlock ] || exit 1
[ "$CASE" != missing-nvidia ] || [ "$name" != nvidia ] || exit 1
[ "$CASE" != renamed ] || name=$name-current
if [ "$4" = filename ]; then echo "/lib/modules/6.0/$name.ko.zst"; fi
if [ "$4" = firmware ] && [ "$5" = nvidia ]; then echo nvidia/test.bin; fi
exit 0
""");modinfo.chmod(0o755)
                helpers="""copy_fixture() {
    name=$1
    [ "$CASE" != renamed ] || name=$name-current
    mkdir -p "$DESTDIR/lib/modules/6.0" "$DESTDIR/conf"
    printf fixture >"$DESTDIR/lib/modules/6.0/$name.ko.zst"
}
force_load() { copy_fixture "$1"; echo "$1" >>"$DESTDIR/conf/modules"; }
manual_add_modules() {
    [ "$CASE" != failed-copy ] || return 1
    [ "$CASE" != silent-copy ] || return 0
    for module in nvidia nvidia_modeset nvidia_drm; do copy_fixture "$module"; done
    if [ "$CASE" != missing-fw ]; then
        mkdir -p "$DESTDIR/usr/lib/firmware/nvidia"
        printf fixture >"$DESTDIR/usr/lib/firmware/nvidia/test.bin.zst"
    fi
}
"""
                hook=(ROOT/"packaging/boot/initramfs-tools-hook").read_text()
                script=base/"hook";script.write_text(hook.replace(". /usr/share/initramfs-tools/hook-functions",helpers))
                run=subprocess.run(["sh",str(script)],env=dict(os.environ,PATH=f"{bindir}:/usr/bin:/bin",DESTDIR=str(dest),version="6.0",CASE=case),capture_output=True,text=True)
                success=case in ("normal","renamed","missing-unlock","missing-nvidia")
                self.assertEqual(run.returncode==0,success,run.stdout+run.stderr)
                self.assertEqual(user.read_text(),"options gpu_unlock targets=0000:01:00.0\noptions nvidia_drm modeset=1\n")
                marker=dest/"conf/gpu-unlock-display"
                if case in ("normal","renamed"):
                    suffix="-current" if case=="renamed" else ""
                    self.assertEqual(generated.read_text(),"".join(f"blacklist {m}{suffix}\n" for m in ("nvidia","nvidia_modeset","nvidia_drm")))
                    self.assertEqual(marker.read_text(),"gpu-unlock-display-v1\n")
                    self.assertEqual((dest/"conf/modules").read_text(),"gpu_unlock\n")
                else:
                    self.assertFalse(marker.exists())
                    self.assertEqual(generated.exists(),case=="config-conflict")
                self.assertFalse(list(config.glob("*.??????")))

    def test_premount_marker_options_and_load_failure(self):
        for marker in (None,"wrong","gpu-unlock-display-v1"):
            for failed in (False,True):
                with self.subTest(marker=marker,failed=failed), tempfile.TemporaryDirectory() as directory:
                    base=Path(directory);flag=base/"marker";log=base/"log"
                    if marker is not None:flag.write_text(marker+"\n")
                    modprobe=base/"modprobe"
                    modprobe.write_text('#!/bin/sh\nprintf "[%s] %s\\n" "$'+'{MODPROBE_OPTIONS-unset}" "$*" >"'+str(log)+'"\nexit '+str(int(failed))+'\n')
                    modprobe.chmod(0o755)
                    source=(ROOT/"packaging/boot/initramfs-tools-premount").read_text()
                    script=base/"premount";script.write_text(source.replace("/conf/gpu-unlock-display",str(flag)).replace("/sbin/modprobe",str(modprobe)))
                    result=subprocess.run(["sh",str(script)],env=dict(os.environ,MODPROBE_OPTIONS="-qb"),capture_output=True,text=True)
                    self.assertEqual(result.returncode,1 if marker=="gpu-unlock-display-v1" and failed else 0)
                    self.assertEqual(log.read_text() if log.exists() else None,"[unset] nvidia_drm\n" if marker=="gpu-unlock-display-v1" else None)
