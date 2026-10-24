#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify a boot capture and summarize firmware views without modifying them."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def digest(data):
    return hashlib.sha256(data).hexdigest()


def registers(data):
    if len(data) < 16:
        raise ValueError("truncated register snapshot")
    magic, version, count, stride = struct.unpack_from("<4I", data)
    if magic != 0x31525547 or version != 1 or stride != 16 or count > 128 or len(data) != 16 + count * stride:
        raise ValueError("invalid register snapshot format")
    return [{"offset": f"0x{off:08x}", "value": f"0x{value:08x}", "status": f"0x{status:x}"}
            for off, value, status in struct.iter_unpack("<IIQ", data[16:])]


def rom_images(data):
    images = []
    pos = 0
    for _ in range(32):
        if pos + 0x1A > len(data) or data[pos:pos+2] not in (b"\x55\xaa", b"VN", b"\x77\xbb"):
            break
        pcir = pos + struct.unpack_from("<H", data, pos+0x18)[0]
        if pcir + 0x16 > len(data) or data[pcir:pcir+4] not in (b"PCIR", b"NPDS", b"RGIS"):
            break
        size = struct.unpack_from("<H", data, pcir+0x10)[0] * 512
        if not size or pos + size > len(data):
            break
        last = bool(data[pcir+0x15] & 0x80)
        images.append({"offset": pos, "bytes": size, "code_type": data[pcir+0x14],
                       "last": last, "byte_sum_mod_256": sum(data[pos:pos+size]) % 256})
        if last:
            break
        pos += size
    return images


def inspect(run):
    run = Path(run)
    report = (run / "REPORT.TXT").read_text(encoding="ascii")
    result = {"capture_files": {}, "full_spi_flash_backup_established": False,
              "persistent_unlock_established": False,
              "profile_complete": "PROFILE complete=1" in report}
    for name, size, sha in re.findall(r"^CAPTURE file=([A-Z0-9.-]+) bytes=(\d+) sha256=([a-f0-9]{64}) verified=1$", report, re.M):
        if name in result["capture_files"]:
            raise ValueError(f"duplicate capture record: {name}")
        data = (run / name).read_bytes()
        if len(data) != int(size) or digest(data) != sha:
            raise ValueError(f"backup verification failed: {name}")
        result["capture_files"][name] = {"bytes": len(data), "sha256": sha, "verified": True}
    if not result["capture_files"]:
        raise ValueError("no hashed capture files found")
    for name in ("ROM.BIN", "PROM.BIN"):
        if name in result["capture_files"]:
            result["capture_files"][name]["pci_rom_images"] = rom_images((run/name).read_bytes())
    if "PROM.BIN" in result["capture_files"] and "PROM2.BIN" in result["capture_files"]:
        result["prom_repeat_identical"] = (run/"PROM.BIN").read_bytes() == (run/"PROM2.BIN").read_bytes()
    if "CONFIG.BIN" in result["capture_files"]:
        data = (run/"CONFIG.BIN").read_bytes()
        if len(data) != 256:
            raise ValueError("invalid conventional PCI configuration size")
        c = struct.unpack("<64I", data)
        result["pci"] = {"vendor": f"{c[0]&65535:04x}", "device": f"{c[0]>>16:04x}",
                         "subsystem_vendor": f"{c[11]&65535:04x}", "subsystem_device": f"{c[11]>>16:04x}",
                         "revision": c[2]&255, "command": c[1]&65535}
    for name in ("REGS0.BIN", "REGS1.BIN"):
        if name in result["capture_files"]:
            result[name] = registers((run/name).read_bytes())
    if "REGS0.BIN" in result and "REGS1.BIN" in result:
        result["changed_registers"] = [{"before": before, "after": after}
                                      for before, after in zip(result["REGS0.BIN"], result["REGS1.BIN"])
                                      if before != after]
    for name in ("BOOTORDER.BIN", "BOOTCURRENT.BIN", "BOOTNEXT.BIN"):
        if name in result["capture_files"]:
            data = (run/name).read_bytes()
            if len(data) % 2:
                raise ValueError(f"invalid boot-number array: {name}")
            result[name] = [f"Boot{n:04X}" for (n,) in struct.iter_unpack("<H", data)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, help="save a new JSON summary")
    args = parser.parse_args()
    result = inspect(args.run)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")


if __name__ == "__main__": main()
