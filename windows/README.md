# Experimental RTX 4090 Windows and WSL2 port

**The unlock is implemented as a preboot UEFI application, but has not been
boot-tested on this RTX 4090. It is not yet verified working on Windows.**
The Windows and Ubuntu/WSL2 CUDA validation runner has been tested on the same
RTX 4090. This establishes benchmark compatibility, not an unlock.

The original Linux module must run before NVIDIA binds the physical GPU.
Ubuntu inside WSL2 uses the Windows host's NVIDIA driver through GPU
paravirtualization; it cannot load this module against the host GPU. This port
instead runs before Windows Boot Manager, then lets Windows and WSL2 use the
normal Windows driver. Whether driver 616.56 preserves the override still needs
a boot-time hardware test.

The UEFI adapter derives from TOTORONG's published RTX 4080 experiment. It is
pinned here to desktop RTX 4090 `10de:2684`, chip `0x192000a1`, with a measured
board profile. No support is claimed for another GPU. It retains the upstream
single-display-GPU handoff restrictions: one physical GOP belonging to the
target GPU, one matching NVIDIA function and one Windows Boot Manager. It can
reject firmware ownership, capability layouts, or display configurations it does
not understand. See [source provenance](THIRD_PARTY_NOTICES.md).

## First step: read-only USB probe

