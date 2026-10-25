# SPDX-License-Identifier: GPL-2.0-only
import ctypes as C
import importlib.util
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest import TestCase, mock

spec = importlib.util.spec_from_file_location("sm_rates", Path(__file__).resolve().parents[1] / "tools/read_sm_rates.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
A = "GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ROW_A = f"{A}, card-A, 00000000:01:00.0, 610.43.03, 450, 2000, 10000"
ROW_B = f"{B}, card-B, 00000000:09:00.0, 610.43.03, 450, 2000, 10000"


class SmRateProbeTests(TestCase):
    def run_probe(self, *, failure=None):
        commands, instances, paths = [], [], []
        def ioctl(fd, code, buffer, mutate):
            self.assertEqual(fd, 7)
            if code == probe.ioctl_number(0x2B, probe.Alloc):
                p = probe.Alloc.from_buffer(buffer)
                self.assertIn(p.cls, (0x41, 0x80, 0x2080))
                if p.cls == 0x80:
                    instances.append(("device", C.cast(p.params, C.POINTER(probe.Device)).contents.device))
                if p.cls == 0x2080:
                    instances.append(("subdevice", C.cast(p.params, C.POINTER(probe.U32)).contents.value))
                p.new = 100
            else:
                self.assertEqual(code, probe.ioctl_number(0x2A, probe.Control))
                p = probe.Control.from_buffer(buffer)
                commands.append(p.cmd)
                if p.cmd == probe.GET_UUID_INFO:
                    params = C.cast(p.params, C.POINTER(probe.UuidInfo)).contents
                    self.assertEqual(bytes(params.uuid).split(b"\0")[0], B.encode())
                    params.gpu_id, params.device, params.subdevice = 0x1234, 5, 2
                    if failure == "uuid":
                        p.status = 0x56
                elif p.cmd == probe.GET_PCI_INFO:
                    params = C.cast(p.params, C.POINTER(probe.PciInfo)).contents
                    self.assertEqual(params.gpu_id, 0x1234)
                    params.domain, params.bus, params.slot = 0, 9, 0
                    if failure == "pci":
                        params.bus = 1
                elif p.cmd == probe.GET_SM_RATES:
                    C.cast(p.params, C.POINTER(probe.Rates)).contents.fmla32 = 1
                    if failure == "getter":
                        p.status = 0x56
                else:
                    self.fail("unexpected ioctl")
        def opened(path, flags):
            paths.append(path)
            if failure == "open" and path != "/dev/nvidiactl":
                raise OSError("open failed")
            return 7 if path == "/dev/nvidiactl" else 8
        with mock.patch.object(probe, "gpu_identity", return_value=[ROW_A, ROW_B]), mock.patch.object(probe.Path, "read_text", return_value=f"GPU UUID: {B}\nDevice Minor: 7\n"), mock.patch.object(probe.os, "open", side_effect=opened), mock.patch.object(probe.os, "fstat", return_value=SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=7)), mock.patch.object(probe.os, "major", return_value=195, create=True), mock.patch.object(probe.os, "minor", return_value=6 if failure=="node" else 7, create=True), mock.patch.object(probe.os, "close") as close:
            if failure:
                with self.assertRaises((RuntimeError, OSError)):
                    probe.read_rates(B, ioctl)
                result = None
            else:
                result = probe.read_rates(B, ioctl)
            self.assertEqual(close.call_args_list, [mock.call(fd) for fd in ([8,7] if len(paths)==2 and failure!="open" else [7])])
        return result, commands, instances, paths

    def test_two_supported_gpus_select_uuid_not_order_or_minor(self):
        result, commands, instances, paths = self.run_probe()
        self.assertEqual(result["gpu"], ROW_B)
        self.assertEqual(result["rates"]["fmla32"], 1)
        self.assertEqual(instances, [("device",5),("subdevice",2)])
        self.assertEqual(paths, ["/dev/nvidiactl","/dev/nvidia7"])
        self.assertEqual(commands, [probe.GET_UUID_INFO,probe.GET_PCI_INFO,probe.GET_SM_RATES])

    def test_mapping_failures_stop_before_device_allocation_and_getter(self):
        for failure in ("uuid","pci","node","open"):
            with self.subTest(failure=failure):
                _, commands, instances, _ = self.run_probe(failure=failure)
                self.assertNotIn(probe.GET_SM_RATES,commands)
                self.assertEqual(instances,[])

    def test_failed_getter_does_not_report_zero_as_full_speed(self):
        self.run_probe(failure="getter")

    def test_absent_duplicate_and_incomplete_identity_open_no_nodes(self):
        for rows in ([ROW_A], [ROW_B,ROW_B], [f"{B}, incomplete"]):
            with self.subTest(rows=rows), mock.patch.object(probe,"gpu_identity",return_value=rows), mock.patch.object(probe.os,"open") as opened:
                with self.assertRaises(RuntimeError):
                    probe.read_rates(B)
                opened.assert_not_called()

    def test_missing_ambiguous_or_wrong_proc_mapping_opens_no_nodes(self):
        for info in ("Device Minor: 7\n",f"GPU UUID: {A}\nDevice Minor: 7\n",f"GPU UUID: {B}\nDevice Minor: 7\nDevice Minor: 9\n",f"GPU UUID: {B}\nDevice Minor: N/A\n"):
            with self.subTest(info=info), mock.patch.object(probe,"gpu_identity",return_value=[ROW_B]), mock.patch.object(probe.Path,"read_text",return_value=info), mock.patch.object(probe.os,"open") as opened:
                with self.assertRaises(RuntimeError):
                    probe.read_rates(B)
                opened.assert_not_called()

    def test_identity_query_allowlist_and_abi(self):
        self.assertEqual((C.sizeof(probe.UuidInfo),C.sizeof(probe.PciInfo)),(272,12))
        with self.assertRaises(ValueError):
            probe.root_control(7,1,0xdeadbeef,probe.UuidInfo(),mock.Mock())
