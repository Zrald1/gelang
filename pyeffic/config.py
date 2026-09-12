"""Configuration and compiler detection for pyeffic.

Toolchain detection is version-adaptive: it finds compilers on PATH or in
the local tools/ directory regardless of their version. Minimum supported
versions are checked and warnings are issued if a toolchain is too old,
but detection itself never fails due to a version mismatch.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---- Minimum supported versions per toolchain ----
# These are minimums — any version >= these will work.
# Updated toolchains should be backward-compatible per each language's semver policy.
MIN_VERSIONS: dict[str, str] = {
    "rustc": "1.70.0",     # Rust 1.70+ (stabilized many features we use)
    "cpp": "10.0.0",      # clang 10+ / GCC 10+ / MSVC 2019+
    "dotnet": "8.0.0",    # .NET 8+ for NativeAOT
    "zig": "0.13.0",      # Zig 0.13+ (API stabilized enough for our use)
    "go": "1.21.0",       # Go 1.21+ (toolchain management, go.mod required)
    "kotlinc": "2.0.0",   # Kotlin 2.0+ (stable Kotlin/Native @CName)
}


@dataclass
class ToolchainInfo:
    """Information about a detected toolchain."""
    path: str
    version: str = "unknown"
    is_supported: bool = True
    warning: str = ""


@dataclass
class CompilerInfo:
    rustc: str | None = None
    cpp: str | None = None  # one of g++/clang++/cl
    cpp_kind: str | None = None  # "gcc" | "clang" | "msvc"
    dotnet: str | None = None  # .NET SDK for C# NativeAOT
    zig: str | None = None  # Zig compiler
    go: str | None = None  # Go compiler
    kotlinc: str | None = None  # Kotlin compiler (kotlinc-native)
    # version info for each toolchain
    versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Config:
    out_dir: Path = field(default_factory=lambda: Path("build"))
    #: platform bucket: "desktop" | "web" | "mobile"
    #: artifacts land in <out_dir>/<target>/ so a multi-target project stays
    #: readable:
    #:     build/desktop/backend/   generated native sources
    #:     build/desktop/obj/       object files
    #:     build/desktop/bin/       executables
    #:     build/web/...            web build
    #:     build/mobile/...         Flutter project
    target: str = "desktop"
    keep_sources: bool = True
    run_after_compile: bool = False
    force_backend: str | None = None  # "rust"|"cpp"|"csharp"|"zig"|"go"|"kotlin"|None (auto)
    do_research: bool = True
    research_timeout: float = 8.0
    opt_level: str = "3"  # -O3 / -C opt-level=3

    @property
    def target_dir(self) -> Path:
        """Root of this target's artifacts: <out_dir>/<target>."""
        return self.out_dir / self.target

    def out(self, *parts: str) -> Path:
        """A path under the target directory, with parents created."""
        p = self.target_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def bin_dir(self) -> Path:
        """Where executables go: <out_dir>/<target>/bin."""
        d = self.target_dir / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def obj_dir(self) -> Path:
        """Where object files go: <out_dir>/<target>/obj."""
        d = self.target_dir / "obj"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def backend_dir(self) -> Path:
        """Where generated sources go: <out_dir>/<target>/backend."""
        d = self.target_dir / "backend"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---- Tool finding ----

def _find_tool(name: str, subdir: str = "") -> str | None:
    """Find a tool on PATH or in the local tools directory.

    Searches in this order:
    1. System PATH (shutil.which)
    2. tools/ directory relative to the package (development mode)
    3. tools/ directory relative to the executable (standalone binary mode)
    4. tools/ directory relative to the current working directory

    This is version-adaptive: it finds any version of the tool, not a
    specific pinned version. Updated toolchains are detected automatically.
    """
    # 1) check PATH
    found = shutil.which(name)
    if found:
        return found

    # 2) check local tools directory relative to this file (development mode)
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    result = _search_tools_dir(tools_dir, name, subdir)
    if result:
        return result

    # 3) check tools/ relative to the executable (standalone binary mode)
    if hasattr(sys, "_MEIPASS") or getattr(sys, "frozen", False):
        # PyInstaller: executable is in dist/ge/ge.exe, tools/ should be next to it
        exe_dir = Path(sys.executable).resolve().parent
        tools_dir = exe_dir / "tools"
        result = _search_tools_dir(tools_dir, name, subdir)
        if result:
            return result
        # also check parent of exe dir
        tools_dir = exe_dir.parent / "tools"
        result = _search_tools_dir(tools_dir, name, subdir)
        if result:
            return result

    # 4) check tools/ relative to current working directory
    tools_dir = Path.cwd() / "tools"
    result = _search_tools_dir(tools_dir, name, subdir)
    if result:
        return result

    return None