Requirements: x64 UEFI firmware, Python 3.14+ on Windows, and
[Zig 0.15.2](https://ziglang.org/download/). Python 3.10+ and `zstd` also work for
building on Ubuntu. Zig can build the same x64 EFI application from either OS.
Run commands from the repository root.

```powershell
python windows/build.py probe --zig C:/path/to/zig.exe --output build/windows/probe
```

Each output directory must be new. The build validates the PE header, x64
architecture, EFI application subsystem, relocations, absence of OS imports,
and executable entry point. `build-result.json` records source and image hashes.

Copy the contents of that output directory onto an **existing FAT32 USB drive**:
`EFI/BOOT/BOOTX64.EFI` and the `GPU-UNLOCK` directory must be at its root. Keep
`build-result.json` with the copy. No formatting, EFI system partition edits,
boot-entry changes, or automatic reboot are performed by these tools.

The EFI is unsigned. Secure Boot can stay enabled if the firmware explicitly
authorizes this image, for example by enrolling its image hash through the BIOS.
Each rebuilt image may need authorization again. Both the probe and unlock
application log Secure Boot state and leave firmware trust settings unchanged.
They accept reported Secure Boot values 0 and 1, and reject unreadable or invalid
state. Firmware authentication still decides whether the application may run.
Before changing firmware boot/security settings, have your BitLocker recovery
key available. Choose the USB using the
firmware's one-time boot menu after a full power-off. Leave the normal Windows
boot entry intact.

The probe reads the PCI configuration, BAR0 descriptor, chip/VRAM/selector state,
PCI ROM and a 1 MiB PROM view. It writes new files only in `GPU-UNLOCK/RUNxx` on
the USB. It performs no GPU writes, DMA allocation, driver disconnection,
firmware transaction, FLR, or boot-variable changes. It requires memory decoding
already enabled and bus mastering disabled; it will not repair an unsuitable
state. Probe version 2 accepts disabled SS1 selectors such as 3 or 7; the earlier
version incorrectly required 7 and stopped before saving ROM data on this card.
The unlock build pins the measured SS1 value rather than copying another
board's default. A successful capture contains:

```text
GPU-UNLOCK/RUN00/REPORT.TXT
GPU-UNLOCK/RUN00/CONFIG.BIN
GPU-UNLOCK/RUN00/ROM.BIN
GPU-UNLOCK/RUN00/PROM.BIN
```

The report must end with successful probe status and contain
`PROFILE complete=1`. Power off, then boot Windows normally. Keep ROM and PROM
dumps local. A rejected probe is a reason to inspect its report, not to remove
the checks.

### Firmware backup and persistence research (probe version 3)

The research probe saves the firmware views exposed without changing the GPU:

| File | Contents |
|---|---|
| `ROM.BIN` | Entire UEFI-provided option-ROM buffer, up to a 16 MiB limit |
| `PROM.BIN`, `PROM2.BIN` | Two independent reads of the card's 1 MiB BAR0 PROM window |
| `CONFIG.BIN`, `BAR0.BIN` | Conventional 256-byte PCI configuration and BAR0 resource descriptor |
| `REGS0.BIN`, `REGS1.BIN` | Two snapshots of 47 selected identity, firmware, permission, fuse and speed-selector registers |
| `BOOT*.BIN` | Available BootCurrent/Next/Order and entries from up to 32 BootOrder numbers |
| `SECUREBOOT.BIN`, `SETUPMODE.BIN`, `AUDITMODE.BIN`, `DEPLOYEDMODE.BIN` | Available UEFI security-state variables |
| `TIME.BIN`, `OSINDIC.BIN` | Available firmware clock and supported OS indications |
| `REPORT.TXT` | Firmware version/vendor, PCI ROM-source attributes, raw read statuses, hashes and capture outcomes |

Every binary save is flushed, checked for exact size, and read back from USB for
byte comparison before the report records its SHA-256 as verified. The second
PROM read is compared with the first. Missing optional UEFI variables and
protected/inaccessible register reads are recorded; they do not imply zero data.
Snapshots use only the register offsets already sampled by this repository's
diagnostic tooling and known Falcon status registers. No broad MMIO/VRAM sweep,
indirect firmware-memory access, SPI transaction, flash write, fuse programming,
driver disconnection, reset, firmware execution, or boot-variable write occurs.
If an unlock eligibility check fails, the probe can still save backup/research
data; the unlock profile builder continues to reject unsuitable states.

These files are **firmware-view backups, not a proven complete, restorable SPI
flash image**. UEFI's ROM buffer may originate from a platform copy, and the
mapped PROM window can expose only part of the image. Protected internal firmware
is outside this capture. Do not use these files as flashing inputs merely because
their hashes verify. Keep the captures local and copy them to another disk after
returning to Windows.

Verify and summarize a capture without changing it:

```powershell
python windows/inspect_capture.py J:/GPU-UNLOCK/RUN02 --output build/windows/capture-summary.json
```

The register files use a 16-byte little-endian header (`GUR1`, version 1, count,
stride 16), then records of `uint32 offset`, `uint32 value`, `uint64 EFI_STATUS`.
The analyzer validates their bounds, verifies the file hashes, compares PROM
copies and register snapshots, and lists recognizable PCI ROM image headers.

For persistence, this evidence helps evaluate a repeatable pre-Windows boot
application and whether an override survives handoff/reset. A truly permanent
firmware-level unlock remains unproven. A valid ROM backup alone does not show
that firmware can be modified or that an override survives loss of power.

## Build the board-specific unlock application

Use the successful capture from **this exact card**. For example, if the USB is
`E:`, build a separate output:

```powershell
python windows/build.py unlock --zig C:/path/to/zig.exe --run E:/GPU-UNLOCK/RUN00 --output build/windows/unlock
python windows/prepare_assets.py build/windows/unlock/GPU-UNLOCK/ASSETS
```

The builder verifies capture hashes and consistency, then embeds the PCI
address, subsystem, chip revision, BAR0 mapping, VRAM size, ROM size/hash, and
complete PROM hash. The generated profile is a measured compatibility guard;
it is not evidence that the firmware transaction will succeed. Captures are
local input, not authenticated attestations. Firmware/BIOS changes or PCI
relocation can require another probe and rebuild.

`prepare_assets.py` downloads the same pinned NVIDIA 610.43.03 inputs as the
Linux project, verifies their SHA-256 hashes, and generates assets locally.
On native Windows, Python 3.14 supplies Zstandard support. On older Python in
Ubuntu, install `zstd`. `--offline --cache PATH` reuses verified inputs.
No NVIDIA installer or display-driver installation is run. Firmware assets
retain the NVIDIA license and must remain local.

Copy this separate build to a FAT32 USB, preserving the probe capture elsewhere.
The unlock program runs preflight checks, preloads Windows Boot Manager and asks
for a manual **U** keypress. Only then can it disconnect the target firmware
driver and attempt one firmware transaction. It verifies payload marker/HALT and
required permissions, writes selectors, disables bus mastering, performs FLR,
checks quiescence, releases DMA mappings, reconnects GOP and starts Windows.
The display may go blank during that handoff. An uncertain DMA/firmware state
halts and retains buffers until power-off; there is no automatic retry.

Selector rejection is logged while the program still attempts the inherited
verified recovery path. Returning to Windows alone does not establish success.
Look for `register_unlock_verified=1` at both `POST-FLR` and `POST-GOP`, then
validate performance and numerical results after Windows loads. The effective
readout check covers all nine 3-bit fields at BAR0 `0x823818`. The retained UEFI
transaction is an older implementation than the current Linux core; it has not
received equivalent full-transaction or hardware validation in this port.

Boot failure, display loss and hardware/data damage are possible during an
experimental unlock. Do not use the unlock application as the default boot path
until this exact card has passed a controlled test. A normal cold boot through
the original Windows entry provides the stock comparison path; persistence
across reboot, sleep, hibernation, or driver updates is unverified.

## Validate from Windows and Ubuntu/WSL2

Build the probe kernels with the CUDA toolkit. In a Visual Studio x64 developer
terminal on Windows (CUDA needs the MSVC host compiler):

```powershell
nvcc --cubin -arch=sm_89 -O3 -std=c++17 -o build/windows/tensor_modes_issue_sm89.cubin diagnostics/bench/tensor_modes_issue.cu
nvidia-smi --query-gpu=uuid,power.limit --format=csv,noheader,nounits
Get-FileHash build/windows/tensor_modes_issue_sm89.cubin -Algorithm SHA256
python diagnostics/bench/tensor_modes_driver_runner.py build/windows/tensor_modes_issue_sm89.cubin --sha256 YOUR_HASH --expect-uuid YOUR_GPU_UUID --expect-power-limit YOUR_WATTS --include-bf16 --output build/windows/stock-windows.json
```

The same cubin runs in Ubuntu/WSL2 using `python3` and Linux paths, for example
from `/mnt/d/Projects/4090 GPU Unlock`. Install only the CUDA **toolkit** inside
WSL2 if compiling there; do not install a Linux NVIDIA display driver.
The runner uses `nvcuda.dll` on Windows and the projected `libcuda.so.1` on WSL2.
It matches the CUDA device's UUID, not a guessed ordinal. It checks the cubin
hash, power cap and every output cell; failures remain active with `python -O`.
`--include-bf16` requires a cubin built from the updated source; it is optional
so previous three-mode cubins remain usable.

If WSL2 reports no power limit, the runner stops. After checking the actual cap
on Windows, an explicit `--allow-unavailable-power-limit` can run the test and
marks `power_limit_verified=false` in its report. It never changes power/clock
settings. Use the same card, cubin, driver, power cap and clock policy for matched
stock/unlocked runs **within each OS**. Windows and WSL timings are separate
baselines. Instruction issue rates and all-ones checks do not establish general
application speedup, general GEMM correctness, or long-term stability.

## Development checks

```powershell
python windows/test.py --zig C:/path/to/zig.exe
python windows/test.py --zig C:/path/to/zig.exe --wsl YOUR_DISTRO
```

The first command runs Python profile/runner checks, simulated UEFI probe/PCI
guard checks and four portable retained kernel components. The second also
cross-compiles all seven retained Linux component tests and runs them in WSL2.
Those tests use mocked hardware. They do not execute the UEFI application under
firmware, prove Windows handoff, or validate the full UEFI firmware transaction.

References: [NVIDIA CUDA on WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html),
[Microsoft CUDA on WSL](https://learn.microsoft.com/en-us/windows/ai/directml/gpu-cuda-in-wsl),
[TOTORONG source](https://huggingface.co/TOTORONG/AD103_win_unlocker).
