"""API surface dump and check.

A committed description of the surfaces users depend on, so a change to them
is a deliberate, reviewable act rather than an accident.

    api/cli.api          every command, flag and argument
    api/diagnostics.api  every GE*** code and its meaning
    api/intrinsics.api   the compiler intrinsics and their backends

Modelled on Kotlin's `apiDump`/`apiCheck` and Go's `apidiff`: the dump is
committed, `--check` fails when it drifts, and changing it means running
`--update`, reviewing the diff, and committing it.

Usage
-----
    ge api-check             fail on unexplained surface change
    ge api-dump              regenerate the dumps (review, then commit)
"""
from __future__ import annotations

import sys
from pathlib import Path

#: backend decorators and the intrinsics every frontend exposes
INTRINSICS = {
    "ge_inline": "target-specific inline code, function body",
    "ge_raw": "unconditional raw code, function body",
    "ge_preamble": "file-scope code injection, module level",
    "gePreamble": "TypeScript-flavour spelling of ge_preamble",
    "geInline": "TypeScript-flavour spelling of ge_inline",
    "geRaw": "TypeScript-flavour spelling of ge_raw",
}

BACKEND_DECORATORS = ("rust", "cpp", "csharp", "zig", "go", "kotlin", "dart")

#: source extensions and the frontend each selects
FRONTENDS = {
    ".ge": "hybrid",
    ".ge.py": "python",
    ".ge.ts": "typescript",
    ".ts.ge.py": "typescript (legacy alias)",
    ".ge.ui": "ui DSL",
}

#: where the dumps live, relative to the repo root
API_DIR = "api"


def api_root() -> Path:
    return Path(__file__).resolve().parent.parent / API_DIR


# ---------------------------------------------------------------------------
# Dump generation
# ---------------------------------------------------------------------------

def dump_cli() -> str:
    """Every command, flag and argument, sorted and stable."""
    import argparse

    from . import ge_cli

    # build the parser the same way the CLI does
    parser = argparse.ArgumentParser(prog="ge", add_help=False)
    sub = parser.add_subparsers(dest="cmd")

    # ge_cli.main() constructs the parser inline; capture it by running the
    # module's parser builder if exposed, otherwise introspect the actions
    # of a freshly built parser via a dry run.
    import io
    from contextlib import redirect_stderr, redirect_stdout

    captured = None

    real_add_subparsers = argparse.ArgumentParser.add_subparsers

    def spy(self, *a, **kw):
        nonlocal captured
        sp = real_add_subparsers(self, *a, **kw)
        captured = self
        return sp

    argparse.ArgumentParser.add_subparsers = spy
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                ge_cli.main(["compilers"])
            except SystemExit:
                pass
    finally:
        argparse.ArgumentParser.add_subparsers = real_add_subparsers

    lines: list[str] = []
    if captured is not None:
        for action in captured._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name in sorted(action.choices):
                    sub_parser = action.choices[name]
                    # one line per (command, surface) pair so a diff names the
                    # exact command that changed
                    lines.append(f"{name} <command>")
                    for sub_action in sub_parser._actions:
                        if sub_action.option_strings:
                            opts = ", ".join(sorted(sub_action.option_strings))
                            lines.append(f"{name} option {opts}")
                        elif sub_action.dest not in ("help",):
                            suffix = "" if sub_action.nargs != "?" else "?"
                            lines.append(f"{name} arg {sub_action.dest}{suffix}")
    lines.sort()
    return "\n".join(lines) + "\n"


def dump_diagnostics() -> str:
    """Every diagnostic code the compiler can emit."""
    from .diagnostics import ErrorReporter  # noqa: F401

    known = {
        "GE001": "unsupported construct / import warning",
        "GE002": "type mismatch or lossy conversion",
        "GE003": "reserved for future use",
        "GE004": "reserved for future use",
        "GE005": "native compilation failed",
        "GE006": "reserved for future use",
        "GE007": "function called but not defined",
        "GE008": "entry point not found",
        "GE009": "reserved for future use",
        "GE010": "source frontend error (TypeScript/hybrid lowering)",
        "GE011": "identifier renamed to avoid a target-language keyword",
        "GE020": "deprecated form (planned)",
    }
    lines = [f"{code} {text}" for code, text in sorted(known.items())]
    return "\n".join(lines) + "\n"


def dump_intrinsics() -> str:
    lines: list[str] = []
    for name, desc in sorted(INTRINSICS.items()):
        lines.append(f"intrinsic {name}: {desc}")
    for dec in sorted(BACKEND_DECORATORS):
        lines.append(f"decorator @{dec}")
    for ext, frontend in sorted(FRONTENDS.items()):
        lines.append(f"extension {ext} -> {frontend}")
    return "\n".join(lines) + "\n"


def all_dumps() -> dict[str, str]:
    return {
        "cli.api": dump_cli(),
        "diagnostics.api": dump_diagnostics(),
        "intrinsics.api": dump_intrinsics(),
    }


# ---------------------------------------------------------------------------
# Check / update
# ---------------------------------------------------------------------------

def check(root: Path | None = None) -> tuple[list[str], list[str]]:
    """Return (changed, missing) file names."""
    root = root or api_root()
    changed: list[str] = []
    missing: list[str] = []
    for name, content in all_dumps().items():
        p = root / name
        if not p.exists():
            missing.append(name)
            continue
        if p.read_text(encoding="utf-8").replace("\r\n", "\n") != content:
            changed.append(name)
    return changed, missing


def update(root: Path | None = None) -> list[str]:
    root = root or api_root()
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, content in all_dumps().items():
        p = root / name
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old is None or old.replace("\r\n", "\n") != content:
            p.write_text(content, encoding="utf-8")
            written.append(name)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="ge api-check",
        description="Check or regenerate the committed API surface dumps")
    p.add_argument("--update", action="store_true",
                   help="regenerate the dumps (review the diff, then commit)")
    args = p.parse_args(argv)

    root = api_root()

    if args.update:
        written = update(root)
        print("GE API surface — update")
        print(f"  dir    : {root}")
        print(f"  written: {len(written)}")
        for name in written:
            print(f"    {name}")
        if not written:
            print("  (no changes)")
        print()
        print("review the diff, then commit it")
        return 0

    changed, missing = check(root)
    print("GE API surface — check")
    print(f"  dir: {root}")
    print()
    if not changed and not missing:
        print("the committed API surface matches the compiler")
        return 0

    if missing:
        print("missing dumps (run: ge api-check --update):")
        for name in missing:
            print(f"  {name}")
    if changed:
        print("changed surface (review, then: ge api-check --update):")
        for name in changed:
            print(f"  {name}")
        print()
        print("a change here is a change users can see — treat it as breaking")
        print("unless it is purely additive")
    return 1


if __name__ == "__main__":
    sys.exit(main())
