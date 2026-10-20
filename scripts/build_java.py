"""Build the Access helper (build/java/FolioAccess.jar) and, for the Windows installer, a
small bundled Java runtime (build/jre).

    python scripts/build_java.py            # the helper jar
    python scripts/build_java.py --runtime  # also a trimmed runtime with jlink (needs a full JDK)

The jar holds java/src/FolioAccess.java plus the pinned Jackcess jars (fetched and
checksummed by fetch_jackcess.py).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_jackcess import fetch  # noqa: E402

BUILD = ROOT / "build"
CLASSES = BUILD / "java" / "classes"
JAR = BUILD / "java" / "FolioAccess.jar"
RUNTIME = BUILD / "jre"
RELEASE = "11"  # the oldest Java the helper has to run on


def _java_bin(name: str) -> str | None:
    exe = name + (".exe" if sys.platform == "win32" else "")
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / exe).is_file():
        return str(Path(home) / "bin" / exe)
    return shutil.which(name)


def _compile(libs: list[Path]) -> None:
    shutil.rmtree(CLASSES, ignore_errors=True)
    CLASSES.mkdir(parents=True)
    cp = os.pathsep.join(str(p) for p in libs)
    source = str(ROOT / "java" / "src" / "FolioAccess.java")
    javac = _java_bin("javac")
    if javac:
        cmd = [javac]
    else:  # a JRE that still carries the compiler module can do it
        java = _java_bin("java")
        if not java:
            raise SystemExit("Java not found: install a JDK (for example openjdk-17-jdk-headless)")
        cmd = [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"]
    common = ["-Xlint:-options", "-cp", cp, "-d", str(CLASSES), source]
    try:
        subprocess.run([*cmd, "--release", RELEASE, *common], check=True)
    except subprocess.CalledProcessError:  # a JRE-only install lacks the --release tables
        subprocess.run([*cmd, "-source", RELEASE, "-target", RELEASE, *common], check=True)


def build_jar() -> Path:
    libs = fetch()
    _compile(libs)
    JAR.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(JAR, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("META-INF/MANIFEST.MF",
                     "Manifest-Version: 1.0\nMain-Class: FolioAccess\nMulti-Release: true\n")
        seen.add("META-INF/MANIFEST.MF")
        for path in sorted(CLASSES.rglob("*.class")):
            name = path.relative_to(CLASSES).as_posix()
            out.write(path, name)
            seen.add(name)
        for lib in libs:  # the dependencies are folded in: one file to ship
            with zipfile.ZipFile(lib) as z:
                for info in z.infolist():
                    name = info.filename
                    if info.is_dir() or name in seen or name.endswith("module-info.class"):
                        continue  # one merged jar can't be several modules
                    if name.upper().startswith("META-INF/") and (
                            name.upper().endswith((".SF", ".RSA", ".DSA", ".MF"))):
                        continue
                    out.writestr(name, z.read(name))
                    seen.add(name)
    return JAR


def build_runtime() -> Path:
    jlink, jdeps = _java_bin("jlink"), _java_bin("jdeps")
    home = os.environ.get("JAVA_HOME")
    if not (jlink and jdeps and home):
        raise SystemExit("jlink/jdeps/JAVA_HOME not found: a full JDK (17 or newer) is needed "
                         "to bundle a Java runtime")
    modules = subprocess.run(
        [jdeps, "--multi-release", RELEASE, "--ignore-missing-deps", "--print-module-deps",
         str(JAR)], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    modules = ",".join(sorted(set(modules.split(",")) | {"java.base", "java.logging"}))
    shutil.rmtree(RUNTIME, ignore_errors=True)
    subprocess.run([jlink, "--add-modules", modules, "--output", str(RUNTIME), "--strip-debug",
                    "--no-header-files", "--no-man-pages", "--compress=2"], check=True)
    return RUNTIME


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true", help="also bundle a Java runtime")
    args = parser.parse_args()
    print(build_jar())
    if args.runtime:
        print(build_runtime())


if __name__ == "__main__":
    main()
