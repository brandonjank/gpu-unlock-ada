#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from Zagitta/gpu-unlock af28cbbf .github/ci/module.sh.
# Disposable CI only: build the module, never load it.
set -eu
. /etc/os-release
case "$ID" in
debian) apt-get update -q; apt-get install -qy --no-install-recommends make gcc linux-headers-amd64 ;;
ubuntu) apt-get update -q; apt-get install -qy --no-install-recommends make gcc linux-headers-generic ;;
fedora) dnf install -qy make gcc kernel-devel ;;
arch) pacman -Syu --noconfirm --needed make gcc linux-headers ;;
*) echo "unsupported distribution: $ID" >&2; exit 1 ;;
esac
for kdir in /usr/src/linux-headers-*-amd64 /usr/src/linux-headers-*-generic /usr/src/kernels/* /usr/lib/modules/*/build; do
    [ -f "$kdir/Makefile" ] && break
done
[ -f "$kdir/Makefile" ] || { echo 'no kernel headers found' >&2; exit 1; }
make -C kernel/gpu_unlock KDIR="$kdir" KCFLAGS=-Werror
test -f kernel/gpu_unlock/gpu_unlock.ko