def _search_tools_dir(tools_dir: Path, name: str, subdir: str = "") -> str | None:
    """Search a tools directory for a tool by name."""
    if not tools_dir.exists():
        return None

    # direct path with subdir
    if subdir:
        p = tools_dir / subdir / f"{name}.exe"
        if p.exists():
            return str(p)
        p = tools_dir / subdir / name
        if p.exists():
            return str(p)

    # version-agnostic search: find any directory matching a prefix
    name_lower = name.lower()
    for child in sorted(tools_dir.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        child_lower = child.name.lower()
        if child_lower.startswith(name_lower) or name_lower in child_lower:
            p = child / f"{name}.exe"
            if p.exists():
                return str(p)
            p = child / name
            if p.exists():
                return str(p)
            p = child / "bin" / f"{name}.exe"
            if p.exists():
                return str(p)
            p = child / "bin" / f"{name}.bat"
            if p.exists():
                return str(p)
            p = child / "bin" / name
            if p.exists():
                return str(p)

    # search one level deep
    for child in tools_dir.iterdir():
        if not child.is_dir():
            continue
        for sub in child.iterdir():
            if sub.is_dir() and sub.name.lower() in ("bin", "lib", "cmd"):
                p = sub / f"{name}.exe"
                if p.exists():
                    return str(p)
                p = sub / f"{name}.bat"
                if p.exists():
                    return str(p)

    return None


# ---- Version parsing ----

def _parse_version(output: str) -> str:
    """Extract a version string from compiler --version output.

    Handles formats like:
    - "rustc 1.92.0 (ded5c06cf 2025-12-08)"
    - "clang version 20.1.8"
    - "go version go1.25.5 windows/amd64"
    - "0.14.1" (Zig)
    - "info: kotlinc-native 2.4.10 (JRE 25.0.1+8-LTS-27)"
    - "10.0.101" (.NET)
    """
    # try common version patterns
    patterns = [
        r'(\d+\.\d+\.\d+(?:\.\d+)?)',  # x.y.z or x.y.z.w
        r'(\d+\.\d+)',                  # x.y (fallback)
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    return "unknown"


def _get_tool_version(tool_path: str, tool_name: str) -> str:
    """Get the version of a toolchain by running it with the right version flag."""
    try:
        # different tools use different version flags
        if tool_name == "zig":
            cmd = [tool_path, "version"]
        elif tool_name == "kotlinc":
            cmd = [tool_path, "-version"]
        elif tool_name == "dotnet":
            cmd = [tool_path, "--version"]
        elif tool_name == "go":
            cmd = [tool_path, "version"]  # Go uses "go version" not "go --version"
        else:
            cmd = [tool_path, "--version"]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = (r.stdout or "") + (r.stderr or "")
        return _parse_version(output)
    except Exception:
        return "unknown"


def _compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Returns -1, 0, or 1."""
    parts1 = [int(x) for x in v1.split(".") if x.isdigit()]
    parts2 = [int(x) for x in v2.split(".") if x.isdigit()]
    # pad with zeros
    while len(parts1) < len(parts2):
        parts1.append(0)
    while len(parts2) < len(parts1):
        parts2.append(0)
    for a, b in zip(parts1, parts2):
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


def _check_version(tool_name: str, found_version: str, min_version: str) -> str:
    """Check if a tool version meets the minimum. Returns warning string or empty."""
    if found_version == "unknown":
        return f"Warning: could not determine {tool_name} version (expected >={min_version})"
    if _compare_versions(found_version, min_version) < 0:
        return f"Warning: {tool_name} {found_version} is older than recommended {min_version} — some features may not work"
    return ""


# ---- Compiler detection ----

def detect_compilers() -> CompilerInfo:
    """Detect all available compilers and their versions.

    This function is version-adaptive: it finds any version of each toolchain
    on PATH or in the local tools/ directory. It records versions and issues
    warnings for outdated toolchains, but never fails to detect a tool.
    """
    info = CompilerInfo()

    # Rust
    info.rustc = _find_tool("rustc")
    if info.rustc:
        v = _get_tool_version(info.rustc, "rustc")
        info.versions["rustc"] = v
        w = _check_version("rustc", v, MIN_VERSIONS["rustc"])
        if w:
            info.warnings.append(w)

    # C++ (try g++, clang++, cl in order)
    for name, kind in (("g++", "gcc"), ("clang++", "clang"), ("cl", "msvc")):
        found = _find_tool(name)
        if found:
            info.cpp = found
            info.cpp_kind = kind
            v = _get_tool_version(found, "cpp")
            info.versions["cpp"] = v
            w = _check_version("cpp", v, MIN_VERSIONS["cpp"])
            if w:
                info.warnings.append(w)
            break

    # C# (.NET)
    info.dotnet = _find_tool("dotnet")
    if info.dotnet:
        v = _get_tool_version(info.dotnet, "dotnet")
        info.versions["dotnet"] = v
        w = _check_version("dotnet", v, MIN_VERSIONS["dotnet"])
        if w:
            info.warnings.append(w)

    # Zig
    info.zig = _find_tool("zig")
    if info.zig:
        v = _get_tool_version(info.zig, "zig")
        info.versions["zig"] = v
        w = _check_version("zig", v, MIN_VERSIONS["zig"])
        if w:
            info.warnings.append(w)

    # Go
    info.go = _find_tool("go")
    if info.go:
        v = _get_tool_version(info.go, "go")
        info.versions["go"] = v
        w = _check_version("go", v, MIN_VERSIONS["go"])
        if w:
            info.warnings.append(w)

    # Kotlin (kotlinc-native for Kotlin/Native compilation)
    info.kotlinc = _find_tool("kotlinc-native")
    if info.kotlinc:
        v = _get_tool_version(info.kotlinc, "kotlinc")
        info.versions["kotlinc"] = v
        w = _check_version("kotlinc", v, MIN_VERSIONS["kotlinc"])
        if w:
            info.warnings.append(w)

    return info


def compiler_version(name: str) -> str:
    """Get the version string of a compiler by name."""
    try:
        if name == "zig":
            cmd = [name, "version"]
        elif name == "kotlinc-native":
            cmd = [name, "-version"]
        else:
            cmd = [name, "--version"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "unknown"
    except Exception:
        return "unknown"


def print_toolchain_report(info: CompilerInfo) -> None:
    """Print a human-readable report of detected toolchains."""
    print("=== GE Toolchain Report ===")
    tools = [
        ("Rust", info.rustc, info.versions.get("rustc", "—")),
        ("C++", info.cpp, info.versions.get("cpp", "—")),
        ("C# (.NET)", info.dotnet, info.versions.get("dotnet", "—")),
        ("Zig", info.zig, info.versions.get("zig", "—")),
        ("Go", info.go, info.versions.get("go", "—")),
        ("Kotlin", info.kotlinc, info.versions.get("kotlinc", "—")),
    ]
    for name, path, version in tools:
        status = "[OK]" if path else "[--]"
        ver_str = f"v{version}" if version != "-" else ""
        print(f"  {status} {name:12} {ver_str:12} {path or 'not found'}")
    if info.warnings:
        print("\nWarnings:")
        for w in info.warnings:
            print(f"  [!] {w}")
