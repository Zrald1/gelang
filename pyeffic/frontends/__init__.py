"""GE frontends — source language variants that all lower to the same IR.

GE follows the N-frontends x M-backends architecture: each source language
has a frontend that produces the shared typed IR (`FuncUnit` + Python AST),
and each target language has a backend (emitter) that consumes it.

    main.ge       hybrid        -> hybrid frontend     -> IR
    foo.ge.py     Python-like   -> python frontend     -> IR
    foo.ge.ts     TypeScript    -> typescript frontend -> IR
                                                         |
                        +--------------------------------+
                        |
              rust / cpp / csharp / zig / go / kotlin emitters

`.ge` is the canonical extension. A single `.ge` file may contain both
Python-flavoured and TypeScript-flavoured definitions; the hybrid frontend
classifies each top-level chunk and lowers it, so a project can mix styles
per function without splitting files.

The single-flavour extensions still work and are useful when a whole module
is one style:

    foo.ge.py   every chunk is Python-flavoured
    foo.ge.ts   every chunk is TypeScript-flavoured

Adding a source language means adding a frontend here; nothing downstream
changes.
"""
from __future__ import annotations

from pathlib import Path

#: Canonical GE extension — flavour is detected per chunk.
HYBRID_SUFFIXES = (".ge",)

#: Source variants that use the TypeScript-flavoured frontend.
#: `.ge.ts` is canonical; `.ts.ge.py` is accepted for compatibility with
#: projects scaffolded before the extension was settled.
TYPESCRIPT_SUFFIXES = (".ge.ts", ".ts.ge.py")

#: Source variants that use the Python-flavoured frontend.
PYTHON_SUFFIXES = (".ge.py",)

#: Longest-first so `.ge.py` is not mistaken for `.ge`, and `.ts.ge.py` is
#: not mistaken for `.ge.py`.
ALL_SUFFIXES = tuple(sorted(
    PYTHON_SUFFIXES + TYPESCRIPT_SUFFIXES + HYBRID_SUFFIXES,
    key=len, reverse=True))


def _match_suffix(name: str, suffixes: tuple[str, ...]) -> str | None:
    """Return the longest suffix in `suffixes` that `name` ends with."""
    lowered = name.lower()
    for suffix in sorted(suffixes, key=len, reverse=True):
        if lowered.endswith(suffix):
            return suffix
    return None


def frontend_for(path: Path | str) -> str:
    """Return the frontend name for a source path.

    One of "hybrid" (.ge), "typescript" (.ge.ts), or "python" (.ge.py).
    """
    name = Path(path).name
    if _match_suffix(name, TYPESCRIPT_SUFFIXES):
        return "typescript"
    if _match_suffix(name, PYTHON_SUFFIXES):
        return "python"
    if _match_suffix(name, HYBRID_SUFFIXES):
        return "hybrid"
    return "python"


def is_ge_source(path: Path | str) -> bool:
    """True if the path looks like a GE source file in any supported flavour."""
    return _match_suffix(Path(path).name, ALL_SUFFIXES) is not None


def python_flavour_of(path: Path | str) -> str:
    """Return the .ge.py style name for a path, whichever flavour it is.

    Used so a project keeps a single canonical module name regardless of
    which flavour the author chose:

        app/memory.ge      -> app/memory.ge.py
        app/memory.ge.ts   -> app/memory.ge.py
        app/memory.ge.py   -> app/memory.ge.py
    """
    p = Path(path)
    suffix = _match_suffix(p.name, ALL_SUFFIXES)
    if suffix is None:
        return str(p)
    return str(p.with_name(p.name[: -len(suffix)] + ".ge.py"))
