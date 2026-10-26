# GPU unlock 1.1.1 — RTX 4090 and RTX 4070 Ti SUPER

New to this project? Start with the [copy-paste Quick Start](QUICKSTART.md).

This fork is maintained at [brandonjank/gpu-unlock-ada](https://github.com/brandonjank/gpu-unlock-ada).
It preserves the original project history and adds the experimental Windows/UEFI
port. See [upstream tracking](docs/upstreams.md) for source repositories,
revision baselines and the update review process.

**Windows / Ubuntu on WSL2:** see the [experimental Windows preboot port](windows/README.md).
Its CUDA validation runner has been exercised on both systems; the RTX 4090 UEFI
unlock and Windows driver handoff still require hardware validation. The Linux
kernel module cannot unlock the Windows host GPU from inside WSL2.

This Linux kernel module enables the SM speed-select override before the stock
NVIDIA driver starts. RTX 4090 (`10de:2684`, AD102) support has demonstrated
approximately **2× FP16 and BF16 tensor throughput with FP32 accumulation**:

| Mode | Before | After |
|---|---:|---:|
| FP16 → FP32 accumulate | 165.6 TF/s | 331.6 TF/s |
| BF16 → FP32 accumulate | 165.5 TF/s | 330.6 TF/s |

The override survived PCIe Function Level Reset (FLR), stock NVIDIA `615.78.08`
initialization and CUDA benchmarks. INT8, `dp4a` and scalar FP32 stayed near their
baseline rates. This is one tested RTX 4090 and one successful cold power-on;
independent cold-boot reproduction and application numerical validation remain
pending. The measured firmware transaction preceded the repository cleanup;
the cleaned module has host-side validation and still needs that hardware repeat.
See the [technical report](rtx4090-register-report.md) and
[sanitized evidence](docs/evidence/rtx4090/README.md).

A separate cold test of the Ada port on one RTX 4070 Ti SUPER
(`10de:2705`) with NVIDIA `580.178.04` measured FP16/FP32 tensor issue rate
at **95.0 → 189.9 TF/s** and BF16/FP32 at **95.0 → 189.7 TF/s** under the
same 240 W power cap. INT8 stayed at 379.5 TOP/s. The stock driver loaded,
the NVIDIA RM getter reported full FMLA32 rate, deterministic FP16/BF16 GEMM
outputs matched exactly, and owner mining recovered with fresh accepted shares.
A second matched instruction benchmark found **TF32/FP32 47.49 → 94.51 TF/s**
(1.99×), with its FP16/FP32 control also near 2×. Unsigned INT4/INT32 stayed
at approximately **754.8 TOP/s** in both states. These are register-resident
issue rates, not application GEMM or inference speedups.
A matched, verified E4M3 FP8/FP32 CUTLASS GEMM measured **59.326 TF/s stock →
59.495 TF/s unlocked** on this card, a 0.3% difference. This single GEMM did
not show a meaningful FP8 gain; other FP8 kernels remain untested.
This is one card; the unlock succeeded on two cold boots and two ordinary
warm reboots, the last from a persistent EFI default. Throughput was measured
on the first cold boot. See the [2705 canary report](docs/ada-2705-report.md)
and its [sanitized raw benchmark output](docs/evidence/ada2705/README.md).

The AD102 payload and its debug-booter analysis come from
**[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)**.
This fork integrates that published payload into
**[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)**'s Linux module,
firmware generation and boot packaging. The payload is essential to the result.

## Additional RTX 4090 evidence

Two contributor reports on NVIDIA 610.57.04 add matched instruction, GEMM and
numerical results: [a standard RTX 4090](docs/evidence/rtx4090-610.57.04/README.md)
and [a modified 48 GB RTX 4090](docs/evidence/rtx4090-48g-modded/README.md).
Affected FP16/BF16-input, FP32-accumulate instruction modes approach 2x;
GEMM improvements vary with shape and include unchanged or regressing cases.
The modified card's quantized MoE serving workload showed no demonstrated gain.
Each report covers one card and one stock/unlocked pair, with documented
background, thermal and cache differences. These are attributed observations,
not new physical validation performed by this fork.

## Supported targets

The module selects the AD102 firmware and payload automatically for RTX 4090
`10de:2684`. The original GeForce/CMP GA102/GA104 device list and GA102 payload
are retained, along with the newer GA103/GA106 device list. Upstream reported
RTX 3090 success; this branch does not revalidate every legacy board.

The Ada port additionally recognizes RTX 4070 Ti SUPER
`10de:2705` as an **experimental AD103 target validated on one card**. It requires both
`gpu_unlock.ad103_experimental=1` and `gpu_unlock.targets=` set to that card's
single exact PCI address. `targets=all` never selects it. On the tested 2705,
two cold boots and later warm reboots confirmed driver 580.178.04 handoff and
full-rate readbacks; matched throughput was measured across stock and unlocked
boots. Other boards remain unverified.
Other Ada IDs, professional RTX A-series and data-centre parts are not accepted.
Shared firmware across Ada chips does not establish support for untested cards.

The RTX 4090 path runs the signed firmware, checks the payload's completion marker and
required permissions, writes SS0 `0x88888888` and SS1 `0x8`, then performs FLR
before the unmodified NVIDIA driver binds. It requires the expected
effective speed-select readout before and after FLR. No patched NVIDIA driver or UEFI
application is needed. The payload uses instruction addresses derived from
published decrypted debug-booter analysis; the production booter is authenticated
and decrypted inside the GPU.

## Build and install

Clone the GPL-2.0-only source and build the packages locally so the pinned
NVIDIA firmware is downloaded and generated on your own machine:

```sh
git clone https://github.com/brandonjank/gpu-unlock-ada.git
cd gpu-unlock-ada
make install
```

`make install` detects the supported distribution family. Its explicit targets
are:

```sh
make install-arch   # makepkg -sif
make install-deb    # apt-get build-dep, dpkg-buildpackage, apt-get install
make install-rpm    # dnf builddep, rpmbuild, dnf install
```

`make arch`, `make deb` and `make rpm` build without installing. Packages are
built from the committed `HEAD`; Debian and RPM outputs go to `build/deb` and
`build/rpm`. Kernel headers and a working DKMS toolchain are required.

Debian builds can start from an NTFS/DrvFS checkout under WSL, including a path
with spaces. `make deb` extracts committed sources into a unique directory under
`$HOME/.cache/gpu-unlock/deb-builds`, preserving the Unix modes Debian requires.
Override this location with `DEBBUILD_ROOT=/path/on/a/Linux/filesystem`; the build
checks that it preserves file modes. Only the private temporary directory is
removed after success or failure, and finished packages are copied back to
`build/deb` (or `DISTDIR/deb`). The Windows UEFI build continues to use its
existing [Windows instructions](windows/README.md).

RPM builds also support checkout, input-cache and output paths containing spaces,
including NTFS/DrvFS checkouts. `make rpm` uses a unique build directory under
`$HOME/.cache/gpu-unlock/rpm-builds`, then copies the two binary packages and
source-only `.nosrc.rpm` back to `build/rpm` (or `DISTDIR/rpm`). Override the private
build location with `RPMBUILD_ROOT=` pointing to a Linux filesystem directory
without whitespace; RPM's generated scripts require this. Its Unix modes are
checked before building. Temporary files are cleaned up on success or failure,
while previous successful packages and unrelated cache files are preserved.

Builds fetch the pinned NVIDIA `610.43.03` source and binary inputs over HTTPS
and verify their SHA-256 hashes. `make inputs` prepares the cache;
`make firmware` generates assets from cached inputs; `make assets` does both.
The default cache is `$HOME/.cache/gpu-unlock` and can be overridden with
`CACHE=`, `INPUTS=` and `ASSETS=`. A clean-chroot Debian build needs
`GPU_UNLOCK_INPUTS` pointing to the input cache because `dpkg-buildpackage`
does not fetch inputs itself.

The source archive produced by `make dist`, the Debian source package and the
`.nosrc.rpm` contain no NVIDIA archives or generated firmware. See
[firmware/README.md](firmware/README.md) for the input and asset layout.
Prebuilt firmware packages are not distributed by this repository.

## Enable at boot

The package installs the module and firmware into the initramfs so the unlock
runs before NVIDIA binds the card. It remains inactive unless the kernel
command line opts in:

```text
gpu_unlock.targets=0000:03:00.0
gpu_unlock.targets=0000:03:00.0,0000:04:00.0
gpu_unlock.targets=all
gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad103_experimental=1
```

These PCI addresses are examples. Use the full PCI names printed by `lspci -D`.
`all` selects every accepted unbound card, including legacy GA102/GA104 targets;
an explicit address is useful when selecting one RTX 4090. Do not mix `all` with
addresses. RTX 4070 Ti SUPER `10de:2705` requires the additional experimental
flag and a single exact PCI address; `all` never selects it. Invalid entries
are logged and ignored.

The packages support these initramfs generators:

- **mkinitcpio:** `/etc/mkinitcpio.conf.d/zz-gpu-unlock.conf` puts `gpu_unlock`
  immediately before `nvidia` in `MODULES`, or last if NVIDIA is absent. Images
  are rebuilt on installation. A custom configuration selected with `-c` or a
  preset `_config` does not read drop-ins; add `gpu_unlock` before `nvidia` in
  that configuration's `MODULES` yourself.
- **initramfs-tools:**
  `/usr/share/initramfs-tools/modules.d/gpu-unlock.conf`.
- **dracut:** `/usr/lib/dracut/dracut.conf.d/gpu-unlock.conf`.

There is no `softdep nvidia pre:` rule because kmod uses only the first matching
soft dependency line, which can conflict with other packages.

**Power the machine off and start it again for the first attempt.** The module
needs a card whose firmware state is fresh before NVIDIA loads. A warm reboot
is not guaranteed to provide that state: it did on the tested
RTX 4070 Ti SUPER, where the pre-firmware WPR2 readback returned to zero and
the unlock succeeded again without an AC cut. Other boards may retain WPR2;
the module refuses to rerun the firmware sequence in that state. It also skips
cards that are already bound, powered down or bus mastering.
Loading the module manually after NVIDIA has bound the card cannot unlock it.

After validating a cold boot and a one-time warm reboot on the exact card, a
persistent bootloader entry can select the same early initramfs and exact
`gpu_unlock.*` options on every boot. A one-shot entry by itself does not
persist. Keep an unmodified stock entry available, and verify
`gpu_unlock: unlocked`, the rate readback and GPU health after each boot.
The tested canary uses a kernel-version-specific image; regenerate and
revalidate that image before removing its pinned kernel during an upgrade.

Avoid `nvidia-smi`, CUDA, NVML and `nvidia-modprobe` before a manual cold-card
attempt: they can load NVIDIA by name. Ordinary modprobe blacklist rules do not
block explicit named loads. The packaged initramfs flow avoids the need for
manual firmware staging and research parameters.

The original display-card handoff is retained: the firmware framebuffer is
removed just before FLR, and the display stays blank until `nvidia-drm` takes
over. Display handoff and multi-card operation were not part of the RTX 4090
validation.

## Check and disable

Inspect the kernel log after boot:

```sh
journalctl -k -b | grep gpu_unlock
lspci -nnk -s 0000:03:00.0  # replace the example address
```

A loaded module or successful `modprobe` return alone does not prove an unlock:
look for the selected card's `gpu_unlock: unlocked` message and the payload,
selector and post-FLR checks. The report describes independent register and
performance confirmation. The optional read-only sampler lives in
`diagnostics/peek`; the CUDA instruction benchmark is in `diagnostics/bench`.
Never load a second BAR0 sampler while `gpu_unlock` is performing its firmware
transaction.

If the module reports that firmware did not stop and its DMA buffers are being
kept, power off before trying again. The module intentionally retains buffers
that firmware may still use. Do not force-unload it in this state.

Remove `gpu_unlock.targets=` from the kernel command line to disable future
attempts. It can be removed for one boot in the bootloader editor. Removing the
packages removes the module and initramfs integration; power off to return to a
fresh hardware state.

## Development and credits

`make test` runs the host-side suite without accessing a GPU. With generated
firmware available, it also exercises complete unlock transactions against mocked
hardware. `make LLVM=1 -C kernel/gpu_unlock` builds the module with LLVM against
the running kernel's headers.

The Linux module and packaging derive from
[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock). The AD102 four-PLM
payload derives from
[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker),
including its published payload generator and debug-booter analysis. The GA102
V67 chain derives from
[WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock).
The earlier CMP unlock work, NVIDIA's published loader code, Nouveau and
[envytools](https://github.com/envytools/envytools) also underpin the loader and
investigation.

The kernel module, packaging and payload integration are GPL-2.0-only. NVIDIA
firmware remains under its own terms. See [firmware/NOTICE.md](firmware/NOTICE.md)
and [licenses/](licenses/) for provenance and preserved license notices.

### initramfs-tools display handoff

The build hook explicitly includes and schedules gpu_unlock, then, when NVIDIA
is installed, includes nvidia_drm, its dependencies and declared firmware.
An image-only generated blacklist prevents earlier NVIDIA alias loads. The
init-premount script clears inherited modprobe blacklist options and restores
NVIDIA display before the encrypted-root prompt. User modprobe options are
preserved; a conflicting generated file or missing required module/firmware
fails image construction visibly. Driver loading failures are reported.

This can add about 90 MB per image; allow space in /boot. It applies to
initramfs-tools, not dracut, mkinitcpio or Windows. Rebuild the initramfs after
installing/updating the package. Host and CI image checks do not establish
physical display recovery for a new board.

### Selecting a GPU for the rate diagnostic

tools/read_sm_rates.py requires an exact --expect-uuid inventory match, the same
UUID in the driver's PCI information, and a matching NVIDIA character device.
The public RM UUID and PCI getters select its actual device/subdevice instances.
Missing or inconsistent mappings fail rather than trying other cards.
Native Linux device nodes and /proc/driver/nvidia/gpus are required; WSL's
projected GPU does not provide this RM transport.
