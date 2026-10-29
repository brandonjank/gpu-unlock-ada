#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a read-only USB probe, or a board-pinned experimental Windows unlocker."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
UEFI = ROOT / "windows/uefi"
COMMON = ["app_io", "format", "runtime", "sha256", "port", "compat", "research"]
CORE = ["vendor/unlock_610", "vendor/prep_610", "vendor/layout_610",
        "vendor/vbios_610", "vendor/gfw_eval"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def boot_profile(path: Path) -> dict:
    """Validate explicit private pins; never learn them from an executing EFI."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate boot profile field: {key}")
            result[key] = value
        return result
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(data, dict) or set(data) != {
            "esp_partition_guid", "boot_manager_bytes", "boot_manager_sha256"}:
        raise ValueError("boot profile requires exactly ESP GUID, boot-manager size and SHA-256")
    guid = uuid.UUID(data["esp_partition_guid"])
    size, digest = data["boot_manager_bytes"], data["boot_manager_sha256"]
    if guid.int == 0 or type(size) is not int or not 1048576 <= size <= 8388608:
        raise ValueError("boot profile needs a nonzero ESP GUID and a reviewed size of 1-8 MiB")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest) or int(digest, 16) == 0:
        raise ValueError("boot profile needs a nonzero whole-file SHA-256 (64 hex digits)")
    return dict(esp_partition_guid=str(guid), boot_manager_bytes=size,
                boot_manager_sha256=digest.lower())


def boot_profile_header(profile: dict) -> str:
    guid = uuid.UUID(profile["esp_partition_guid"])
    tail = ",".join(f"0x{x:02x}" for x in guid.bytes[8:])
    return ("// Private generated boot profile; do not publish.\n#pragma once\n"
            f"#define GU_WINDOWS_PARTITION_INITIALIZER {{{guid.time_low:#x},{guid.time_mid:#x},"
            f"{guid.time_hi_version:#x},{{{tail}}}}}\n"
            f"#define GU_WINDOWS_BOOTMGR_BYTES {profile['boot_manager_bytes']}U\n"
            f"#define GU_WINDOWS_BOOTMGR_SHA256 \"{profile['boot_manager_sha256']}\"\n")


def board_profile(run: Path) -> dict[str, int | str]:
    """Bind a build to complete, mutually consistent files from one probe run."""
    report = (run / "REPORT.TXT").read_text(encoding="ascii")
    if "PROBE ONLY:" not in report or "PROFILE complete=1" not in report:
        raise ValueError("a successful read-only probe run is required")
    if "PROBE FINAL status=0 GPU writes=0 DMA maps=0" not in report:
        raise ValueError("probe did not finish successfully without GPU writes")
    values = {}
    for key, value in re.findall(r"^PROFILE ([a-z0-9_]+)=([a-z0-9]+)$", report, re.M):
        if key in values:
            raise ValueError(f"duplicate profile field: {key}")
        values[key] = value
    for key, filename, length in [("config", "CONFIG.BIN", 256),
                                  ("rom", "ROM.BIN", None),
                                  ("prom", "PROM.BIN", 1048576)]:
        data = (run / filename).read_bytes()
        limit = 16 * 1048576 if key == "rom" else 1048576
        if (length is not None and len(data) != length) or not 0 < len(data) <= limit:
            raise ValueError(f"unexpected {filename} size")
        if sha256(data) != values.get(key + "_sha256"):
            raise ValueError(f"{filename} hash does not match the probe report")
    config = struct.unpack("<64I", (run / "CONFIG.BIN").read_bytes())
    numeric = ["segment", "bus", "device", "function", "bar_base", "bar_size",
               "bar_granularity", "chip", "vram_mib", "rom_bytes", "wpr2_hi", "ss0", "ss1"]
    profile = {key: int(values[key]) for key in numeric}
    if (config[0] != 0x268410DE or profile["chip"] != 0x192000A1 or
            config[2] >> 24 != 3 or config[1] & 6 != 2 or
            config[3] & 0x7F0000 or config[12] & 1 or
            profile["wpr2_hi"] >> 4 or profile["ss0"] & 0x88888888 or
            profile["ss1"] & ~7 or not 24512 <= profile["vram_mib"] <= 24576):
        raise ValueError("probe is not a cold, non-bus-mastering RTX 4090")
    if not (0 <= profile["segment"] <= 65535 and 0 <= profile["bus"] <= 255 and
            0 <= profile["device"] <= 31 and 0 <= profile["function"] <= 7):
        raise ValueError("invalid PCI address")
    base = config[4] & ~15
    kind = (config[4] >> 1) & 3
    if kind == 2:
        base |= config[5] << 32
    elif kind != 0:
        raise ValueError("unsupported BAR type")
    if (config[4] & 1 or not base or base != profile["bar_base"] or
            base % 0x1000000 or profile["bar_size"] != 0x1000000 or
            base + profile["bar_size"] > 2**64 or
            profile["bar_granularity"] not in (32, 64)):
        raise ValueError("invalid or inconsistent BAR0 mapping")
    rom = (run / "ROM.BIN").read_bytes()
    prom = (run / "PROM.BIN").read_bytes()
    if len(rom) != profile["rom_bytes"] or rom[:2] != b"\x55\xaa" or prom[:2] != b"\x55\xaa":
        raise ValueError("missing PCI ROM signatures or inconsistent ROM size")
    profile.update(board_id=config[0], board_subsystem=config[11],
                   class_revision=config[2], bar0_config=config[4],
                   rom_sha256=values["rom_sha256"], prom_sha256=values["prom_sha256"],
                   config_sha256=values["config_sha256"])
    return profile


def profile_header(profile: dict) -> str:
    names = {"board_id": "BOARD_ID", "board_subsystem": "BOARD_SUBSYSTEM", "chip": "BOARD_CHIP", "ss1": "COLD_SS1"}
    lines = ["// SPDX-License-Identifier: GPL-2.0-only", "#pragma once"]
    for key, value in profile.items():
        if key in {"config_sha256", "wpr2_hi", "ss0"}:
            continue
        name = names.get(key, key.upper())
        literal = json.dumps(value) if isinstance(value, str) else f"0x{value:x}" + ("U" if value <= 0xFFFFFFFF else "ULL")
        lines.append(f"#define GU_{name} {literal}")
    return "\n".join(lines) + "\n"


def inspect_pe(data: bytes) -> dict:
    """Reject a host executable accidentally produced instead of a relocatable EFI."""
    def u16(offset): return struct.unpack_from("<H", data, offset)[0]
    def u32(offset): return struct.unpack_from("<I", data, offset)[0]
    pe = u32(60)
    opt = pe + 24
    if (data[:2] != b"MZ" or data[pe:pe+4] != b"PE\0\0" or
            u16(pe+4) != 0x8664 or u16(opt) != 0x20B or u16(opt+68) != 10 or
            u16(opt+70) & 0x140 != 0x140 or u32(opt+112+5*8+4) == 0):
        raise ValueError("expected AMD64 EFI_APPLICATION with relocations, ASLR and NX")
    if any(data[opt+112+i*8:opt+120+i*8] != bytes(8) for i in (1, 12, 13)):
        raise ValueError("EFI application unexpectedly imports OS libraries")
    entry = u32(opt+16)
    sections = opt + u16(pe+20)
    if not any(u32(s+12) <= entry < u32(s+12)+u32(s+8) and u32(s+36) & 0x20000000
               for s in (sections+40*i for i in range(u16(pe+6)))):
        raise ValueError("EFI entry point is outside executable sections")
    return {"machine": "AMD64", "subsystem": "EFI_APPLICATION", "imports": False,
            "relocations": True, "size": len(data), "sha256": sha256(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["probe", "unlock"])
    parser.add_argument("--zig", default="zig", help="path to Zig 0.15.2 executable")
    parser.add_argument("--run", type=Path, help="GPU-UNLOCK/RUNxx directory from the probe")
    parser.add_argument("--boot-profile", type=Path, help="private reviewed Windows ESP/file pins (required for unlock)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / "build/windows" / args.mode).resolve()
    profile = None
    boot = None
    if args.mode == "unlock":
        if args.run is None:
            parser.error("unlock requires --run from this card's successful preboot probe")
        if args.boot_profile is None:
            parser.error("unlock requires --boot-profile; see windows/boot-profile.example.json")
        try:
            profile = board_profile(args.run)
            boot = boot_profile(args.boot_profile)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            parser.error(str(error))
    # Build into a new directory to keep each USB image and report paired.
    output.mkdir(parents=True, exist_ok=False)
    (output / "GPU-UNLOCK/ASSETS").mkdir(parents=True)
    (output / "EFI/BOOT").mkdir(parents=True)
    if profile:
        (output / "board_profile.h").write_text(profile_header(profile), encoding="ascii")
        (output / "boot_profile.h").write_text(boot_profile_header(boot), encoding="ascii")
    sources = COMMON + (["probe", "boot_tests", "checks", "ownership", "vendor/vbios_610", "vendor/gfw_eval"]
                        if args.mode == "probe" else ["app", "ownership", "checks"] + CORE)
    image = output / "EFI/BOOT/BOOTX64.EFI"
    flags = ["-target", "x86_64-uefi", "-std=c11", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-mno-red-zone", "-fshort-wchar", "-Os", "-g0",
             "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-D__KERNEL__",
             "-DGU_UEFI_PORT", "-DGU_TARGET_PCI_ID=0x268410deU", "-nostdlib"]
    if args.mode == "probe":
        flags.append("-DGU_PROBE_ONLY")
    includes = [output, UEFI, UEFI / "compat", UEFI / "edk2/MdePkg/Include",
                UEFI / "edk2/MdePkg/Include/X64"]
    subprocess.run([args.zig, "cc", *flags, *(f"-I{p}" for p in includes),
                    *(str(UEFI / (s + ".c")) for s in sources), "-o", str(image)], check=True)
    report = inspect_pe(image.read_bytes())
    report.update(mode=args.mode, profile=profile, boot_profile=boot, hardware_tested=False, uefi_vm_tested=False,
                  probe_version=4 if args.mode == "probe" else None,
                  builder_sha256=sha256(Path(__file__).read_bytes()),
                  zig_version=subprocess.check_output([args.zig, "version"], text=True).strip(),
                  source_sha256={str(p.relative_to(ROOT)): sha256(p.read_bytes())
                                 for p in sorted(UEFI.rglob("*"))
                                 if p.is_file() and p.suffix in {".c", ".h", ".inc"}})
    (output / "build-result.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE")
    shutil.copyfile(ROOT / "windows/THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
    shutil.copytree(UEFI / "LICENSES", output / "LICENSES")
    print(f"Built {image}\nSHA256 {report['sha256']}\nHardware validation pending.")


if __name__ == "__main__":
    main()
