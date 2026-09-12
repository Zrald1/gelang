"""GE packer: bundle artifacts into a single .ge distribution package.

Like npm: `ge pack` builds everything and bundles it into one `.ge` file.
`ge install package.ge` unpacks and compiles for any target (Windows, Android).

The .ge file is a zip archive containing:
  package.json    — metadata (name, version, ffi_exports, targets)
  source.ge.py    — the original GE source (for recompilation on any platform)
  native/
    ge_logic.rs   — generated Rust source (for cross-compilation)
    ge_logic.dll  — pre-compiled Windows native lib (if available)
  dart/
    bindings.dart — generated Dart FFI bindings
    main.dart     — generated Flutter UI
    pubspec.yaml  — Flutter project config

Compression shrinks DISTRIBUTION SIZE, not runtime speed.
"""
from __future__ import annotations

import json
import re
import zlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileSize:
    path: Path
    raw: int
    packed: int

    @property
    def ratio(self) -> float:
        return self.packed / self.raw if self.raw else 0.0


@dataclass
class PackReport:
    package: Path | None = None
    files: list[FileSize] = field(default_factory=list)
    total_raw: int = 0
    total_packed: int = 0

    @property
    def ratio(self) -> float:
        return self.total_packed / self.total_raw if self.total_raw else 0.0


@dataclass
class PackageMeta:
    """Metadata stored inside the .ge package (package.json)."""
    name: str = ""
    version: str = "0.1.0"
    ge_version: str = "0.1.0"
    app_name: str = ""
    lib_name: str = "ge_logic"
    backend: str = "rust"
    ffi_exports: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=lambda: ["windows", "android"])
    source_file: str = "source.ge.py"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "version": self.version,
            "ge_version": self.ge_version, "app_name": self.app_name,
            "lib_name": self.lib_name, "backend": self.backend,
            "ffi_exports": self.ffi_exports, "targets": self.targets,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PackageMeta":
        return cls(
            name=d.get("name", ""), version=d.get("version", "0.1.0"),
            ge_version=d.get("ge_version", "0.1.0"),
            app_name=d.get("app_name", ""), lib_name=d.get("lib_name", "ge_logic"),
            backend=d.get("backend", "rust"),
            ffi_exports=d.get("ffi_exports", []),
            targets=d.get("targets", ["windows", "android"]),
            source_file=d.get("source_file", "source.ge.py"),
        )


def minify_source(text: str) -> str:
    """Strip comments and collapse runs of whitespace. Preserves strings."""
    out_lines = []
    for line in text.splitlines():
        stripped = re.sub(r'(?:"[^"]*")|(\s*//[^\n]*)', lambda m: m.group(1) or "", line)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if stripped:
            out_lines.append(stripped)
    return "\n".join(out_lines)


def strip_binary_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


# ---- .ge package format (zip-based, npm-like) ----

def pack_ge(source: Path, meta: PackageMeta, artifacts: dict[str, Path],
            out_path: Path, minify: bool = True) -> PackReport:
    """Bundle source + generated artifacts + metadata into a single .ge zip.

    artifacts: dict mapping archive path -> local file path, e.g.:
        {"native/ge_logic.rs": Path("ge_build/myrent/lib/ge_logic.rs"),
         "dart/bindings.dart": Path("ge_build/myrent/lib/bindings.dart"), ...}
    """
    report = PackReport(package=out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 1) metadata
        meta_json = json.dumps(meta.to_dict(), indent=2)
        zf.writestr("package.json", meta_json)
        report.files.append(FileSize(Path("package.json"), len(meta_json), len(meta_json.encode())))
        report.total_raw += len(meta_json)
        report.total_packed += len(meta_json.encode())

        # 2) GE source
        raw = source.read_bytes()
        if minify:
            text = raw.decode("utf-8", errors="ignore")
            mini = minify_source(text)
            data = mini.encode("utf-8")
        else:
            data = raw
        zf.writestr(meta.source_file, data)
        report.files.append(FileSize(source, len(raw), len(data)))
        report.total_raw += len(raw)
        report.total_packed += len(data)

        # 3) artifacts (native lib, Rust source, Dart files, pubspec)
        for arc_name, local_path in artifacts.items():
            if not local_path or not local_path.exists():
                continue
            raw = local_path.read_bytes()
            # only minify the GE source (.py); native source (.rs/.cpp) and Dart
            # must be preserved exactly for cross-compilation and Flutter
            if minify and local_path.suffix == ".py":
                text = raw.decode("utf-8", errors="ignore")
                mini = minify_source(text)
                data = mini.encode("utf-8")
            else:
                data = raw
            zf.writestr(arc_name, data)
            report.files.append(FileSize(local_path, len(raw), len(data)))
            report.total_raw += len(raw)
            report.total_packed += len(data)

    report.total_packed = out_path.stat().st_size
    return report


def pack_simple(source: Path, out_path: Path, app_name: str = "",
                backend: str = "rust", minify: bool = True) -> PackReport:
    """Convenience: pack a single source file into a .ge package.

    This is the simplest API for the common case of bundling one .ge.py file.
    """
    meta = PackageMeta(
        name=app_name or source.stem.replace(".ge", ""),
        app_name=app_name or source.stem.replace(".ge", ""),
        backend=backend,
    )
    return pack_ge(source, meta, {}, out_path, minify=minify)


def unpack_ge(pkg_path: Path, dest_dir: Path) -> PackageMeta:
    """Extract a .ge package to dest_dir. Returns the parsed metadata."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pkg_path, "r") as zf:
        zf.extractall(dest_dir)
    meta_path = dest_dir / "package.json"
    if meta_path.exists():
        return PackageMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
    return PackageMeta()


# ---- legacy .gepkg format (backward compat) ----

def pack(files: list[Path] | Path, out_path: Path, minify: bool = True) -> PackReport:
    """Bundle files into a zlib-compressed .gepkg. Returns a size report.

    Accepts either a single Path or a list of Paths for convenience.
    """
    if isinstance(files, Path):
        files = [files]
    report = PackReport(package=out_path)
    blob = bytearray()
    for f in files:
        if not f.exists():
            continue
        raw = f.read_bytes()
        if minify and f.suffix in (".rs", ".cpp", ".dart", ".py"):
            text = raw.decode("utf-8", errors="ignore")
            mini = minify_source(text)
            data = mini.encode("utf-8")
        else:
            data = raw
        name = f.name.encode("utf-8")
        blob += len(name).to_bytes(4, "little") + name
        blob += len(data).to_bytes(4, "little") + data
        report.files.append(FileSize(f, len(raw), len(data)))
        report.total_raw += len(raw)
        report.total_packed += len(data)

    compressed = zlib.compress(bytes(blob), level=9)
    out_path.write_bytes(compressed)
    report.total_packed = len(compressed)
    return report


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/(1024*1024):.2f} MB"
