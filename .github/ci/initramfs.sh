#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Disposable Debian CI: construct an image; never load a module or boot it.
set -eux
apt-get update -q
apt-get install -qy --no-install-recommends initramfs-tools linux-headers-amd64
kernel_dir=$(find /lib/modules -mindepth 2 -maxdepth 2 -name build | sort | tail -n 1)
[ -n "$kernel_dir" ]
release=$(make -s -C "$kernel_dir" kernelrelease)
scratch=$(mktemp -d)
mkdir -p "$scratch/modules" "/lib/modules/$release/updates/gpu-unlock-ci"
cat >"$scratch/modules/Makefile" <<'EOF'
obj-m += nvidia.o nvidia_modeset.o nvidia_drm.o
EOF
cat >"$scratch/modules/nvidia.c" <<'EOF'
#include <linux/module.h>
int gpu_unlock_ci_nvidia(void) { return 0; }
EXPORT_SYMBOL(gpu_unlock_ci_nvidia);
MODULE_FIRMWARE("gpu-unlock-ci.bin");
MODULE_LICENSE("GPL");
EOF
cat >"$scratch/modules/nvidia_modeset.c" <<'EOF'
#include <linux/module.h>
extern int gpu_unlock_ci_nvidia(void);
int gpu_unlock_ci_modeset(void) { return gpu_unlock_ci_nvidia(); }
EXPORT_SYMBOL(gpu_unlock_ci_modeset);
MODULE_LICENSE("GPL");
EOF
cat >"$scratch/modules/nvidia_drm.c" <<'EOF'
#include <linux/module.h>
extern int gpu_unlock_ci_modeset(void);
static int __init fixture_init(void) { return gpu_unlock_ci_modeset(); }
module_init(fixture_init);
MODULE_LICENSE("GPL");
EOF
make -s -C "$kernel_dir" M="$scratch/modules" modules
make -s -C "$kernel_dir" M="$PWD/kernel/gpu_unlock" modules
cp "$scratch/modules/"*.ko kernel/gpu_unlock/gpu_unlock.ko "/lib/modules/$release/updates/gpu-unlock-ci/"
depmod "$release"
make -s ASSETS="$PWD/build/deb/gpu-unlock-$(cat VERSION)/debian/gpu-unlock-build/assets" install-firmware install-initramfs-tools
printf fixture >/lib/firmware/gpu-unlock-ci.bin
mkdir -p /etc/modprobe.d
printf 'options gpu_unlock targets=0000:01:00.0\n' >/etc/modprobe.d/gpu-unlock.conf
printf 'nvidia\nnvidia_drm\n' >>/etc/initramfs-tools/modules
mkinitramfs -o "$scratch/image" "$release"
unmkinitramfs "$scratch/image" "$scratch/unpacked"
marker=$(find "$scratch/unpacked" -path '*/conf/gpu-unlock-display' -print -quit)
[ -n "$marker" ]
image=$(dirname "$(dirname "$marker")")
test -x "$image/scripts/init-premount/gpu-unlock"
grep -q '^gpu_unlock' "$image/conf/modules"
grep -q '^gpu-unlock-display-v1$' "$image/conf/gpu-unlock-display"
grep -q '^blacklist nvidia$' "$image/etc/modprobe.d/zz-gpu-unlock-display.conf"
grep -q '^blacklist nvidia_modeset$' "$image/etc/modprobe.d/zz-gpu-unlock-display.conf"
grep -q '^blacklist nvidia_drm$' "$image/etc/modprobe.d/zz-gpu-unlock-display.conf"
grep -q '^options gpu_unlock targets=0000:01:00.0$' "$image/etc/modprobe.d/gpu-unlock.conf"
find "$image" -name 'gpu_unlock.ko*' | grep -q .
find "$image" -name 'nvidia_drm.ko*' | grep -q .
find "$image" -name 'gpu-unlock-ci.bin*' | grep -q .
echo "Real initramfs contains modules/firmware, preserved options and guarded display handoff."
