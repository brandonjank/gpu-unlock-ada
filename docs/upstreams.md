# Upstream tracking

The public development repository is
[brandonjank/gpu-unlock-ada](https://github.com/brandonjank/gpu-unlock-ada).
Its Git history is preserved from JustAResearcher's Ada fork. Local Windows/UEFI
work is committed on top of that history; the existing GPL and third-party
notices remain in place.

## Sources to monitor

| Source | Relationship and review focus |
|---|---|
| [JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada) | Direct parent: Ada fixes, validation, firmware integration and packaging. |
| [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) | Linux module origin: reset, DMA lifetime, initialization, device support and tests. |
| [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock) | GA102 V67 payload and CMP research: privilege masks, firmware flow and reproducible evidence. |
| [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker) | Ada payload and UEFI port source: Windows handoff, board checks and debug-booter analysis. This source is hosted on Hugging Face. |
| [NVIDIA/open-gpu-kernel-modules](https://github.com/NVIDIA/open-gpu-kernel-modules) | Pinned firmware's source contracts: GSP/SEC2/boot loaders, ABI changes, Ada and reset behavior. |
| [tianocore/edk2](https://github.com/tianocore/edk2) | Vendored declaration headers: relevant MdePkg UEFI, PCI, filesystem and boot-service fixes. |
| [envytools/envytools](https://github.com/envytools/envytools) | Investigation reference: Ada register definitions, Falcon and firmware decoding. |
| [Consensus-Protocol/cmp170hx](https://github.com/Consensus-Protocol/cmp170hx) | Research reference: privilege-level masks, unlock validation and reproducible hardware findings. |
| [amoghmunikote/cmpunlocker](https://github.com/amoghmunikote/cmpunlocker) | Earlier CMP research reference: relevant mechanisms and validation ideas. |

[upstreams.json](upstreams.json) records the initial observed heads and the
integration pins where known. An observed head is a monitoring baseline, not a
claim that its code is integrated or validated. The exact firmware hashes and
source pins remain authoritative in `firmware/artifacts-610.43.03.json`,
`firmware/ada-610.43.03.json` and `windows/THIRD_PARTY_NOTICES.md`.

## Daily review

A Codex monitor attached to the project chat checks these sources daily at
9:00 AM America/Los_Angeles. Scheduling is managed in the desktop app, outside
the source repository. It requires the app's local scheduler and network access.
Cloning this repository does not install or activate that schedule.

The monitor compares default-branch heads, releases, and recently updated issues
and pull requests or Hugging Face discussions against its last successful
checkpoint. It reviews relevant diffs and evidence, then reports useful updates
and concrete ideas with source links, affected local files and suggested checks.
Large reference repositories are filtered to this project's review focus.
It stays quiet when nothing actionable changes and deduplicates prior reports.
Unavailable sources are recorded as coverage gaps, never as unchanged.

Private checkpoints and review notes live under the ignored
`scratchpad/upstream-monitor/` directory. The initial public baseline lives in
`docs/upstreams.json`. Successful checkpoints advance only after the relevant
material has been inspected; failed sources retain their prior checkpoints.

## Integrating a candidate

1. Fetch the source and compare its commits with the recorded integration pin.
2. Develop the selected change on a `codex/` branch, retaining source attribution
   and reviewing its license. Prefer a focused cherry-pick or port over a broad
   merge between divergent implementations.
3. Run the relevant host tests, including `make test` for Linux and
   `python windows/test.py --zig PATH_TO_ZIG` for the Windows port.
4. Review any changed firmware addresses, hashes, device assumptions and boot
   handoff separately. Host tests do not establish hardware safety or throughput.
5. Review and commit the tested change before updating an integration pin.

Monitoring does not automatically merge code, replace pinned firmware, execute
upstream scripts, run GPU experiments or change the machine's boot configuration.

## Detailed review, 2026-10-24

Reviewed our published `aaaa5d7` against Zagitta's current
`af28cbbfd3d922a659227ecfb7369adfd924cf03`, the two initially identified
commits, relevant open issues/PRs, and NVIDIA's `615.78.08` PM notifier source.
The direct Ada parent is still `491925c`. Zagitta is 22 commits ahead of the
older transaction recorded by the UEFI vendor notice; that count does not
describe the separate Ada Linux module's integration status.

The initial candidate list was provisional: **the older-kernel and firmware-BME
fixes are already in our Linux module**, including its fault-injection cases.
No runtime behavior is changed by this review.

| Candidate | Decision | Evidence and scope |
|---|---|---|
| [Reject initial GFW register-error values, issue 42](https://github.com/Zagitta/gpu-unlock/issues/42) | First priority: implement a focused adaptation | Both `kernel/gpu_unlock/gfw_eval.c` and `windows/uefi/vendor/gfw_eval.c` accept `0xbadfxxxx` samples when their low bits resemble completion. Independently reproduced with the actual predicates, without GPU access. |
| [FWSEC DMA validation before launch, PR 35](https://github.com/Zagitta/gpu-unlock/pull/35) | Keep Linux's existing solution; adapt the remaining UEFI cleanup fix | Linux already rounds transfer spans, bounds their tails, validates both transfers before reset and marks firmware active at the DMA boundary. UEFI already rounds/bounds DMEM through `gpu_unlock_fwsec_dmem_transfer`, but sets `firmware_started` and calls `GuStarted()` before `falcon_hs()` rejects invalid mapped-address geometry. Review that lifetime boundary separately. |
| [CI with generated firmware and real module builds](https://github.com/Zagitta/gpu-unlock/blob/af28cbbfd3d922a659227ecfb7369adfd924cf03/.github/workflows/ci.yml) | Bring over the coverage approach | Our workflow runs host tests without generated inputs. Add checked input caching, generated GA/Ada assets and full mocked transactions; then real Linux-header and native-package builds. Keep our Windows checks and adapt rather than replacing the workflow wholesale. |
| [Debian dracut packaging, PR 26](https://github.com/Zagitta/gpu-unlock/pull/26), and [Arch packaging, issue 44](https://github.com/Zagitta/gpu-unlock/issues/44) | Bring in focused packaging fixes | Our Debian install target/list omit the dracut file; our Arch recipe only invokes `install-mkinitcpio`. The shared `make install-dracut` target already exists. Test the actual native package contents and lifecycle, not just a staging install that explicitly requests every integration target. |
| [Older-kernel and firmware-BME claims](https://github.com/Zagitta/gpu-unlock/commit/d04f5a00f30d9bceec7069868a7504fd925dc7ad) | No Linux import needed | `unlock_transaction_claim()` already accepts `PCI_UNKNOWN` only with PMCSR-confirmed D0 and verifies clearing firmware BME. Existing scenarios cover unknown power with/without PM support and stuck BME. The separate UEFI environment needs its own ownership policy. |
| [mkinitcpio systemd-hook fix, PR 34](https://github.com/Zagitta/gpu-unlock/pull/34) and [Debian/RPM lifecycle rebuilds](https://github.com/Zagitta/gpu-unlock/commit/258f38ad4efc3ea6b25afedf8ccbf6fe655423a9) | Core fixes already present | Our mkinitcpio config emits the plain module name and tests removal of the old `?` entry. Debian rebuild hooks and the RPM/DKMS per-kernel lifecycle work are already present. Do not replace our ordering logic with a duplicate fix. |
| [Suspend/resume re-unlock](https://github.com/Zagitta/gpu-unlock/commit/c274e74981d996e4b83266b43b9070804099ddae) | Hold; do not enable by default | Requires a new bound-driver transaction path and a characterized failure handoff. [Issue 43](https://github.com/Zagitta/gpu-unlock/issues/43) reports late failures retaining DMA/state while the card remains eligible for another resume transaction. Source review confirms the notifier logs a failure and retains that eligibility. This issue is an offline report, not proof of a particular hardware failure. |

### Independently reproduced validator gap

A small CPU-only harness linked separately against each production `gfw_eval.c`
returned success (`0`) for each of these samples with `config_ok=true`:

| PLM | BOOT | CPUCTL | Result in both copies |
|---|---|---|---|
| `0xbadf0001` | `0xff` | `0x10` | `0` |
| `1` | `0xbadf00ff` | `0x10` | `0` |
| `1` | `0xff` | `0xbadf0010` | `0` |
| `0xbadf0001` | `0xbadf00ff` | `0xbadf0010` | `0` |

The valid control also returned `0`; the all-ones control returned `-ENODEV`.
The transaction's later feature/permission/WPR2 checks still apply: this result
establishes a validator inconsistency, not a demonstrated complete unlock bypass.

Acceptance for the adaptation: reject the PRI-error family in each register and
mixed samples; retain valid/in-progress/all-ones controls; verify initial-sampler
PCI identity and protected-read ordering; preserve the existing bounded retry
policy after FLR. Add adapter assertions that invalid initial samples cannot
launch FWSEC or Booter. Apply and test the equivalent predicate fix in both
Linux and UEFI copies without importing the rest of the old transaction.

### Resume gate

NVIDIA `615.78.08` registers a default-priority PM notifier only when
`NVreg_UseKernelSuspendNotifiers` is enabled. Zagitta's priority-1 notifier is
intended to run first, but that arrangement alone does not establish safe state
for every driver configuration or failure. Our existing API only allows the
cold, unbound transaction and checks for empty probe resources; the upstream
resume path deliberately bypasses some of those assumptions for a bound device.

Before considering an experimental opt-in implementation, require separate
primary/cleanup/retained-state outcomes; quarantine after retained or cleanup-
failed attempts; no retry that accumulates another DMA transaction or module pin;
tests carrying late FWSEC/Booter/FLR failures through repeated PM events; and
Ada-specific cold/kept-power/already-resumed/multi-card hardware validation.
Quarantine does not itself solve the first unsafe handoff to NVIDIA. Preserve
the cold-boot-only path until that handoff and recovery contract are established.
A Linux PM notifier does not add Windows/WSL resume support.

## Selected fixes, 2026-10-24

The selected integration implements issue 42's PRI-error rejection in both
validators. Both initial samplers now require the exact PCI vendor/device pair,
defer BOOT reads until PL0 is readable, and retry transient unreadable samples
within the existing deadline. Post-FLR retry behavior remains unchanged.

The UEFI transaction now marks firmware/DMA active at the validated DMA boundary,
matching the Linux lifetime policy. Rejected mapped-address geometry does not
set either the transaction or platform started marker; a timeout after entering
the DMA path still sets both markers and requires proven quiescence before
releasing buffers. No firmware addresses, payload bytes or input pins change.

Debian and Arch packages now ship their existing dracut configuration alongside
their other early-load configuration. Host regressions exercise the actual
Arch install function, the Debian install recipe/file selection, and Debian's
mocked install/removal rebuild hooks. Native CI also inspects built packages.

CI coverage adapts Zagitta's `af28cbbf` workflow and helper scripts under the
existing GPL-2.0-only license: hash-verified input caching, generated GA/Ada
assets, full mocked transactions, real module builds against Debian/Ubuntu/
Fedora/Arch headers, and Debian/RPM/Arch package builds. Windows and Linux run
the UEFI host tests with checksummed Zig 0.15.2, including a synthetic EFI build.
Generated firmware and packages are never uploaded as CI artifacts.

Suspend/resume support is excluded from this integration. These automated
checks exercise CPU mocks, source/package construction and compilation; they
do not establish a new physical GPU unlock or boot-handoff result.

## Local version control

`origin` points to this public fork; `upstream` points to JustAResearcher's Ada
fork. Additional source remotes are available for comparison. Normal development
uses small commits pushed to `origin`; updating an upstream remote never changes
the checked-out files by itself. Build outputs, raw ROM/firmware dumps, generated
EFI images and local credentials are excluded from new commits. Existing
sanitized published evidence remains tracked.

## Selected fixes, 2026-10-25

The firmware-only RPM permission rule adapts Zagitta PR
[128](https://github.com/Zagitta/gpu-unlock/pull/128) at
daf91fd7062ce965cba3956016f539a66630502b: files are explicitly 0644,
directories 0755, and ownership root:root. Fedora CI checks the exact firmware
package inventory, permissions, ownership and SHA-256 digests against pinned
manifests, then extracts the package privately and hashes its actual payload.
A second build deliberately stages executable files and restrictive directories
to exercise the manifest correction. BuildArch remains noarch with standard RPM
postprocessing and architecture checks enabled.

RPM builds now run from committed archives in unique, mode-checked Linux build
directories, with verified input links and completed packages copied back to the
checkout. Checkout, input-cache and output paths can contain spaces on NTFS/DrvFS;
`RPMBUILD_ROOT` must name a Linux directory without whitespace because RPM's own
generated scripts do not consistently quote `_topdir`. Native CI exercises the
spaced paths and continues to check both normal and deliberately incorrect
staging modes. The private source tree is removed on success or failure without
deleting unrelated cache entries or previous successful packages.

The NTFS Debian build fix adapts Zagitta PR
[154](https://github.com/Zagitta/gpu-unlock/pull/154) at
16d9a6bfa6de607742e59f90b8fa0fd5c18dce9f. Each build uses its own temporary
directory on a filesystem that preserves Unix modes. Quoted paths support
spaces, concurrent builds never delete each other's source directories, and
failed builds preserve previous output. Native CI checks the delivered Debian
packages and constructs its initramfs from packaged firmware, without depending
on a retained build tree. Windows UEFI behavior and firmware pins are unchanged.

This integration adapts Zagitta PR [70](https://github.com/Zagitta/gpu-unlock/pull/70)
at 524822309479f5fe760fc3ab675c5c15ae4163bd: Linux and UEFI wait for bounded GFW
completion immediately after claim, before layout reads and DMA. Existing PRI
rejection, exact identity, cold-state and cleanup checks remain.

The initramfs-tools display integration adapts Zagitta PR
[76](https://github.com/Zagitta/gpu-unlock/pull/76) at
620ebe1065f4c87806fe87f1f6ccb7f7c0ec2ab1, retaining GPL-2.0-only attribution.
Our adaptation explicitly schedules gpu_unlock, verifies copied modules and
firmware before generating a dedicated blacklist/marker, preserves user options,
and reports failed image construction or display loading.

Ada PR [36](https://github.com/JustAResearcher/gpu-unlock-ada/pull/36) identifies
multi-GPU assumptions, but its first-success minor scan is not imported.
We resolve the exact UUID through NVIDIA's pinned public RM identity ABI,
verify PCI/proc/device-node consistency and allocate its returned instances.
No firmware, MMIO, reset, suspend or resume operation is added.

Unchanged evidence from Ada PR
[21](https://github.com/JustAResearcher/gpu-unlock-ada/pull/21), commit
a13b3ea7fb14be2fcc10b7a217d684fcf360f11a, and PR
[37](https://github.com/JustAResearcher/gpu-unlock-ada/pull/37), commit
64a4d2068354afe2d042039ae85df14b0dba2ee3, is retained with its manifests, original
reports and provenance. All 34 published evidence-file checksums match.
These observations are not independent physical verification by this fork.
The earlier report also used 610.57.04; the later report's "first documented"
wording is retained only as original source text.

## Kernel CI coverage, 2026-10-27

The module-build coverage adapts Zagitta `6081407b312aa3139a2bed62bdda354f4ffddc1d`.
Eight distribution jobs build every unique header tree, including Ubuntu
22.04/24.04 GA and HWE and Arch current/LTS kernels. Each build cleans previous
outputs, selects the versioned GCC recorded by the headers when available,
and treats compiler warnings as errors. Expected dual-kernel jobs fail when
fewer than two distinct trees build. Behavioral tests cover aliases, paths
with spaces, missing compilers/headers, failures and stale module rejection.
The generated-input, firmware hash, package and Windows checks remain in place;
no runtime code, firmware pins, Windows boot path or suspend/resume support changes.
