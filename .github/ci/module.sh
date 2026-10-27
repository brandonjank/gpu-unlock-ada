#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from Zagitta/gpu-unlock af28cbbf and 6081407b .github/ci/module.sh.
# Disposable CI only: build the module, never load it.
set -eu
. /etc/os-release
minimum=1
case "$ID" in
debian) apt-get update -q; apt-get install -qy --no-install-recommends make gcc linux-headers-amd64 ;;
ubuntu)
    apt-get update -q
    apt-get install -qy --no-install-recommends make gcc linux-headers-generic
    case "$VERSION_ID" in
    22.04|24.04)
        # Missing expected HWE coverage must fail CI visibly.
        apt-get install -qy --no-install-recommends "linux-headers-generic-hwe-$VERSION_ID"
        minimum=2 ;;
    esac
    # HWE headers need not depend on the GCC used to compile their kernel.
    compilers=$(grep -h '^CONFIG_CC_VERSION_TEXT=' /usr/src/linux-headers-*/.config |
                grep -o 'gcc-[0-9][0-9]*' | sort -u)
    for compiler in $compilers; do
        apt-get install -qy --no-install-recommends "$compiler"
    done ;;
fedora) dnf install -qy make gcc kernel-devel ;;
arch)
    pacman -Syu --noconfirm --needed make gcc linux-headers linux-lts-headers
    minimum=2 ;;
*) echo "unsupported distribution: $ID" >&2; exit 1 ;;
esac
MIN_KERNEL_BUILDS=$minimum sh .github/ci/module-build.sh \
    /usr/src/linux-headers-*-amd64 /usr/src/linux-headers-*-generic \
    /usr/src/kernels/* /usr/lib/modules/*/build
