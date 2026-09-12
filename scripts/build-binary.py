#!/usr/bin/env python3
"""GE build script — builds the standalone binary and Windows installer.

Usage:
    python build.py              # build binary only
    python build.py --installer  # build binary + installer
    python build.py --clean      # clean build artifacts first
    python build.py --all        # clean + build binary + installer

Prerequisites:
    pip install pyinstaller
    # For installer: Inno Setup (iscc) must be on PATH
    # Download from: https://jrsoftware.org/isinfo.php

This script:
1. Builds ge.exe using PyInstaller (standalone binary bundling Python + pyeffic)
2. Optionally builds a Windows installer using Inno Setup
3. Reports the output locations
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def run(cmd: list[str], cwd: Path | None = None) -> int:
    """Run a command and return its exit code."""
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return r.returncode


def clean() -> None:
    """Remove build artifacts."""
    print("=== Cleaning build artifacts ===")
    for d in [DIST, BUILD, ROOT / "__pycache__", ROOT / "pyeffic" / "__pycache__"]:
        if d.exists():
            print(f"  removing {d}")
            shutil.rmtree(d, ignore_errors=True)
    # remove .pyc files
    for pyc in ROOT.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)
    print("  done")


def build_binary() -> bool:
    """Build ge.exe using PyInstaller."""
    print("=== Building ge.exe (standalone binary) ===")

    # check pyinstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("  PyInstaller not found. Installing...")
        if run([sys.executable, "-m", "pip", "install", "pyinstaller"]) != 0:
            print("  ERROR: Failed to install PyInstaller")
            return False

    # run pyinstaller
    spec = ROOT / "ge.spec"
    if not spec.exists():
        print(f"  ERROR: {spec} not found")
        return False

    rc = run([sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm",
              "--distpath", str(DIST), "--workpath", str(BUILD)])
    if rc != 0:
        print("  ERROR: PyInstaller build failed")
        return False

    exe = DIST / "ge" / "ge.exe"
    if not exe.exists():
        print(f"  ERROR: {exe} not found after build")
        return False

    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"  Built: {exe} ({size_mb:.1f} MB)")
    return True


def build_installer() -> bool:
    """Build the Windows installer using Inno Setup."""
    print("=== Building Windows installer ===")

    # find iscc (Inno Setup compiler)
    iscc = shutil.which("iscc")
    if not iscc:
        # try common install paths
        for p in [
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
            r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        ]:
            if Path(p).exists():
                iscc = p
                break

    if not iscc:
        print("  ERROR: Inno Setup (iscc) not found.")
        print("  Install from: https://jrsoftware.org/isinfo.php")
        return False

    iss = ROOT / "installer" / "ge.iss"
    if not iss.exists():
        print(f"  ERROR: {iss} not found")
        return False

    # check that the binary was built
    if not (DIST / "ge" / "ge.exe").exists():
        print("  ERROR: ge.exe not found. Run 'python build.py' first.")
        return False

    rc = run([iscc, str(iss)], cwd=ROOT)
    if rc != 0:
        print("  ERROR: Inno Setup build failed")
        return False

    installer = ROOT / "installer" / "Output" / "GE-Setup-1.0.0.exe"
    if installer.exists():
        size_mb = installer.stat().st_size / (1024 * 1024)
        print(f"  Built: {installer} ({size_mb:.1f} MB)")
        return True
    else:
        print("  WARNING: Installer not found at expected path")
        return False


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Build GE standalone binary and installer")
    p.add_argument("--clean", action="store_true", help="clean build artifacts first")
    p.add_argument("--installer", action="store_true", help="also build Windows installer")
    p.add_argument("--all", action="store_true", help="clean + build binary + installer")
    args = p.parse_args()

    if args.all:
        args.clean = True
        args.installer = True

    if args.clean:
        clean()

    if not build_binary():
        return 1

    if args.installer:
        if not build_installer():
            return 1

    print("\n=== Build complete ===")
    print(f"  Binary:    {DIST / 'ge' / 'ge.exe'}")
    if args.installer:
        print(f"  Installer: {ROOT / 'installer' / 'Output' / 'GE-Setup-1.0.0.exe'}")
    print("\nTo test the binary:")
    print(f'  "{DIST / "ge" / "ge.exe"}" compilers')
    print(f'  "{DIST / "ge" / "ge.exe"}" build examples/myrent.ge.py --run')

    return 0


if __name__ == "__main__":
    sys.exit(main())
