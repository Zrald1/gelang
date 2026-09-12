"""Golden lowering corpus — proves emitted code stays put.

Every emitter change is a risk: generated code can churn silently while still
compiling and still producing the right answer. This module makes that churn
visible.

For each case under `tests/golden/<case>/`:

    main.ge            the source
    rust.golden        expected emitted Rust
    cpp.golden         expected emitted C++
    csharp.golden      ...
    zig.golden
    go.golden
    kotlin.golden
    expected.out       what the program must print

Two independent checks:

    lowering   emitted code == committed golden, byte for byte
    behaviour  compiling and running the golden prints expected.out

The lowering check proves we still emit the code we reviewed. The behaviour
check proves that code still does what it did. Together they catch a
regression that keeps compiling.

This is the model bento uses for its TypeScript-to-Go corpus, and it is the
same idea as Kotlin's `apiDump`/`apiCheck` applied to emitted code.

Usage
-----
    ge golden --check            fail on any drift
    ge golden --update           regenerate goldens (review the diff, then commit)
    ge golden --check -v         show which cases drifted
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, detect_compilers

BACKENDS = ("rust", "cpp", "csharp", "zig", "go", "kotlin")

_EMITTERS = {
    "rust": "emit_rust",
    "cpp": "emit_cpp",
    "csharp": "emit_csharp",
    "zig": "emit_zig",
    "go": "emit_go",
    "kotlin": "emit_kotlin",
}


def golden_root() -> Path:
    """Where the corpus lives, relative to the repo root."""
    here = Path(__file__).resolve().parent.parent
    return here / "tests" / "golden"


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

def emit_unit(source_path: Path, backend: str) -> str:
    """Emit the whole compilation unit for one backend.

    Uses the same import resolution and IR rename path as a real build, so a
    golden reflects what a user would actually get.
    """
    from .emitters import (emit_cpp, emit_csharp, emit_go, emit_kotlin,
                           emit_rust, emit_zig)
    from .idents import rename_reserved_functions
    from .modules import get_last_constants, get_last_preamble, resolve_imports

    source = source_path.read_text(encoding="utf-8")
    units, classes, _warnings = resolve_imports(source, source_path)
    supported = [u for u in units if u.supported and u.body is not None]

    # pin every function to the requested backend so the golden is stable
    for u in supported:
        u.forced_backend = backend
    rename_reserved_functions(supported, {backend})

    emit_fn = {
        "rust": emit_rust, "cpp": emit_cpp, "csharp": emit_csharp,
        "zig": emit_zig, "go": emit_go, "kotlin": emit_kotlin,
    }[backend]
    prog, _emitted = emit_fn(supported, entry="main", classes=classes,
                             constants=get_last_constants(),
                             preamble=get_last_preamble())
    return prog


def _normalise(text: str) -> str:
    """Line endings normalised so goldens are platform-independent."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class GoldenProblem:
    case: str
    kind: str      # "lowering" | "behaviour" | "missing" | "unexpected"
    detail: str


@dataclass
class GoldenReport:
    cases: list[Path] = field(default_factory=list)
    problems: list[GoldenProblem] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def checked(self) -> int:
        return len(self.cases)


# ---------------------------------------------------------------------------
# Case discovery
# ---------------------------------------------------------------------------

def find_cases(root: Path | None = None) -> list[Path]:
    """Every golden case directory (one that contains a source file)."""
    root = root or golden_root()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        for name in ("main.ge", "main.ge.py", "main.ge.ts"):
            if (d / name).is_file():
                out.append(d)
                break
    return out


def case_source(case_dir: Path) -> Path:
    for name in ("main.ge", "main.ge.py", "main.ge.ts"):
        p = case_dir / name
        if p.is_file():
            return p
    raise FileNotFoundError(f"no source in {case_dir}")


# ---------------------------------------------------------------------------
# Check / update
# ---------------------------------------------------------------------------

def _golden_path(case_dir: Path, backend: str) -> Path:
    return case_dir / f"{backend}.golden"


def check_case(case_dir: Path, backends: tuple[str, ...] = BACKENDS,
               run: bool = True) -> list[GoldenProblem]:
    """Compare emitted code with the committed goldens for one case."""
    problems: list[GoldenProblem] = []
    src = case_source(case_dir)
    name = case_dir.name

    for backend in backends:
        gpath = _golden_path(case_dir, backend)
        try:
            emitted = _normalise(emit_unit(src, backend))
        except Exception as exc:
            problems.append(GoldenProblem(
                name, "lowering", f"{backend}: emission failed: {exc}"))
            continue

        if not gpath.exists():
            problems.append(GoldenProblem(
                name, "missing", f"{backend}.golden is absent "
                                 f"(run: ge golden --update)"))
            continue

        expected = _normalise(gpath.read_text(encoding="utf-8"))
        if emitted != expected:
            problems.append(GoldenProblem(
                name, "lowering",
                f"{backend}.golden drifted — review with `ge golden --update` "
                f"then commit the diff"))
    return problems


