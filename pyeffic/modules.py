"""Module/import system for GE.

Resolves `from module import function` statements by finding the
corresponding `.ge.py` file and merging its functions into the
current compilation unit.

Supported import syntax:
    from mymodule import my_function
    from mymodule import func1, func2
    from .mymodule import func  (relative import)

The module file is searched in:
1. The same directory as the source file
2. The GE standard library directory (future)
"""
from __future__ import annotations

import ast
from pathlib import Path
from .analyzer import FuncUnit, parse_source_full, ClassUnit, collect_constants, collect_preamble
from .frontends import frontend_for, python_flavour_of


#: Modules provided by the compiler itself. Importing them is how a source
#: file selects a backend decorator; they must never be resolved as user code.
_COMPILER_MODULES = ("pyeffic", "__future__")


def _is_compiler_module(module_name: str) -> bool:
    """True if the import names a compiler-provided module."""
    head = module_name.lstrip(".").split(".")[0]
    return head in _COMPILER_MODULES


def _lower_source(source: str, path: Path | None = None) -> str:
    flavour = frontend_for(path) if path is not None else "python"
    if flavour == "typescript":
        from .frontends.typescript import ts_to_python
        return ts_to_python(source)
    if flavour == "hybrid":
        from .frontends.hybrid import hybrid_to_python
        return hybrid_to_python(source)
    return source


def _parse_source(source: str, path: Path | None = None) -> tuple[list[FuncUnit], list[ClassUnit]]:
    """Parse source using the frontend that matches the file flavour."""
    if path is not None and frontend_for(path) != "python":
        from .analyzer import parse_source_full as _parse_py
        return _parse_py(_lower_source(source, path))
    return parse_source_full(source)


def _collect_constants(source: str, path: Path | None = None) -> dict[str, object]:
    """Collect module-level constants using the matching frontend."""
    if path is not None and frontend_for(path) != "python":
        return collect_constants(_lower_source(source, path))
    return collect_constants(source)


def _collect_preamble(source: str, path: Path | None = None) -> dict[str, str]:
    """Collect ge_preamble/gePreamble blocks using the matching frontend."""
    if path is not None and frontend_for(path) != "python":
        return collect_preamble(_lower_source(source, path))
    return collect_preamble(source)


def resolve_imports(source: str, source_path: Path) -> tuple[list[FuncUnit], list[ClassUnit], list[str]]:
    """Parse source, resolve all imports (transitively), and return merged units.

    Imports are followed recursively so a module that only re-exports from
    other modules (an aggregator) still contributes the full function set.
    Each module file is visited once; cycles are broken by the visited set.

    Returns:
        (units, classes, warnings)
    """
    warnings: list[str] = []
    source_dir = source_path.parent if source_path else Path(".")

    units: list[FuncUnit] = []
    classes: list[ClassUnit] = []
    constants: dict[str, object] = {}
    preamble: dict[str, str] = {}
    seen_modules: set[str] = set()
    seen_units: set[str] = set()
    seen_classes: set[str] = set()

    def _merge_preamble(src_preamble: dict[str, str]) -> None:
        for bk, code in src_preamble.items():
            if bk in preamble:
                preamble[bk] += "\n" + code
            else:
                preamble[bk] = code

    def _visit(module_source: str, base_dir: Path, module_key: str, depth: int,
               module_path: Path | None = None) -> None:
        """Parse one module and recurse into its imports (depth-first)."""
        if module_key in seen_modules or depth > 64:
            return
        seen_modules.add(module_key)

        # Non-Python flavours are lowered before the import scan; the same
        # frontend also builds the IR below.
        scan_source = _lower_source(module_source, module_path)
        tree = ast.parse(scan_source)

        # 1) recurse into this module's imports first (dependencies before dependents)
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            module_name = node.module or ""
            if not module_name:
                continue
            if _is_compiler_module(module_name):
                # GE runtime modules (`from pyeffic.backends import rust`) are
                # compiler intrinsics, not user code — resolving them would
                # pull the compiler's own sources into the program.
                continue
            dep_path = _find_module(module_name, base_dir)
            if dep_path is None or not dep_path.exists():
                if depth == 0:
                    warnings.append(f"could not find module '{module_name}' at line {node.lineno}")
                continue
            dep_source = dep_path.read_text(encoding="utf-8")
            dep_key = str(dep_path.resolve())
            _visit(dep_source, dep_path.parent, dep_key, depth + 1, dep_path)

        # 2) then add this module's own definitions
        mod_units, mod_classes = _parse_source(module_source, module_path)
        for u in mod_units:
            if u.name not in seen_units:
                seen_units.add(u.name)
                units.append(u)
        for c in mod_classes:
            if c.name not in seen_classes:
                seen_classes.add(c.name)
                classes.append(c)
        constants.update(_collect_constants(module_source, module_path))
        _merge_preamble(_collect_preamble(module_source, module_path))

    _visit(source, source_dir, str(source_path.resolve()) if source_path else "<source>", 0,
           source_path)

    globals()["_LAST_CONSTANTS"] = constants
    globals()["_LAST_PREAMBLE"] = preamble

    return units, classes, warnings


def get_last_constants() -> dict[str, object]:
    """Return the constants collected during the last resolve_imports call."""
    return globals().get("_LAST_CONSTANTS", {})


def get_last_preamble() -> dict[str, str]:
    """Return the preamble collected during the last resolve_imports call."""
    return globals().get("_LAST_PREAMBLE", {})


def _find_module(module_name: str, source_dir: Path) -> Path | None:
    """Find a GE source file for the given module name.

    Both flavours are searched, Python-like first:
        app.main -> app/main.ge.py, app/main.ts.ge.py, app/main.ge.ts
    """
    # handle relative imports (from .module import ...)
    if module_name.startswith("."):
        module_name = module_name.lstrip(".")

    # handle dotted module names: app.main -> app/main.ge.py
    parts = module_name.split(".")
    base = parts[-1]
    # candidate file names for the module leaf, in preference order.
    # `.ge` (hybrid) is canonical; the single-flavour variants are honoured
    # next, and a plain .py is the last resort.
    leaf_names = (f"{base}.ge", f"{base}.ge.py", f"{base}.ge.ts",
                  f"{base}.ts.ge.py", f"{base}.py")

    # search in source_dir and parent directories (up to 3 levels)
    search_dirs = [source_dir]
    parent = source_dir.parent
    for _ in range(3):
        search_dirs.append(parent)
        parent = parent.parent

    for search_dir in search_dirs:
        if len(parts) > 1:
            # dotted name: only resolve relative to the package path.
            # app.main -> search_dir/app/main.ge.py
            # Never fall back to matching just the leaf, or `app.main` would
            # wrongly resolve to a sibling `main.ge.py`.
            pkg_dir = search_dir.joinpath(*parts[:-1])
            for leaf in leaf_names:
                candidate = pkg_dir / leaf
                if candidate.exists():
                    return candidate
            # package directory: app/main/__init__.ge
            for leaf in ("__init__.ge", "__init__.ge.py", "__init__.ge.ts",
                         "__init__.py"):
                candidate = pkg_dir / leaf
                if candidate.exists():
                    return candidate
            continue

        # simple name: search_dir/<name>.<flavour>
        for leaf in leaf_names:
            candidate = search_dir / leaf
            if candidate.exists():
                return candidate

        # search_dir / name / __init__.ge
        pkg_dir = search_dir / module_name
        for leaf in ("__init__.ge", "__init__.ge.py", "__init__.ge.ts",
                     "__init__.py"):
            candidate = pkg_dir / leaf
            if candidate.exists():
                return candidate

    return None
