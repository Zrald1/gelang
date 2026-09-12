"""Compile emitted Rust/C++ sources with the detected toolchain."""
from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import CompilerInfo, Config

_EXE = ".exe" if os.name == "nt" else ""
_LIB = ".dll" if os.name == "nt" else (".so" if os.name != "darwin" else ".dylib")


@dataclass
class CompileResult:
    ok: bool
    exe: Path | None
    log: str


# ---- Android cross-compilation ----

ANDROID_ABIS = [
    ("aarch64-linux-android", "arm64-v8a", "aarch64-linux-android"),
    ("armv7-linux-androideabi", "armeabi-v7a", "armv7a-linux-androideabi"),
    ("x86_64-linux-android", "x86_64", "x86_64-linux-android"),
]
ANDROID_API_LEVEL = "24"  # Android 7.0+ — covers 99%+ of devices


def _find_ndk() -> Path | None:
    """Find the latest Android NDK installation."""
    sdk = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "ndk"
    if not sdk.exists():
        return None
    versions = sorted(sdk.iterdir(), reverse=True)
    return versions[0] if versions else None


def _ndk_linker(ndk: Path, rust_target: str) -> str:
    """Get the NDK linker path for a given Rust target."""
    bin_dir = ndk / "toolchains" / "llvm" / "prebuilt" / "windows-x86_64" / "bin"
    # map rust target to NDK clang prefix
    prefix_map = {
        "aarch64-linux-android": f"aarch64-linux-android{ANDROID_API_LEVEL}",
        "armv7-linux-androideabi": f"armv7a-linux-androideabi{ANDROID_API_LEVEL}",
        "x86_64-linux-android": f"x86_64-linux-android{ANDROID_API_LEVEL}",
    }
    prefix = prefix_map.get(rust_target, rust_target)
    linker = bin_dir / f"{prefix}-clang.cmd"
    return str(linker) if linker.exists() else str(bin_dir / f"{prefix}-clang")


def _ndk_cpp_compiler(ndk: Path, rust_target: str) -> str:
    """Get the NDK C++ compiler path for a given Rust target."""
    bin_dir = ndk / "toolchains" / "llvm" / "prebuilt" / "windows-x86_64" / "bin"
    prefix_map = {
        "aarch64-linux-android": f"aarch64-linux-android{ANDROID_API_LEVEL}",
        "armv7-linux-androideabi": f"armv7a-linux-androideabi{ANDROID_API_LEVEL}",
        "x86_64-linux-android": f"x86_64-linux-android{ANDROID_API_LEVEL}",
    }
    prefix = prefix_map.get(rust_target, rust_target)
    cpp = bin_dir / f"{prefix}-clang++.cmd"
    return str(cpp) if cpp.exists() else str(bin_dir / f"{prefix}-clang++")


@dataclass
class AndroidCompileResult:
    ok: bool
    libs: dict[str, Path] = field(default_factory=dict)  # abi -> .so path
    logs: list[str] = field(default_factory=list)