def update_case(case_dir: Path, backends: tuple[str, ...] = BACKENDS) -> list[str]:
    """Regenerate the goldens for one case. Returns the files written."""
    src = case_source(case_dir)
    written: list[str] = []
    for backend in backends:
        try:
            emitted = _normalise(emit_unit(src, backend))
        except Exception:
            continue
        gpath = _golden_path(case_dir, backend)
        old = gpath.read_text(encoding="utf-8") if gpath.exists() else None
        if _normalise(old or "") != emitted:
            gpath.write_text(emitted, encoding="utf-8")
            written.append(f"{case_dir.name}/{backend}.golden")
    return written


def _check_behaviour(case_dir: Path, timeout: int = 90) -> list[GoldenProblem]:
    """Compile and run the source; it must print expected.out."""
    expected_path = case_dir / "expected.out"
    if not expected_path.exists():
        return [GoldenProblem(case_dir.name, "missing",
                              "expected.out is absent")]
    expected = _normalise(expected_path.read_text(encoding="utf-8")).strip()

    from .pipeline import build
    from .config import Config

    with __import__("tempfile").TemporaryDirectory() as td:
        cfg = Config(out_dir=Path(td), target="desktop", do_research=False)
        try:
            report = build(case_source(case_dir), cfg, entry="main")
        except Exception as exc:
            return [GoldenProblem(case_dir.name, "behaviour",
                                  f"build raised: {exc}")]
        if report.errors.has_errors():
            first = report.errors.diagnostics[0]
            return [GoldenProblem(
                case_dir.name, "behaviour",
                f"build failed: {getattr(first, 'message', first)}")]

        cr = report.rust_compile or report.cpp_compile
        if cr is None or not cr.ok or not cr.exe:
            return [GoldenProblem(case_dir.name, "behaviour",
                                  "no runnable binary produced")]
        try:
            proc = subprocess.run([str(cr.exe)], capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return [GoldenProblem(case_dir.name, "behaviour",
                                  f"timed out after {timeout}s")]
        got = _normalise(proc.stdout).strip()
        if got != expected:
            return [GoldenProblem(
                case_dir.name, "behaviour",
                f"output changed\n    expected: {expected!r}\n"
                f"    actual  : {got!r}")]
    return []


def check(root: Path | None = None, backends: tuple[str, ...] = BACKENDS,
          behaviour: bool = True) -> GoldenReport:
    """Check every case."""
    report = GoldenReport()
    for case_dir in find_cases(root):
        report.cases.append(case_dir)
        report.problems.extend(check_case(case_dir, backends))
        if behaviour:
            report.problems.extend(_check_behaviour(case_dir))
    return report


def update(root: Path | None = None,
           backends: tuple[str, ...] = BACKENDS) -> GoldenReport:
    """Regenerate every golden."""
    report = GoldenReport()
    for case_dir in find_cases(root):
        report.cases.append(case_dir)
        report.updated.extend(update_case(case_dir, backends))
    return report


def available(backends: tuple[str, ...] = BACKENDS) -> tuple[str, ...]:
    """Backends whose toolchain is installed (behaviour checks need these)."""
    info = detect_compilers()
    have = {
        "rust": bool(info.rustc), "cpp": bool(info.cpp),
        "csharp": bool(info.dotnet), "zig": bool(info.zig),
        "go": bool(info.go), "kotlin": bool(info.kotlinc),
    }
    return tuple(b for b in backends if have.get(b))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="ge golden",
        description="Check or regenerate the golden lowering corpus")
    p.add_argument("--check", action="store_true",
                   help="fail if emitted code differs from the committed golden")
    p.add_argument("--update", action="store_true",
                   help="regenerate goldens from the current emitters")
    p.add_argument("--no-behaviour", action="store_true",
                   help="skip the compile-and-run check")
    p.add_argument("--backends", default=None,
                   help="comma-separated subset (default: all)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    backends = BACKENDS
    if args.backends:
        backends = tuple(b.strip() for b in args.backends.split(",") if b.strip())

    root = golden_root()
    if not root.is_dir():
        print(f"error: no golden corpus at {root}", file=sys.stderr)
        return 2

    if args.update:
        report = update(root, backends)
        print("GE golden corpus — update")
        print(f"  cases  : {report.checked}")
        print(f"  written: {len(report.updated)}")
        for name in report.updated:
            print(f"    {name}")
        if not report.updated:
            print("  (no changes)")
        print()
        print("review the diff, then commit it")
        return 0

    report = check(root, backends, behaviour=not args.no_behaviour)
    print("GE golden corpus — check")
    print(f"  cases   : {report.checked}")
    print(f"  backends: {', '.join(backends)}")
    print()

    if report.ok:
        print("all goldens match and every case still prints its expected output")
        return 0

    print(f"{len(report.problems)} problem(s):")
    for prob in report.problems:
        print(f"  [{prob.kind}] {prob.case}: {prob.detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
