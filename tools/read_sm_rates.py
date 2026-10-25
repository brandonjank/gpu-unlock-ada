#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read current SM issue-rate selectors using NVIDIA's public RM getter.

No BAR mapping, register write, firmware upload, reset, CUDA context or kernel.
Allocates only temporary RM client/device/subdevice handles, closed on exit.
Resolves the exact UUID to PCI address, device node and RM device/subdevice.
Refuses missing or ambiguous mappings; never scans for the first working GPU.
ABI: NVIDIA open-gpu-kernel-modules 610.43.03, ctrl2080gr.h and cl0080.h.
"""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import re
import stat
import subprocess

U32, U64 = C.c_uint32, C.c_uint64
GET_SM_RATES = 0x20801230
GET_UUID_INFO = 0x274
GET_PCI_INFO = 0x21B


class Alloc(C.Structure):
    _fields_ = [(name, U32) for name in ("root", "parent", "new", "cls")] + [
        ("params", U64), ("rights", U64), ("size", U32),
        ("flags", U32), ("status", U32)]


class Control(C.Structure):
    _fields_ = [(name, U32) for name in ("client", "obj", "cmd", "flags")] + [
        ("params", U64), ("size", U32), ("status", U32)]


class Device(C.Structure):
    _fields_ = [(name, U32) for name in ("device", "share", "target_client", "target_device", "flags")] + [
        ("va_size", U64), ("va_start", U64), ("va_limit", U64), ("va_mode", U32)]


class UuidInfo(C.Structure):
    _fields_ = [("uuid", C.c_uint8 * 256)] + [
        (name, U32) for name in ("flags", "gpu_id", "device", "subdevice")]


class PciInfo(C.Structure):
    _fields_ = [("gpu_id", U32), ("domain", U32), ("bus", C.c_uint16),
                ("slot", C.c_uint16)]


RATE_FIELDS = ("imla0", "fmla16", "dp", "fmla32", "ffma", "imla1", "imla2", "imla3", "imla4")


class Rates(C.Structure):
    _fields_ = [("route_flags", U32), ("padding", U32), ("route", U64)] + [
        (name, C.c_uint8) for name in RATE_FIELDS]


assert C.sizeof(Alloc) == 48 and C.sizeof(Control) == 32
assert C.sizeof(Device) == 56 and C.sizeof(Rates) == 32
assert Rates.imla0.offset == 16 and Rates.imla4.offset == 24
assert C.sizeof(UuidInfo) == 272 and UuidInfo.device.offset == 264
assert C.sizeof(PciInfo) == 12


def ioctl_number(number, structure):
    return (3 << 30) | (C.sizeof(structure) << 16) | (ord("F") << 8) | number


def call_ioctl(fd, number, structure, ioctl):
    buffer = bytearray(bytes(structure))
    ioctl(fd, number, buffer, True)
    C.memmove(C.addressof(structure), bytes(buffer), len(buffer))
    if structure.status:
        raise RuntimeError(f"RM request failed with status 0x{structure.status:x}")


def gpu_identity():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,name,pci.bus_id,driver_version,power.limit,clocks.gr,clocks.mem",
         "--format=csv,noheader,nounits"], check=True, capture_output=True, text=True, timeout=8)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def target_identity(expected_uuid):
    matches = [line for line in gpu_identity()
               if line.split(",", 1)[0].strip() == expected_uuid]
    if len(matches) != 1:
        raise RuntimeError("expected one GPU with the exact supplied UUID")
    fields = [part.strip() for part in matches[0].split(",")]
    if len(fields) != 7:
        raise RuntimeError("incomplete GPU identity")
    match = re.fullmatch(r"([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])", fields[2])
    if not match:
        raise RuntimeError("invalid GPU PCI address")
    pci = tuple(int(value, 16) for value in match.groups())
    if pci[2] > 31 or pci[3] != 0:
        raise RuntimeError("unsupported GPU PCI function")
    address = f"{pci[0]:04x}:{pci[1]:02x}:{pci[2]:02x}.{pci[3]}"
    info = Path("/proc/driver/nvidia/gpus") / address / "information"
    try:
        values = {}
        for line in info.read_text().splitlines():
            key, separator, value = line.partition(":")
            if separator:
                key = key.strip()
                if key in values:
                    raise RuntimeError("ambiguous driver GPU information")
                values[key] = value.strip()
        if values.get("GPU UUID") != expected_uuid:
            raise RuntimeError("driver UUID does not match the selected PCI address")
        minor_text = values.get("Device Minor", "")
        if not minor_text.isdecimal() or not 0 <= int(minor_text) < 255:
            raise RuntimeError("driver device minor is unavailable")
    except OSError as error:
        raise RuntimeError("native Linux driver GPU information is unavailable") from error
    return matches[0], pci, int(minor_text)


def root_control(fd, client, command, params, ioctl):
    expected = {GET_UUID_INFO: UuidInfo, GET_PCI_INFO: PciInfo}
    if command not in expected or type(params) is not expected[command]:
        raise ValueError("only typed read-only GPU identity queries are allowed")
    request = Control(client=client, obj=client, cmd=command,
                      params=C.addressof(params), size=C.sizeof(params))
    call_ioctl(fd, ioctl_number(0x2A, Control), request, ioctl)


def read_rates(expected_uuid, ioctl=None):
    identity, pci, minor = target_identity(expected_uuid)
    encoded = expected_uuid.encode("ascii")
    if not encoded or len(encoded) >= 256 or b"\0" in encoded:
        raise RuntimeError("invalid GPU UUID")
    if ioctl is None:
        import fcntl
        ioctl = fcntl.ioctl
    descriptors = []
    try:
        open_flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        ctl = os.open("/dev/nvidiactl", open_flags)
        descriptors.append(ctl)

        def allocate(root, parent, cls, params=None):
            request = Alloc(root=root, parent=parent, cls=cls,
                            params=C.addressof(params) if params is not None else 0,
                            size=C.sizeof(params) if params is not None else 0)
            call_ioctl(ctl, ioctl_number(0x2B, Alloc), request, ioctl)
            if not request.new:
                raise RuntimeError("RM returned an empty object handle")
            return request.new

        client = allocate(0, 0, 0x41)
        # Public ctrl0000gpu.h resolves UUID directly; device numbers, probe
        # order and /dev minors are independent namespaces.
        mapping = UuidInfo(device=0xFFFFFFFF, subdevice=0xFFFFFFFF)
        mapping.uuid[:len(encoded)] = encoded
        root_control(ctl, client, GET_UUID_INFO, mapping, ioctl)
        if (bytes(mapping.uuid).split(b"\0", 1)[0] != encoded or
                mapping.device >= 32 or mapping.subdevice >= 32):
            raise RuntimeError("invalid RM UUID mapping")
        location = PciInfo(gpu_id=mapping.gpu_id)
        root_control(ctl, client, GET_PCI_INFO, location, ioctl)
        if (location.gpu_id != mapping.gpu_id or
                (location.domain, location.bus, location.slot) != pci[:3]):
            raise RuntimeError("RM UUID/PCI mapping mismatch")
        device_fd = os.open(f"/dev/nvidia{minor}", open_flags)
        descriptors.append(device_fd)
        node = os.fstat(device_fd)
        if not stat.S_ISCHR(node.st_mode) or os.major(node.st_rdev) != 195 or os.minor(node.st_rdev) != minor:
            raise RuntimeError("NVIDIA device node does not match the driver minor")
        device = allocate(client, client, 0x80, Device(device=mapping.device))
        subdevice = allocate(client, device, 0x2080, U32(mapping.subdevice))
        rates = Rates()
        request = Control(client=client, obj=subdevice, cmd=GET_SM_RATES,
                          params=C.addressof(rates), size=C.sizeof(rates))
        call_ioctl(ctl, ioctl_number(0x2A, Control), request, ioctl)
        values = {name: getattr(rates, name) for name in RATE_FIELDS}
        if any(value > 6 for value in values.values()):
            raise RuntimeError("driver returned an unknown issue-rate encoding")
        return {"gpu": identity, "command": f"0x{GET_SM_RATES:x}",
                "rates": values, "meaning": "0=full; 1=half; 2=quarter; higher values are further reductions",
                "hardware_changes": False}
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-uuid", required=True)
    args = parser.parse_args()
    print(json.dumps(read_rates(args.expect_uuid)))


if __name__ == "__main__":
    main()
