# UEFI source provenance

The UEFI application and compatibility layer in `uefi/` derive from
[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker),
revision `51df9c17ec89eb8486df52cc9079dde4bd1f9974`. The code is GPL-2.0-only.
Original per-file notices are preserved. Newly added probe, profile/build tools,
tests, and modifications are also GPL-2.0-only.

Changes dated 2026-10-24: add a read-only RTX 4090 probe; bind PCI location,
subsystem, chip, BAR0, VRAM and ROM/PROM hashes to that probe's measurements;
replace fixed RTX 4080 identity and memory assumptions; add reproducible build
reports and Windows/WSL validation. The retained firmware transaction is an
experimental adaptation and requires hardware validation on the RTX 4090.

Follow-up changes on the same date: accept disabled SS1 selector values rather
than requiring another board's value of 7; pin the measured SS1 for unlock
preflight; log Secure Boot state and support firmware-authorized execution with
Secure Boot enabled without changing any firmware trust variables.

Changes dated 2026-10-29: add private Windows ESP and boot-manager size/SHA-256
pins, exact-buffer firmware loading and explicit staged-image cleanup, following
the boot-file preflight approach in
[JustAResearcher/gpu-unlock-ada PR #104](https://github.com/JustAResearcher/gpu-unlock-ada/pull/104),
head `26fdc0473bfb4541dae50ae76d5012f32c81170f`. That contribution by w93163red
derives from Latence.app's AD104/MSI port, published through Bizcott. Our focused
adaptation remains GPL-2.0-only and retains our Secure Boot admission, build
toolchain, board profiles and display/transaction implementation. No Windows
binary, ESP identifier or other board's hardware pins are distributed.

Probe version 3 adds bounded firmware-view backups, repeated PROM sampling,
selected register and boot-state snapshots, USB readback verification, and an
offline capture inspector. The register selection follows this repository's
`diagnostics/peek/gpu_peek.c` and retained Falcon-status diagnostics.

The retained transaction in `uefi/vendor/` derives from
[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock/tree/0ebdb1c6308b6a2072be5bf04513472942541956),
revision `0ebdb1c6308b6a2072be5bf04513472942541956`, with TOTORONG's UEFI changes.
It is a separate, older transaction implementation from `kernel/gpu_unlock/`;
tests of the current Linux module do not establish this port's hardware behavior.

The EDK2 declaration headers in `uefi/edk2/` derive from TianoCore EDK2
revision `c1415771ac592ad8509351c46cd3cda4f38d7d52`, as supplied by the pinned
TOTORONG source. Their license is BSD-2-Clause-Patent; see
`uefi/LICENSES/EDK2-BSD-2-Clause-Patent.txt`, `uefi/edk2/License.txt`, and
individual copyright headers. No EDK2 library binaries are linked.

Preserved MIT and NVIDIA driver notices are in `uefi/LICENSES/`. Firmware assets
are generated locally by the existing pinned generators; NVIDIA's license is
preserved with them. ROM dumps and generated firmware are not part of the source
distribution. See the repository's `firmware/NOTICE.md` for payload provenance.
