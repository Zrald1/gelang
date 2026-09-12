"""GE toolchain downloader — fetches missing compilers from official sources.

When a required toolchain (Rust, Go, Zig, etc.) is not found locally, GE can
download it from official sources and cache it in the GE tools directory.

Download URLs (official sources):
  Rust:  https://static.rust-lang.org/rustup/dist/{target}/rustup-init[.exe]
  Go:    https://go.dev/dl/go{version}.{platform}-{arch}.{zip|tar.gz}
  Zig:   https://ziglang.org/download/{version}/zig-{platform}-{arch}-{version}.zip
  C++:   Uses MSVC (Visual Studio) or MinGW — not downloadable by GE
  C#:    Uses .NET SDK from Microsoft — detected, not downloaded
  Kotlin: Uses kotlinc — detected, not downloaded
  Dart/Flutter: https://storage.googleapis.com/flutter_infra_release/releases/...

Cache location: ~/.ge/tools/{name}/
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

# Official download URLs
DOWNLOAD_URLS = {
    "rust": {
        "windows-x86_64": "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe",
        "linux-x86_64": "https://sh.rustup.rs",
        "macos-x86_64": "https://sh.rustup.rs",
    },
    "go": {
        "windows-x86_64": "https://go.dev/dl/go1.23.4.windows-amd64.zip",
        "linux-x86_64": "https://go.dev/dl/go1.23.4.linux-amd64.tar.gz",
        "macos-x86_64": "https://go.dev/dl/go1.23.4.darwin-amd64.tar.gz",
        "macos-aarch64": "https://go.dev/dl/go1.23.4.darwin-arm64.tar.gz",
    },
    "zig": {
        "windows-x86_64": "https://ziglang.org/download/0.13.0/zig-x86_64-windows-0.13.0.zip",
        "linux-x86_64": "https://ziglang.org/download/0.13.0/zig-x86_64-linux-0.13.0.tar.xz",
        "macos-x86_64": "https://ziglang.org/download/0.13.0/zig-x86_64-macos-0.13.0.tar.xz",
        "macos-aarch64": "https://ziglang.org/download/0.13.0/zig-aarch64-macos-0.13.0.tar.xz",
    },
}

# Toolchain binary names after extraction
TOOLCHAIN_BINARIES = {
    "rust": "rustc",
    "go": "go",
    "zig": "zig",
}

# Minimum required versions (kept loose for downloaded toolchains)
MIN_VERSIONS = {
    "rust": "1.70",
    "go": "1.21",
    "zig": "0.13",
}


def _get_platform_key() -> str:
    """Return platform key like 'windows-x86_64' or 'linux-x86_64'."""
    os_name = platform.system().lower()
    if os_name == "windows":
        os_name = "windows"
    elif os_name == "darwin":
        os_name = "macos"
    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        arch = "x86_64"
    elif arch in ("arm64", "aarch64"):
        arch = "aarch64"
    return f"{os_name}-{arch}"


def get_tools_dir() -> Path:
    """Get the GE tools cache directory."""
    home = Path.home()
    tools_dir = home / ".ge" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def get_toolchain_dir(name: str) -> Path:
    """Get the directory for a specific toolchain."""
    return get_tools_dir() / name


def is_toolchain_available(name: str) -> bool:
    """Check if a toolchain is available (either on PATH or in GE tools cache)."""
    binary = TOOLCHAIN_BINARIES.get(name, name)
    if shutil.which(binary):
        return True
    # Check GE tools cache
    tool_dir = get_toolchain_dir(name)
    if tool_dir.exists():
        # Look for binary in common subdirectory patterns
        for pattern in ["bin", ".", "go/bin"]:
            bin_dir = tool_dir / pattern
            if bin_dir.exists():
                exe_name = binary + (".exe" if platform.system() == "Windows" else "")
                if (bin_dir / exe_name).exists():
                    return True
        # Check if any file matching the binary name exists
        for p in tool_dir.rglob(f"{binary}*"):
            if p.is_file():
                return True
    return False


def get_toolchain_path(name: str) -> str | None:
    """Get the executable path for a toolchain, or None."""
    binary = TOOLCHAIN_BINARIES.get(name, name)
    # Check PATH first
    path = shutil.which(binary)
    if path:
        return path
    # Check GE tools cache
    tool_dir = get_toolchain_dir(name)
    if tool_dir.exists():
        exe_name = binary + (".exe" if platform.system() == "Windows" else "")
        for pattern in ["bin", ".", "go/bin"]:
            bin_dir = tool_dir / pattern
            if bin_dir.exists():
                exe_path = bin_dir / exe_name
                if exe_path.exists():
                    return str(exe_path)
        # Search recursively
        for p in tool_dir.rglob(f"{binary}*"):
            if p.is_file():
                return str(p)
    return None


def _download(url: str, dest: Path) -> bool:
    """Download a file from URL to dest. Returns True on success."""
    try:
        print(f"  Downloading from {url}...")
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        return False


def _extract_archive(archive_path: Path, dest_dir: Path) -> bool:
    """Extract a zip or tar archive. Returns True on success."""
    try:
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(dest_dir)
        elif archive_path.suffix in (".gz", ".xz", ".tgz"):
            with tarfile.open(archive_path, "r:*") as t:
                t.extractall(dest_dir)
        else:
            print(f"  Unknown archive format: {archive_path.suffix}")
            return False
        return True
    except Exception as e:
        print(f"  Extract failed: {e}")
        return False


def _find_extracted_root(dest_dir: Path) -> Path:
    """Find the actual root directory after extraction (handles nested dirs)."""
    # If there's a single subdirectory, return it
    entries = [p for p in dest_dir.iterdir() if p.is_dir()]
    if len(entries) == 1:
        return entries[0]
    return dest_dir


def download_toolchain(name: str, force: bool = False) -> bool:
    """Download and install a toolchain from official sources.

    Args:
        name: toolchain name (rust, go, zig)
        force: re-download even if already available

    Returns:
        True if toolchain is available after this call.
    """
    if name not in DOWNLOAD_URLS:
        print(f"  Toolchain '{name}' is not auto-downloadable (needs manual install).")
        return is_toolchain_available(name)

    if not force and is_toolchain_available(name):
        return True

    plat_key = _get_platform_key()
    urls = DOWNLOAD_URLS[name]
    url = urls.get(plat_key) or urls.get(plat_key.split("-")[0] + "-x86_64")
    if not url:
        print(f"  No download URL for {name} on {plat_key}")
        return False

    tool_dir = get_toolchain_dir(name)
    tool_dir.mkdir(parents=True, exist_ok=True)

    # Download to temp file
    archive_name = url.split("/")[-1]
    archive_path = tool_dir / archive_name

    if not _download(url, archive_path):
        return False

    # Handle rustup specially (it's an installer, not an archive)
    if name == "rust":
        if archive_path.suffix == ".exe":
            # Run rustup-init.exe with default settings
            import subprocess
            print("  Running rustup-init...")
            try:
                subprocess.run([str(archive_path), "-y"], check=True, timeout=300)
                archive_path.unlink()
                return is_toolchain_available("rust")
            except Exception as e:
                print(f"  rustup-init failed: {e}")
                return False
        else:
            # Unix: run the shell script
            import subprocess
            os.chmod(str(archive_path), os.stat(str(archive_path)).st_mode | stat.S_IEXEC)
            print("  Running rustup-init...")
            try:
                subprocess.run(["sh", str(archive_path), "-y"], check=True, timeout=300)
                archive_path.unlink()
                return is_toolchain_available("rust")
            except Exception as e:
                print(f"  rustup-init failed: {e}")
                return False

    # Extract archive
    print(f"  Extracting {archive_name}...")
    if not _extract_archive(archive_path, tool_dir):
        return False

    # Clean up archive
    archive_path.unlink()

    # For Go, the archive extracts to a "go" subdirectory
    if name == "go":
        extracted = _find_extracted_root(tool_dir)
        # Go archives extract to "go/" — move contents to tool_dir if needed
        if extracted.name == "go" and extracted != tool_dir:
            # Already in the right place (tool_dir/go/)
            pass

    # For Zig, archives extract to "zig-..." directory
    if name == "zig":
        extracted = _find_extracted_root(tool_dir)
        if extracted != tool_dir:
            # Move contents from zig-x86_64-.../ to tool_dir/
            for item in extracted.iterdir():
                shutil.move(str(item), str(tool_dir / item.name))
            extracted.rmdir()

    available = is_toolchain_available(name)
    if available:
        print(f"  {name} installed successfully.")
    else:
        print(f"  {name} downloaded but binary not found. Check {tool_dir}")
    return available


def ensure_toolchains(names: list[str], auto_download: bool = True) -> dict[str, bool]:
    """Ensure all specified toolchains are available.

    Args:
        names: list of toolchain names
        auto_download: download missing toolchains automatically

    Returns:
        Dict mapping toolchain name to availability status.
    """
    result = {}
    for name in names:
        if is_toolchain_available(name):
            result[name] = True
        elif auto_download and name in DOWNLOAD_URLS:
            print(f"Toolchain '{name}' not found. Downloading...")
            result[name] = download_toolchain(name)
        else:
            result[name] = False
    return result


def get_tools_status() -> dict[str, dict]:
    """Get status of all known toolchains."""
    from .config import detect_compilers
    detected = detect_compilers()
    status = {}
    for name in ["rust", "cpp", "csharp", "zig", "go", "kotlin", "dart"]:
        available = is_toolchain_available(name) or getattr(detected, name, None) is not None
        path = get_toolchain_path(name) or getattr(detected, name, None)
        downloadable = name in DOWNLOAD_URLS
        status[name] = {
            "available": bool(available),
            "path": str(path) if path else None,
            "downloadable": downloadable,
            "cache_dir": str(get_toolchain_dir(name)),
        }
    return status
