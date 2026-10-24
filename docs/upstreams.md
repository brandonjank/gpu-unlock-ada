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

## Initial review, 2026-10-24

The direct Ada parent, WildFlash payload source and TOTORONG source match the
recorded integration revisions. Zagitta's current head is 22 commits ahead of
the older Linux transaction vendored by the Windows port. That comparison does
not describe the ancestry or integration status of the separate Ada Linux module.
Two candidates merit a focused review:

- [Older-kernel device claiming and firmware-set bus mastering](https://github.com/Zagitta/gpu-unlock/commit/d04f5a00f30d9bceec7069868a7504fd925dc7ad).
  Upstream accepts `PCI_UNKNOWN` only when PMCSR confirms D0, and clears
  firmware-set BME before claiming an unbound card. Review against the existing
  fail-closed guards in `kernel/gpu_unlock/unlock_610.c` and the separately
  retained Windows transaction. Add negative claim tests before considering a
  port; upstream's reported RTX 3090 result does not validate Ada or UEFI.
- [Unlock after suspend-to-RAM](https://github.com/Zagitta/gpu-unlock/commit/c274e74981d996e4b83266b43b9070804099ddae).
  Upstream adds a power-management notifier and a guarded resume path. This
  fork's `kernel/gpu_unlock/main.c` has no matching notifier. A future Linux
  adaptation needs Ada selector, firmware freshness, driver-ordering and DMA
  lifetime checks plus suspend/resume hardware validation. It does not establish
  a Windows runtime resume mechanism.

Neither candidate is integrated by the publication or monitoring setup.

## Local version control

`origin` points to this public fork; `upstream` points to JustAResearcher's Ada
fork. Additional source remotes are available for comparison. Normal development
uses small commits pushed to `origin`; updating an upstream remote never changes
the checked-out files by itself. Build outputs, raw ROM/firmware dumps, generated
EFI images and local credentials are excluded from new commits. Existing
sanitized published evidence remains tracked.
