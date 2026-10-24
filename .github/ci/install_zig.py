#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract the pinned host-test compiler into the CI runner's temp directory."""
import hashlib
import os
from pathlib import Path
import sys
import tarfile
import urllib.request
import zipfile

VERSION = "0.15.2"
PLATFORM, SHA256 = (("x86_64-windows", "3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c")
                    if sys.platform == "win32" else
                    ("x86_64-linux", "02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239"))
root = Path(os.environ["RUNNER_TEMP"]) / "gpu-unlock-zig"
root.mkdir(exist_ok=True)
name = f"zig-{PLATFORM}-{VERSION}"
archive = root / (name + (".zip" if sys.platform == "win32" else ".tar.xz"))
urllib.request.urlretrieve(f"https://ziglang.org/download/{VERSION}/{archive.name}", archive)
if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
    raise SystemExit("Zig archive checksum mismatch")
if sys.platform == "win32":
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(root)
else:
    with tarfile.open(archive) as bundle:
        bundle.extractall(root, filter="data")
with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as output:
    output.write(str(root / name) + "\n")
