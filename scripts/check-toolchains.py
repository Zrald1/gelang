#!/usr/bin/env python3
"""Report available toolchains in a CI-friendly form.

    python scripts/check-toolchains.py            human-readable, exit 0/1
    python scripts/check-toolchains.py --json     machine-readable
    python scripts/check-toolchains.py --require rust,cpp

Exits non-zero only when a *required* backend is missing, so a CI matrix can
install what it needs and fail fast otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyeffic.config import detect_compilers  # noqa: E402

BACKENDS = ("rust", "cpp", "csharp", "zig", "go", "kotlin")


def snapshot() -> dict:
    info = detect_compilers()
    paths = {
        "rust": info.rustc,
        "cpp": info.cpp,
        "csharp": info.dotnet,
        "zig": info.zig,
        "go": info.go,
        "kotlin": info.kotlinc,
    }
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}."
                  f"{sys.version_info.micro}",
        "python_ok": sys.version_info >= (3, 10),
        "backends": {name: bool(p) for name, p in paths.items()},
        "paths": {name: (p or "") for name, p in paths.items()},
        "versions": info.versions,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--require", default="",
                   help="comma-separated backends that must be present")
    args = p.parse_args(argv)

    snap = snapshot()
    required = [b.strip() for b in args.require.split(",") if b.strip()]

    if args.json:
        snap["required"] = required
        snap["missing_required"] = [b for b in required
                                    if not snap["backends"].get(b)]
        print(json.dumps(snap, indent=2))
    else:
        print(f"python {snap['python']}"
              + ("" if snap["python_ok"] else "  (needs 3.10+)"))
        for name in BACKENDS:
            ok = snap["backends"][name]
            mark = "OK" if ok else "--"
            detail = snap["paths"][name] or "not found"
            print(f"  [{mark}] {name:<8} {detail}")

    problems = []
    if not snap["python_ok"]:
        problems.append("python >= 3.10 is required")
    for name in required:
        if not snap["backends"].get(name):
            problems.append(f"required backend '{name}' is not installed")

    if problems:
        print()
        for msg in problems:
            print(f"error: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
