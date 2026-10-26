# RTX 4090 Windows and WSL2 result — October 24, 2026

Local combined suite version 10 completed a preboot unlock on **one desktop
RTX 4090 with Secure Boot enabled on October 24, 2026**, then handed off to
Windows 11 with the stock NVIDIA 616.56 driver. Four CUDA probe modes passed
on native Windows and Ubuntu/WSL2, with zero mismatches across **2,162,688 output
cells checked after the unlock**. WSL2 used the Windows host GPU driver; the
Linux unlock module was not run inside WSL2.

This is an operator-reported experiment supported by selected local records.
The date appears in the run record and RUN08 firmware RTC calendar date; these
files do not independently establish publication time or priority. No claim of
being the first Windows or Secure Boot-enabled implementation is made.

## Tested image and publication boundary

The successful EFI came from **later local version 10 development**, beyond the
Windows implementation currently published in this repository. This update
publishes documentation and sanitized evidence only. The current public build
instructions do not reproduce that tested image. Its SHA-256 is:

```text
ff20becfcaf53529eea69e79f69653a9c9e5ec2bd04774fdf79914e53c187f3e
```

The image, firmware/ROM/PROM captures, private board profile, signing material
and complete machine logs are not included. The hash identifies the retained
local artifact; it is not a downloadable release or an independent attestation.

The tested path ran a firmware-authorized EFI application before Windows Boot
Manager. Both reports record `SecureBoot=1 status=0 firmware_policy_unchanged=1`.
Image authorization is specific to the image and firmware configuration; this
result does not establish Microsoft signing or compatibility with another
machine's trust configuration. See the [Windows port notes](../../../windows/README.md).

## Preboot observations

[RUN08](run08-diagnostics.txt) reports suite version 10, all 12 required
diagnostics passing, and the same-day RTC date. The subsequent
[RUN09 transaction](run09-transaction.txt) records one SEC2 payload execution,
SS0 `0x88888888` and SS1 `0x00000008` after both FLR and graphics-output-protocol
(GOP) reconnect, with `register_unlock_verified=1` and effective `readout1=0`.
The transaction completed with `quiesced=1 fault=0 retained=0 maps=0 FLR=1`
and final `status=0 stage=post-unlock-handoff attempted=1 driver_release=1 clean=1`.

The FBPA permission target remained `0xffffff0f`, rather than the expected
`0xffffffff`. The tested transaction explicitly treated this mismatch as
nonfatal; the other three targets matched. These records do not show all four
permission targets opening.

`windows_driver_verified=0` in the preboot log is intentional: selector readback
ends before Windows starts. Windows driver availability and CUDA output checks
are separate observations in the workload reports. No direct selector register
readback was performed after the Windows driver loaded.

## Workload observations

The two unlocked reports use the same SM89 cubin hash, 20,000 iterations,
three timing repetitions, 1,056 blocks, 256 threads and eight chains. Each of
FP16/FP32, BF16/FP32, TF32/FP32 and unsigned INT4/INT32 checks 270,336 output
cells per environment, with zero mismatches. The runner uses all-ones operands;
these checks do not establish general numerical correctness or application
stability. The recorded power limit was verified at 450 W in all four reports.

Observed best instruction issue rates after unlock (best of three repetitions):

| Mode | Windows 11 | Ubuntu/WSL2 | Unit |
|---|---:|---:|---|
| FP16 / FP32 accumulate | 288.93 | 301.50 | TFLOP/s |
| BF16 / FP32 accumulate | 316.35 | 329.16 | TFLOP/s |
| TF32 / FP32 accumulate | 150.65 | 150.73 | TFLOP/s |
| Unsigned INT4 / INT32 accumulate | 1263.25 | 1314.38 | TOP/s |

These are register-resident instruction probes, counting two operations per
multiply-accumulate without a sparsity multiplier. The JSON field
`rates_Top_per_s` is used for both floating-point and integer modes.

Earlier per-OS smoke baselines are included for transparency. Their private GPU
identity, driver, cubin hash, launch parameters and 450 W power limit match the
unlocked reports. Earlier clocks, thermal state and contention were uncontrolled,
and baseline timings were unusually low and variable. **These observations do
not establish a controlled speedup ratio, a general 2x gain, or an application,
gaming or inference improvement.** The evidence covers one board and one
successful unlock boot; repeated cold boots, suspend/resume, other boards,
driver updates and long-term stability remain unvalidated by this experiment.

## Files and sanitization

| File | Contents |
|---|---|
| [run08-diagnostics.txt](run08-diagnostics.txt) | Selected diagnostic lines and RTC date; time fields omitted |
| [run09-transaction.txt](run09-transaction.txt) | Selected security, permission, selector, cleanup and handoff lines |
| [unlock-v10-run09-windows.json](unlock-v10-run09-windows.json) | Native Windows post-unlock CUDA report |
| [unlock-v10-run09-wsl2.json](unlock-v10-run09-wsl2.json) | Ubuntu/WSL2 post-unlock CUDA report |
| [baseline-windows.json](baseline-windows.json) | Earlier uncontrolled Windows smoke baseline |
| [baseline-wsl2.json](baseline-wsl2.json) | Earlier uncontrolled WSL2 smoke baseline |
| [provenance.json](provenance.json) | Original source hashes, transformations, tested image hash and validation boundaries |
| [SHA256SUMS](SHA256SUMS) | Checksums of every other file in this directory |

Report excerpts retain selected original lines, apart from the explicitly
marked RTC time omission. Other log lines, firmware contents, host paths, PCI
locations, device paths, handles, memory addresses and board fingerprints are
omitted. In each workload JSON, the original GPU inventory string is replaced
with model, driver and power limit; the GPU UUID and PCI address are removed.
All other workload JSON values are unchanged, with formatting normalized.
The same private GPU inventory was checked across all four source reports
before export. Original source hashes were checked against the retained local
validation manifest, including the tested EFI hash. Checksums establish file
integrity, not independent reproduction of the experiment.

Check the published bundle from this directory:

```sh
sha256sum -c SHA256SUMS
```

The Ada payload derives from
[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker);
the retained loader components derive from
[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock). See the
[source notices](../../../windows/THIRD_PARTY_NOTICES.md) for attribution.
