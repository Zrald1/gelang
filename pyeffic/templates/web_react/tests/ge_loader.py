"""Import hook for .ge.py modules.

Python cannot import `app/core/add.ge.py` as `app.core.add`, so this module
installs a meta path finder that maps dotted names onto .ge.py files.
"""
import importlib.abc
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
_installed = False


def _stub_preamble(backend, code):  # noqa: ARG001
    """No-op stand-in for the GE ge_preamble intrinsic."""
    return None


def _stub_value(*args, **kwargs):  # noqa: ARG001
    """No-op stand-in for ge_inline / ge_raw; returns int 0."""
    return 0


class GeFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve `pkg.mod` to `pkg/mod.ge.py` under the project root."""

    @staticmethod
    def _ge_path(parts: list[str]) -> Path:
        return ROOT.joinpath(*parts[:-1]) / (parts[-1] + ".ge.py")

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        ge_path = self._ge_path(parts)
        if ge_path.is_file():
            return importlib.util.spec_from_loader(fullname, self)
        pkg_dir = ROOT.joinpath(*parts)
        init = pkg_dir / "__init__.py"
        if init.is_file():
            return importlib.util.spec_from_file_location(
                fullname, init, submodule_search_locations=[str(pkg_dir)])
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        parts = module.__name__.split(".")
        ge_path = self._ge_path(parts)
        code = ge_path.read_text(encoding="utf-8")
        ns = module.__dict__
        ns.setdefault("ge_preamble", _stub_preamble)
        ns.setdefault("ge_inline", _stub_value)
        ns.setdefault("ge_raw", _stub_value)
        exec(compile(code, str(ge_path), "exec"), ns)


def install() -> None:
    """Install the .ge.py import hook (idempotent)."""
    global _installed
    if _installed:
        return
    if not any(isinstance(f, GeFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, GeFinder())
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    _installed = True
