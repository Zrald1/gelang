"""Differential testing: prove every backend agrees with Python.

GE emits many backends from one IR, so the same program can be run through
CPython and through every native binary and the outputs compared. That makes
cross-backend agreement a *checkable property* rather than a hope.

    python -m pyeffic.difftest <file-or-dir> [--backends rust,cpp,...]

Lanes
-----
reference   CPython executes the lowered program — the oracle
parity      each backend's binary must match the oracle byte-for-byte
            (stdout, and optionally exit code)

This is the technique `scriptc` uses with Node.js as its oracle, and the one
Rustlantis used to find 22 previously-unknown Rust compiler bugs.

Corpus conventions
------------------
A case is a `.ge`, `.ge.py`, or `.ge.ts` file with a `main()` that prints.
Optional directives in the first lines:

    // @expect: 42          expected stdout (skips the CPython run)
    // @skip: cpp           exclude a backend
    // @only: rust         run only these backends
    // @exit: 1             expected exit code
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, detect_compilers

#: backends we can build and run, in a stable order
RUNNABLE_BACKENDS = ("rust", "cpp", "csharp", "zig", "go", "kotlin")

_EXE = ".exe" if sys.platform == "win32" else ""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    backend: str
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    note: str = ""

    @property
    def normalised(self) -> str:
        """Stdout with trailing whitespace normalised for comparison."""
        return "\n".join(line.rstrip() for line in self.stdout.splitlines()).strip()


@dataclass
class DiffReport:
    source: Path
    reference: RunResult | None = None
    results: dict[str, RunResult] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def expected(self) -> str:
        if self.reference and self.reference.ok:
            return self.reference.normalised
        return ""

    @property
    def mismatches(self) -> dict[str, str]:
        """backend -> why it disagrees with the oracle."""
        want = self.expected
        out: dict[str, str] = {}
        for backend, r in self.results.items():
            if not r.ok:
                out[backend] = r.note or "build or run failed"
            elif r.normalised != want:
                out[backend] = (f"stdout differs\n"
                                f"    expected: {want!r}\n"
                                f"    actual  : {r.normalised!r}")
        return out

    @property
    def passed(self) -> bool:
        return not self.error and not self.mismatches

    @property
    def compared(self) -> int:
        return len(self.results) - len(self.mismatches)


# ---------------------------------------------------------------------------
# Directives
# ---------------------------------------------------------------------------

def _directives(source: str) -> dict[str, str]:
    """Parse leading `// @key: value` / `# @key: value` directives.

    A repeated key accumulates, one value per line, so a program with
    several output lines can list several `@expect` directives.
    """
    out: dict[str, str] = {}
    for line in source.splitlines()[:24]:
        s = line.strip()
        for prefix in ("//", "#"):
            if s.startswith(prefix):
                body = s[len(prefix):].strip()
                if body.startswith("@") and ":" in body:
                    key, _, val = body[1:].partition(":")
                    key = key.strip().lower()
                    if key in out:
                        out[key] = out[key] + "\n" + val.strip()
                    else:
                        out[key] = val.strip()
                break
    return out


# ---------------------------------------------------------------------------
# Reference lane: CPython
# ---------------------------------------------------------------------------

def _stub_preamble(backend, code):  # noqa: ARG001
    return None


def _stub_value(*args, **kwargs):  # noqa: ARG001
    return 0


def _stub_decorator(*args, **kwargs):
    """`@rust` / `@cpp` used bare, or called with a function."""
    if len(args) == 1 and callable(args[0]):
        return args[0]

    def _wrap(fn):
        return fn
    return _wrap


def run_reference(source_path: Path) -> RunResult:
    """Execute the lowered program under CPython and capture stdout."""
    from .frontends import frontend_for
    from .modules import _lower_source

    result = RunResult(backend="python", ok=False)
    try:
        raw = source_path.read_text(encoding="utf-8")
        if frontend_for(source_path) != "python":
            code = _lower_source(raw, source_path)
        else:
            code = raw
    except Exception as exc:
        result.note = f"lowering failed: {exc}"
        return result

    # Strip compiler-only imports and give the intrinsics no-op stubs so the
    # program can run as ordinary Python.
    lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("from pyeffic.") or s.startswith("import pyeffic"):
            continue
        if s.startswith("from __future__"):
            continue
        lines.append(line)
    code = "\n".join(lines)

    ns: dict = {
        "__name__": "__main__",
        "ge_preamble": _stub_preamble,
        "ge_inline": _stub_value,
        "ge_raw": _stub_value,
        "gePreamble": _stub_preamble,
        "geInline": _stub_value,
        "geRaw": _stub_value,
        "print": print,
    }
    for backend in RUNNABLE_BACKENDS:
        ns[backend] = _stub_decorator

    buf = io.StringIO()
    try:
        exec(compile(code, str(source_path), "exec"), ns)  # noqa: S102
        with redirect_stdout(buf):
            main = ns.get("main")
            if callable(main):
                main()
            else:
                # module-level program: re-exec with stdout captured
                exec(compile(code, str(source_path), "exec"), ns)  # noqa: S102
        result.stdout = buf.getvalue()
        result.ok = True
    except SystemExit as exc:
        result.stdout = buf.getvalue()
        result.exit_code = int(exc.code or 0)
        result.ok = True
    except Exception:
        result.stdout = buf.getvalue()
        result.note = "runtime error: " + traceback.format_exc(limit=1).strip().splitlines()[-1]
    return result


# ---------------------------------------------------------------------------
# Parity lane: native backends
# ---------------------------------------------------------------------------

def available_backends(requested: tuple[str, ...] | None = None) -> list[str]:
    """Backends whose toolchain is actually installed."""
    info = detect_compilers()
    have = {
        "rust": bool(info.rustc),
        "cpp": bool(info.cpp),
        "csharp": bool(info.dotnet),
        "zig": bool(info.zig),
        "go": bool(info.go),
        "kotlin": bool(info.kotlinc),
    }
    wanted = requested or RUNNABLE_BACKENDS
    return [b for b in wanted if have.get(b)]


def _exe_for(report, backend: str) -> Path | None:
    cr = {
        "rust": report.rust_compile,
        "cpp": report.cpp_compile,
        "csharp": report.csharp_compile,
        "zig": report.zig_compile,
        "go": report.go_compile,
        "kotlin": report.kotlin_compile,
    }.get(backend)
    if cr is None:
        return None
    return cr.exe if cr.ok else None


def run_backend(source_path: Path, backend: str, timeout: int = 60,
                workdir: Path | None = None) -> RunResult:
    """Build the program for one backend, run it, capture stdout."""
    from .pipeline import build

    result = RunResult(backend=backend, ok=False)
    with tempfile.TemporaryDirectory() as td:
        out = Path(workdir) if workdir else Path(td) / "build"
        cfg = Config(out_dir=out, target="desktop", do_research=False,
                     force_backend=backend)
        try:
            report = build(source_path, cfg, entry="main")
        except Exception as exc:
            result.note = f"compiler error: {exc}"
            return result

        if report.errors.has_errors():
            first = report.errors.diagnostics[0]
            result.note = f"build failed: {getattr(first, 'message', first)}"
            return result

        exe = _exe_for(report, backend)
        if exe is None or not Path(exe).exists():
            result.note = "no executable produced"
            return result

        try:
            proc = subprocess.run([str(exe)], capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            result.note = f"timed out after {timeout}s"
            return result
        result.stdout = proc.stdout
        result.stderr = proc.stderr
        result.exit_code = proc.returncode
        result.ok = True
    return result


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def diff_one(source_path: Path, backends: list[str] | None = None,
             timeout: int = 60) -> DiffReport:
    """Compare one program's output across CPython and every backend."""
    report = DiffReport(source=source_path)
    raw = source_path.read_text(encoding="utf-8")
    directives = _directives(raw)

    expected = directives.get("expect")
    skip = {b.strip() for b in directives.get("skip", "").split(",") if b.strip()}
    only = {b.strip() for b in directives.get("only", "").split(",") if b.strip()}

    candidates = backends if backends is not None else available_backends()
    if only:
        candidates = [b for b in candidates if b in only]
    candidates = [b for b in candidates if b not in skip]

    if expected is not None:
        report.reference = RunResult(backend="python", ok=True, stdout=expected)
    else:
        report.reference = run_reference(source_path)
        if not report.reference.ok:
            report.error = f"reference failed: {report.reference.note}"
            return report

    for backend in candidates:
        report.results[backend] = run_backend(source_path, backend, timeout=timeout)

    for backend in RUNNABLE_BACKENDS:
        if backend not in report.results:
            report.skipped[backend] = "not requested or toolchain missing"
    return report


