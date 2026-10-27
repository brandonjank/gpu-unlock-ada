#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from Zagitta/gpu-unlock 6081407b .github/ci/module.sh.
# Build every unique header tree supplied by the disposable CI container.
set -eu
minimum=${MIN_KERNEL_BUILDS:-1}
case "$minimum" in ''|*[!0-9]*) echo 'invalid MIN_KERNEL_BUILDS' >&2; exit 1 ;; esac
[ "$minimum" -gt 0 ] || { echo 'MIN_KERNEL_BUILDS must be positive' >&2; exit 1; }
seen=
count=0
for candidate do
    [ -f "$candidate/Makefile" ] || continue
    kdir=$(realpath "$candidate")
    # Exact lines also handle header paths containing spaces and aliases.
    if printf '%s\n' "$seen" | grep -Fxq -- "$kdir"; then
        continue
    fi
    compiler=${CC:-gcc}
    if [ -f "$kdir/.config" ]; then
        configured=$(sed -n '/^CONFIG_CC_VERSION_TEXT=/p' "$kdir/.config" |
                     grep -o 'gcc-[0-9][0-9]*' | sort -u)
        if [ -n "$configured" ]; then
            compiler=$configured
        fi
    fi
    command -v "$compiler" >/dev/null 2>&1 || {
        echo "required compiler unavailable: $compiler ($kdir)" >&2
        exit 1
    }
    echo "Building against $kdir with $compiler"
    make -C kernel/gpu_unlock KDIR="$kdir" CC="$compiler" clean
    make -C kernel/gpu_unlock KDIR="$kdir" CC="$compiler" KCFLAGS=-Werror
    test -f kernel/gpu_unlock/gpu_unlock.ko
    seen="${seen}${seen:+
}$kdir"
    count=$((count + 1))
done
[ "$count" -ge "$minimum" ] || {
    echo "expected at least $minimum unique kernel header trees; built $count" >&2
    exit 1
}
echo "Built $count unique kernel header trees."