def compile_rust_android(src: Path, cfg: Config, info: CompilerInfo,
                         lib_basename: str = "ge_logic",
                         out_dir: Path | None = None) -> AndroidCompileResult:
    """Cross-compile a Rust source to Android .so files for all ABIs.

    Requires: rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android
    And: Android NDK installed.
    """
    if not info.rustc:
        return AndroidCompileResult(False, logs=["rustc not found"])
    ndk = _find_ndk()
    if not ndk:
        return AndroidCompileResult(False, logs=["Android NDK not found in SDK"])

    if out_dir is None:
        out_dir = src.parent / "android_libs"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = AndroidCompileResult(ok=True)
    for rust_target, abi, _ in ANDROID_ABIS:
        abi_dir = out_dir / abi
        abi_dir.mkdir(exist_ok=True)
        out = abi_dir / f"lib{lib_basename}.so"
        linker = _ndk_linker(ndk, rust_target)
        cmd = [info.rustc, "--target", rust_target,
               "-C", f"opt-level={cfg.opt_level}", "-A", "warnings",
               "-C", f"linker={linker}",
               "--crate-type", "cdylib", "-o", str(out), str(src)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        log = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            result.ok = False
            result.logs.append(f"[{abi}] FAIL: {log[:300]}")
        else:
            result.libs[abi] = out
            result.logs.append(f"[{abi}] OK -> {out.name} ({out.stat().st_size} bytes)")
    return result


def compile_mixed_android(rust_src: Path, cpp_src: Path | None,
                          cfg: Config, info: CompilerInfo,
                          lib_basename: str = "ge_logic",
                          out_dir: Path | None = None) -> AndroidCompileResult:
    """Cross-compile Rust + C++ to Android .so files, linked into one library.

    For each ABI:
      1. Compile C++ to object file using NDK clang++
      2. Compile Rust cdylib, linking the C++ object file in
    """
    if not info.rustc:
        return AndroidCompileResult(False, logs=["rustc not found"])
    ndk = _find_ndk()
    if not ndk:
        return AndroidCompileResult(False, logs=["Android NDK not found in SDK"])

    if out_dir is None:
        out_dir = rust_src.parent / "android_libs"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = AndroidCompileResult(ok=True)
    for rust_target, abi, _ in ANDROID_ABIS:
        abi_dir = out_dir / abi
        abi_dir.mkdir(exist_ok=True)
        out = abi_dir / f"lib{lib_basename}.so"

        # 1) compile C++ to object file (if provided)
        cpp_obj = None
        if cpp_src and cpp_src.exists():
            cpp_obj = abi_dir / f"{cpp_src.stem}.o"
            cpp_compiler = _ndk_cpp_compiler(ndk, rust_target)
            cpp_cmd = [cpp_compiler, "-O2", "-std=c++17", "-w", "-c",
                       "-o", str(cpp_obj), str(cpp_src)]
            r_cpp = subprocess.run(cpp_cmd, capture_output=True, text=True,
                                   timeout=120, encoding="utf-8", errors="replace")
            if r_cpp.returncode != 0:
                result.ok = False
                result.logs.append(f"[{abi}] C++ FAIL: {(r_cpp.stderr or '')[:300]}")
                continue

        # 2) compile Rust cdylib, linking C++ object
        linker = _ndk_linker(ndk, rust_target)
        cmd = [info.rustc, "--target", rust_target,
               "-C", f"opt-level={cfg.opt_level}", "-A", "warnings",
               "-C", f"linker={linker}",
               "--crate-type", "cdylib", "-o", str(out), str(rust_src)]
        if cpp_obj:
            cmd += ["-C", f"link-arg={cpp_obj}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        log = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            result.ok = False
            result.logs.append(f"[{abi}] Rust FAIL: {log[:300]}")
        else:
            result.libs[abi] = out
            result.logs.append(f"[{abi}] OK -> {out.name} ({out.stat().st_size} bytes)")
    return result


def compile_rust(src: Path, cfg: Config, info: CompilerInfo,
                 shared: bool = False, lib_basename: str = "pyeffic_logic") -> CompileResult:
    if not info.rustc:
        return CompileResult(False, None, "rustc not found on PATH")
    # detect if source uses Win32 API (needs user32/gdi32 linking on Windows)
    src_text = src.read_text(encoding="utf-8", errors="replace")
    needs_win32 = ("windows.h" in src_text or "user32" in src_text
                   or "CreateWindow" in src_text or "WinMain" in src_text
                   or "GetMessage" in src_text or "WndProc" in src_text)
    if shared:
        out = cfg.target_dir / f"{lib_basename}{_LIB}"
        cmd = [info.rustc, "-C", f"opt-level={cfg.opt_level}", "-A", "warnings",
               "--crate-type", "cdylib", "-o", str(out), str(src)]
    else:
        out = cfg.bin_dir() / (src.stem + _EXE)
        cmd = [info.rustc, "-C", f"opt-level={cfg.opt_level}", "-A", "warnings",
               "-o", str(out), str(src)]
    # link Windows GUI libraries when Win32 API is used
    if needs_win32 and sys.platform == "win32":
        cmd += ["-C", "link-arg=user32.lib", "-C", "link-arg=gdi32.lib"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return CompileResult(False, None, log)
    return CompileResult(True, out, log)


def compile_cpp(src: Path, cfg: Config, info: CompilerInfo,
                shared: bool = False, lib_basename: str = "pyeffic_logic") -> CompileResult:
    if not info.cpp:
        return CompileResult(False, None, "no C++ compiler (g++/clang++/cl) found on PATH")
    # detect if source uses Win32 API (needs user32/gdi32 linking)
    src_text = src.read_text(encoding="utf-8", errors="replace")
    needs_win32 = ("#include <windows.h>" in src_text or "#include <wingdi.h>" in src_text
                   or "WinMain" in src_text or "CreateWindow" in src_text)
    if shared:
        out = cfg.target_dir / f"{lib_basename}{_LIB}"
        if info.cpp_kind == "msvc":
            cmd = [info.cpp, f"/O{cfg.opt_level}", "/EHsc", "/std:c++17", "/LD",
                   f"/Fe:{out}", str(src)]
            if needs_win32:
                cmd[-1:-1] = ["user32.lib", "gdi32.lib"]
        else:
            cmd = [info.cpp, f"-O{cfg.opt_level}", "-std=c++17", "-w", "-shared",
                   "-fPIC", "-o", str(out), str(src)]
            if needs_win32:
                cmd.extend(["-luser32", "-lgdi32"])
    else:
        out = cfg.bin_dir() / (src.stem + _EXE)
        if info.cpp_kind == "msvc":
            cmd = [info.cpp, f"/O{cfg.opt_level}", "/EHsc", "/std:c++17",
                   f"/Fe:{out}", str(src)]
            if needs_win32:
                cmd[-1:-1] = ["user32.lib", "gdi32.lib"]
        else:
            cmd = [info.cpp, f"-O{cfg.opt_level}", "-std=c++17", "-w",
                   "-o", str(out), str(src)]
            if needs_win32:
                cmd.extend(["-luser32", "-lgdi32"])
            cmd = [c for c in cmd if c]  # remove empty strings
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return CompileResult(False, None, log)
    return CompileResult(True, out, log)


# ---- C# compilation via .NET NativeAOT ----

def compile_csharp(src: Path, cfg: Config, info: CompilerInfo,
                   shared: bool = False, lib_basename: str = "pyeffic_logic") -> CompileResult:
    """Compile C# source to a native library via .NET NativeAOT.

    Requires .NET 8+ SDK with NativeAOT workload. Produces a shared library
    that exports C ABI functions via [UnmanagedCallersOnly].
    """
    if not info.dotnet:
        return CompileResult(False, None, "dotnet not found on PATH (need .NET 8+ SDK)")

    # Create a temporary project for NativeAOT compilation
    project_dir = src.parent / f"{lib_basename}_csharp_project"
    project_dir.mkdir(parents=True, exist_ok=True)

    # write csproj
    csproj = project_dir / f"{lib_basename}.csproj"
    output_type = "Library" if shared else "Exe"
    # Use NativeAOT only for shared libraries (FFI); for executables, use regular build
    # NativeAOT requires the MSVC C++ workload which may not be installed
    publish_aot = "true" if shared else "false"
    csproj.write_text(
        f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <PublishAot>{publish_aot}</PublishAot>
    <OutputType>{output_type}</OutputType>
    <AssemblyName>{lib_basename}</AssemblyName>
  </PropertyGroup>
</Project>
""", encoding="utf-8")

    # copy source into project
    cs_file = project_dir / f"{lib_basename}.cs"
    cs_file.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    if shared:
        out = cfg.target_dir / f"{lib_basename}{_LIB}"
        cmd = [info.dotnet, "publish", str(csproj.resolve()), "-c", "Release",
               "-r", _get_rid(), "-o", str((project_dir / "publish").resolve()),
               "/p:NativeLib=Shared", "/p:SelfContained=true"]
    else:
        out = project_dir / "publish" / f"{lib_basename}{_EXE}"
        cmd = [info.dotnet, "publish", str(csproj.resolve()), "-c", "Release",
               "-o", str((project_dir / "publish").resolve())]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                       cwd=str(project_dir))
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return CompileResult(False, None, log)

    # find the produced binary
    publish_dir = project_dir / "publish"
    if shared:
        produced = list(publish_dir.glob(f"{lib_basename}*{_LIB}"))
        if not produced:
            produced = list(publish_dir.glob(f"{lib_basename}*"))
        if produced:
            import shutil as sh
            sh.copy2(produced[0], out)
            return CompileResult(True, out, log)
        return CompileResult(False, None, f"published but no library found in {publish_dir}\n{log}")
    else:
        exe = publish_dir / f"{lib_basename}{_EXE}"
        if exe.exists():
            return CompileResult(True, exe, log)
        return CompileResult(False, None, f"published but no exe found in {publish_dir}\n{log}")


def _get_rid() -> str:
    """Get the .NET Runtime Identifier for the current platform."""
    import platform
    sys_name = platform.system()
    machine = platform.machine().lower()
    if sys_name == "Windows":
        return "win-x64" if "64" in machine else "win-x86"
    if sys_name == "Darwin":
        return "osx-arm64" if "arm" in machine or "aarch64" in machine else "osx-x64"
    return "linux-x64" if "64" in machine else "linux-x86"


# ---- Zig compilation ----

def compile_zig(src: Path, cfg: Config, info: CompilerInfo,
                shared: bool = False, lib_basename: str = "pyeffic_logic") -> CompileResult:
    """Compile Zig source to a native binary or shared library.

    Zig compiles with no runtime and exports C ABI functions natively.
    """
    if not info.zig:
        return CompileResult(False, None, "zig not found on PATH")

    # Zig uses ReleaseFast/ReleaseSafe/ReleaseSmall, not -O3
    opt_mode = "ReleaseFast" if cfg.opt_level in ("3", "2") else "Debug"

    if shared:
        out = cfg.target_dir / f"{lib_basename}{_LIB}"
        cmd = [info.zig, "build-lib", str(src), "-dynamic", "-O", opt_mode,
               "-femit-bin=" + str(out)]
    else:
        out = cfg.bin_dir() / (src.stem + _EXE)
        cmd = [info.zig, "build-exe", str(src), "-O", opt_mode,
               "-femit-bin=" + str(out)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return CompileResult(False, None, log)
    return CompileResult(True, out, log)


# ---- Go compilation (cgo shared library) ----

def compile_go(src: Path, cfg: Config, info: CompilerInfo,
               shared: bool = False, lib_basename: str = "pyeffic_logic") -> CompileResult:
    """Compile Go source to a native shared library via cgo.

    Go exports C ABI functions with //export directive. Requires Go 1.21+.
    """
    if not info.go:
        return CompileResult(False, None, "go not found on PATH")

    # Go 1.16+ requires a go.mod file for module mode
    go_mod = src.parent / "go.mod"
    if not go_mod.exists():
        go_mod.write_text("module pyeffic\n\ngo 1.21\n", encoding="utf-8")

    if shared:
        out = cfg.target_dir / f"{lib_basename}{_LIB}"
        env = os.environ.copy()
        env["CGO_ENABLED"] = "1"
        # full output path: go runs with cwd=src.parent, so a bare name would
        # land next to the source instead of in the target directory
        cmd = [info.go, "build", "-buildmode=c-shared",
               "-o", str(out.resolve()), str(src.resolve())]
    else:
        out = cfg.bin_dir() / (src.stem + _EXE)
        env = os.environ.copy()
        cmd = [info.go, "build", "-o", str(out.resolve()), str(src.resolve())]

    # Go requires running from the directory containing the source
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env,
                       cwd=str(src.parent))
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return CompileResult(False, None, log)
    return CompileResult(True, out, log)


# ---- Kotlin compilation (Kotlin/Native) ----

def compile_kotlin(src: Path, cfg: Config, info: CompilerInfo,
                   shared: bool = False, lib_basename: str = "pyeffic_logic") -> CompileResult:
    """Compile Kotlin source to a native library via Kotlin/Native.

    Kotlin/Native compiles Kotlin to a native shared library with @CName
    exports for C ABI FFI. Requires Kotlin compiler (kotlinc) with native target.
    """
    if not info.kotlinc:
        return CompileResult(False, None, "kotlinc not found on PATH")

    if shared:
        out = cfg.target_dir / f"{lib_basename}{_LIB}"
        # Kotlin/Native produces shared libraries with -produce dynamic
        cmd = [info.kotlinc, "-produce", "dynamic", "-opt",
               "-output", str(out), str(src)]
    else:
        out = cfg.bin_dir() / (src.stem + _EXE)
        cmd = [info.kotlinc, "-produce", "program", "-opt",
               "-output", str(out), str(src)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return CompileResult(False, None, log)
    return CompileResult(True, out, log)
