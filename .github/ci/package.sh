#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from Zagitta/gpu-unlock af28cbbf .github/ci/package.sh.
# Disposable CI only: build packages, never install the unlock.
set -eu
: "${INPUTS:?set INPUTS to the checked artifact cache}"
INPUTS=$(realpath "$INPUTS")
git config --global --add safe.directory "$PWD"
. /etc/os-release
case "$ID" in
debian|ubuntu)
    apt-get build-dep -qy .
    make deb INPUTS="$INPUTS"
    dpkg-deb --contents build/deb/gpu-unlock-dkms_*_all.deb > build/deb/package-contents.txt
    grep -q 'usr/lib/dracut/dracut.conf.d/gpu-unlock.conf' build/deb/package-contents.txt
    grep -q 'usr/share/initramfs-tools/modules.d/gpu-unlock.conf' build/deb/package-contents.txt
    grep -q 'usr/share/initramfs-tools/hooks/gpu-unlock' build/deb/package-contents.txt
    grep -q 'usr/share/initramfs-tools/scripts/init-premount/gpu-unlock' build/deb/package-contents.txt
    sh .github/ci/initramfs.sh
    ;;
fedora)
    dnf builddep -qy packaging/rpm/gpu-unlock.spec
    make rpm INPUTS="$INPUTS"
    rpm -qlp build/rpm/RPMS/noarch/gpu-unlock-dkms-*.rpm > build/rpm/package-contents.txt
    grep -q '/usr/lib/dracut/dracut.conf.d/gpu-unlock.conf' build/rpm/package-contents.txt
    ;;
arch)
    useradd -m builder
    chown -R builder "$PWD" "$INPUTS"
    runuser -u builder -- env SRCDEST="$INPUTS" sh -c 'cd packaging/arch && makepkg -f --noconfirm'
    for package in packaging/arch/gpu-unlock-dkms-*.pkg.tar.zst; do
        tar -tf "$package" > build-package-contents.txt
        grep -q 'usr/lib/dracut/dracut.conf.d/gpu-unlock.conf' build-package-contents.txt
        grep -q 'etc/mkinitcpio.conf.d/zz-gpu-unlock.conf' build-package-contents.txt
    done
    ;;
*) echo "unsupported distribution: $ID" >&2; exit 1 ;;
esac