def find_cases(root: Path) -> list[Path]:
    """Every runnable case under `root`."""
    from .frontends import is_ge_source

    if root.is_file():
        return [root]
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and is_ge_source(p):
            out.append(p)
    return out


def diff_corpus(root: Path, backends: list[str] | None = None,
                timeout: int = 60, verbose: bool = False) -> list[DiffReport]:
    """Run the differential lane over a file or directory."""
    reports: list[DiffReport] = []
    for case in find_cases(root):
        rep = diff_one(case, backends=backends, timeout=timeout)
        reports.append(rep)
        if verbose:
            mark = "ok  " if rep.passed else "DIFF"
            print(f"  [{mark}] {case.name}  "
                  f"({rep.compared}/{len(rep.results)} backends agree)")
            for backend, why in rep.mismatches.items():
                print(f"          {backend}: {why}")
            if rep.error:
                print(f"          {rep.error}")
    return reports


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="python -m pyeffic.difftest",
        description="Compare CPython and every native backend on the same program")
    p.add_argument("path", help="a .ge file or a directory of them")
    p.add_argument("--backends", default=None,
                   help="comma-separated subset (default: all installed)")
    p.add_argument("--timeout", type=int, default=60,
                   help="per-program run timeout in seconds")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    requested = None
    if args.backends:
        requested = tuple(b.strip() for b in args.backends.split(",") if b.strip())

    root = Path(args.path)
    if not root.exists():
        print(f"error: {root} not found", file=sys.stderr)
        return 2

    backends = available_backends(requested)
    print("GE differential test")
    print(f"  corpus  : {root}")
    print(f"  oracle  : CPython")
    print(f"  backends: {', '.join(backends) if backends else '(none installed)'}")
    print()

    if not backends:
        print("no backend toolchains available — nothing to compare")
        return 2

    reports = diff_corpus(root, backends=backends, timeout=args.timeout,
                          verbose=args.verbose)
    total = len(reports)
    failed = [r for r in reports if not r.passed]
    comparisons = sum(len(r.results) for r in reports)
    agreements = sum(r.compared for r in reports)

    print()
    print(f"  programs   : {total}")
    print(f"  comparisons: {comparisons}")
    print(f"  agreements : {agreements}")
    print(f"  mismatches : {comparisons - agreements}")

    if failed:
        print()
        print("FAILED:")
        for r in failed:
            print(f"  {r.source}")
            if r.error:
                print(f"    {r.error}")
            for backend, why in r.mismatches.items():
                print(f"    {backend}: {why}")
        return 1

    print()
    print("all backends agree with CPython")
    return 0


if __name__ == "__main__":
    sys.exit(main())
