"""Download the pinned Jackcess jars (Access file support) into java/lib, checking SHA-256.

Run before building the helper; CI does it too. Nothing is trusted unless the checksum matches.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "java" / "lib"
MAVEN = "https://repo1.maven.org/maven2/"
JARS = {
    "jackcess-4.0.8.jar": ("com/healthmarketscience/jackcess/jackcess/4.0.8/",
                           "bb84e5c7367dedf3a5cea7ad2d37e6874bb688f9003edb92749ef032be25671e"),
    "commons-lang3-3.17.0.jar": ("org/apache/commons/commons-lang3/3.17.0/",
                                 "6ee731df5c8e5a2976a1ca023b6bb320ea8d3539fbe64c8a1d5cb765127c33b4"),
    "commons-logging-1.3.4.jar": ("commons-logging/commons-logging/1.3.4/",
                                  "bc2dfe32f1ef06509e6a065144c1adf7b420eabf11a87f30bd127f8faa332016"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch() -> list[Path]:
    LIB.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (folder, digest) in JARS.items():
        target = LIB / name
        if not (target.exists() and sha256(target) == digest):
            with urllib.request.urlopen(MAVEN + folder + name, timeout=60) as response:
                target.write_bytes(response.read())
            if sha256(target) != digest:
                target.unlink()
                raise SystemExit(f"{name}: checksum mismatch, refusing to use it")
        paths.append(target)
    return paths


if __name__ == "__main__":
    for p in fetch():
        print(p)
    sys.exit(0)
