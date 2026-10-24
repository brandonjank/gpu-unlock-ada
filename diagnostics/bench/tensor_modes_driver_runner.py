# SPDX-License-Identifier: GPL-2.0-only
"""Launch hash-pinned SM89 cubin MMA probes through the CUDA Driver API.

The GPU is exclusively reserved by the caller; this program never touches the
mining supervisor. It checks every output cell against an all-ones reference.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

BLOCKS = 1056
THREADS = 256
WARPS = BLOCKS * THREADS // 32
CHAINS = 8
MODES = (
    ("f16_f32", "bench_f16_f32", 16, False),
    ("tf32", "bench_tf32", 8, False),
    ("u4_s32", "bench_u4", 64, True),
)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def cuda_library():
    if os.name == "nt":
        # CUDA's Windows Driver API uses the Windows calling convention.
        return C.WinDLL("nvcuda.dll", winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
    try:
        return C.CDLL("libcuda.so.1")
    except OSError:
        # WSL projects this library even when ldconfig has not added its path.
        if "microsoft" not in platform.release().lower():
            raise
        return C.CDLL("/usr/lib/wsl/lib/libcuda.so.1")


def nvidia_smi():
    command = shutil.which("nvidia-smi")
    if command:
        return command
    wsl_command = Path("/usr/lib/wsl/lib/nvidia-smi")
    if wsl_command.is_file():
        return str(wsl_command)
    raise RuntimeError("nvidia-smi is missing; install the Windows host driver for WSL2")


def gpu_info(uuid, expected_power_limit, allow_unavailable=False):
    gpu = subprocess.run(
        [nvidia_smi(), "--id=" + uuid,
         "--query-gpu=uuid,name,pci.bus_id,driver_version,power.limit",
         "--format=csv,noheader,nounits"], check=True, capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    fields = [field.strip() for field in gpu.split(",")]
    if len(fields) != 5 or fields[0] != uuid or "\n" in gpu:
        raise ValueError("GPU identity mismatch: " + gpu)
    try:
        actual_power = float(fields[4])
    except ValueError:
        if not allow_unavailable:
            raise ValueError("power limit unavailable; check it on the Windows host, then use "
                             "--allow-unavailable-power-limit if appropriate") from None
        return gpu, False
    if not math.isfinite(actual_power) or abs(actual_power - expected_power_limit) >= 0.01:
        raise ValueError("power limit mismatch: " + gpu)
    return gpu, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cubin", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--expect-uuid", required=True)
    parser.add_argument("--expect-power-limit", type=float, required=True)
    parser.add_argument("--allow-unavailable-power-limit", action="store_true",
                        help="WSL2 may omit power telemetry; record it as unverified")
    parser.add_argument("--iters", type=int, default=20000)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--output", type=Path, help="save the successful JSON report")
    parser.add_argument("--include-bf16", action="store_true",
                        help="also run BF16 (requires a cubin built from the updated source)")
    args = parser.parse_args()
    if not args.cubin.is_file() or digest(args.cubin) != args.sha256.lower():
        parser.error("cubin is missing or its SHA-256 differs from --sha256")
    if not 0 < args.iters <= 20000 or not 1 <= args.reps <= 5:
        parser.error("--iters must be 1..20000 and --reps must be 1..5")
    if not 0 < args.expect_power_limit < float("inf"):
        parser.error("--expect-power-limit must be finite and positive")
    gpu, power_verified = gpu_info(args.expect_uuid, args.expect_power_limit,
                                   args.allow_unavailable_power_limit)

    lib = cuda_library()
    def api(name, argtypes):
        function = getattr(lib, name)
        function.argtypes = argtypes
        function.restype = C.c_int
        return function
    cuInit = api("cuInit", [C.c_uint])
    cuDeviceGetCount = api("cuDeviceGetCount", [C.POINTER(C.c_int)])
    cuDeviceGet = api("cuDeviceGet", [C.POINTER(C.c_int), C.c_int])
    class UUID(C.Structure):
        _fields_ = [("bytes", C.c_ubyte * 16)]
    cuDeviceGetUuid = api("cuDeviceGetUuid_v2", [C.POINTER(UUID), C.c_int])
    cuCtxCreate = api("cuCtxCreate_v2", [C.POINTER(C.c_void_p), C.c_uint, C.c_int])
    cuCtxDestroy = api("cuCtxDestroy_v2", [C.c_void_p])
    cuModuleLoad = api("cuModuleLoad", [C.POINTER(C.c_void_p), C.c_char_p])
    cuModuleUnload = api("cuModuleUnload", [C.c_void_p])
    cuModuleGetFunction = api("cuModuleGetFunction", [C.POINTER(C.c_void_p), C.c_void_p, C.c_char_p])
    cuMemAlloc = api("cuMemAlloc_v2", [C.POINTER(C.c_uint64), C.c_size_t])
    cuMemFree = api("cuMemFree_v2", [C.c_uint64])
    cuMemcpyDtoH = api("cuMemcpyDtoH_v2", [C.c_void_p, C.c_uint64, C.c_size_t])
    cuEventCreate = api("cuEventCreate", [C.POINTER(C.c_void_p), C.c_uint])
    cuEventRecord = api("cuEventRecord", [C.c_void_p, C.c_void_p])
    cuEventSynchronize = api("cuEventSynchronize", [C.c_void_p])
    cuEventElapsedTime = api("cuEventElapsedTime", [C.POINTER(C.c_float), C.c_void_p, C.c_void_p])
    cuEventDestroy = api("cuEventDestroy_v2", [C.c_void_p])
    cuCtxSynchronize = api("cuCtxSynchronize", [])
    cuLaunchKernel = api("cuLaunchKernel", [C.c_void_p, C.c_uint, C.c_uint, C.c_uint,
                                            C.c_uint, C.c_uint, C.c_uint, C.c_uint,
                                            C.c_void_p, C.POINTER(C.c_void_p), C.c_void_p])
    cuGetErrorString = api("cuGetErrorString", [C.c_int, C.POINTER(C.c_char_p)])
    def check(code, step):
        if code:
            message = C.c_char_p()
            cuGetErrorString(code, C.byref(message))
            raise RuntimeError(f"{step}: CUDA {code}: {message.value!r}")

    ctx = C.c_void_p()
    module = C.c_void_p()
    device_mem = C.c_uint64()
    started = time.time()
    report = {"gpu": gpu, "cubin_sha256": args.sha256, "iters": args.iters,
              "reps": args.reps, "blocks": BLOCKS, "threads": THREADS,
              "warps": WARPS, "chains": CHAINS, "modes": {},
              "platform": platform.platform(), "power_limit_verified": power_verified,
              "expected_power_limit_watts": args.expect_power_limit}
    check(cuInit(0), "cuInit")
    count = C.c_int()
    check(cuDeviceGetCount(C.byref(count)), "cuDeviceGetCount")
    device = C.c_int()
    matched = []
    for ordinal in range(count.value):
        check(cuDeviceGet(C.byref(device), ordinal), "cuDeviceGet")
        uuid = UUID()
        check(cuDeviceGetUuid(C.byref(uuid), device.value), "cuDeviceGetUuid")
        raw = bytes(uuid.bytes).hex()
        actual = "GPU-" + "-".join((raw[:8], raw[8:12], raw[12:16], raw[16:20], raw[20:]))
        if actual.lower() == args.expect_uuid.lower():
            matched.append(device.value)
    if len(matched) != 1:
        raise ValueError("expected GPU UUID is not uniquely visible to the CUDA Driver API")
    device.value = matched[0]
    try:
        check(cuCtxCreate(C.byref(ctx), 0, device.value), "cuCtxCreate")
        check(cuModuleLoad(C.byref(module), os.fsencode(args.cubin.resolve())), "cuModuleLoad")
        cells = BLOCKS * THREADS
        check(cuMemAlloc(C.byref(device_mem), cells * 4), "cuMemAlloc")
        modes = MODES + ((("bf16_f32", "bench_bf16_f32", 16, False),) if args.include_bf16 else ())
        for label, name, k, integer in modes:
            fn = C.c_void_p()
            check(cuModuleGetFunction(C.byref(fn), module, name.encode()), "cuModuleGetFunction " + name)
            iters = C.c_ulonglong(args.iters)
            params = (C.c_void_p * 2)(C.cast(C.byref(iters), C.c_void_p),
                                       C.cast(C.byref(device_mem), C.c_void_p))
            def launch():
                check(cuLaunchKernel(fn, BLOCKS, 1, 1, THREADS, 1, 1, 0, None, params, None),
                      "cuLaunchKernel " + name)
            launch()
            check(cuCtxSynchronize(), "warmup sync " + name)
            times = []
            for _ in range(args.reps):
                start = C.c_void_p()
                stop = C.c_void_p()
                check(cuEventCreate(C.byref(start), 0), "cuEventCreate start")
                check(cuEventCreate(C.byref(stop), 0), "cuEventCreate stop")
                try:
                    check(cuEventRecord(start, None), "cuEventRecord start")
                    launch()
                    check(cuEventRecord(stop, None), "cuEventRecord stop")
                    check(cuEventSynchronize(stop), "cuEventSynchronize")
                    ms = C.c_float()
                    check(cuEventElapsedTime(C.byref(ms), start, stop), "cuEventElapsedTime")
                    if not ms.value > 0:
                        raise RuntimeError("CUDA event returned an invalid duration")
                    times.append(float(ms.value))
                finally:
                    check(cuEventDestroy(stop), "cuEventDestroy stop")
                    check(cuEventDestroy(start), "cuEventDestroy start")
            if integer:
                host = (C.c_int32 * cells)()
            else:
                host = (C.c_float * cells)()
            check(cuMemcpyDtoH(C.cast(host, C.c_void_p), device_mem.value, cells * 4),
                  "cuMemcpyDtoH " + name)
            expected = 4 * CHAINS * args.iters * k
            mismatches = sum(1 for value in host if value != expected)
            if mismatches:
                raise RuntimeError(f"{name}: {mismatches} numerical mismatches; expected {expected}")
            ops = WARPS * args.iters * CHAINS * (16 * 8 * k * 2)
            rates = [ops / (ms * 1e9) for ms in times]
            report["modes"][label] = {"instruction": name, "k": k,
                                      "times_ms": times, "rates_Top_per_s": rates,
                                      "best_Top_per_s": max(rates),
                                      "expected_cell": expected,
                                      "cells_checked": cells,
                                      "mismatches": mismatches}
    finally:
        if device_mem.value:
            check(cuMemFree(device_mem.value), "cuMemFree")
        if module.value:
            check(cuModuleUnload(module), "cuModuleUnload")
        if ctx.value:
            check(cuCtxDestroy(ctx), "cuCtxDestroy")
    report["seconds"] = time.time() - started
    result = json.dumps(report)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
