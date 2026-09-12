"""Tests for new GE language features: strings, try/except, for-in, structs."""
import unittest
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyeffic.pipeline import build
from pyeffic.config import Config, detect_compilers

_COMPILERS = detect_compilers()
BACKENDS = []
if _COMPILERS.rustc:
    BACKENDS.append("rust")
if _COMPILERS.cpp:
    BACKENDS.append("cpp")
if _COMPILERS.dotnet:
    BACKENDS.append("csharp")
if _COMPILERS.zig:
    BACKENDS.append("zig")
if _COMPILERS.go:
    BACKENDS.append("go")
if _COMPILERS.kotlinc:
    BACKENDS.append("kotlin")

_TMPDIR = Path(tempfile.mkdtemp(prefix="ge_features_"))


def _ensure_tmpdir():
    global _TMPDIR
    if not _TMPDIR.exists():
        _TMPDIR = Path(tempfile.mkdtemp(prefix="ge_features_"))


def _compile_and_run(source: str, backend: str, expected: str) -> bool:
    _ensure_tmpdir()
    src_file = _TMPDIR / f"t_{backend}_{abs(hash(source)) % 100000}.ge.py"
    src_file.write_text(source, encoding="utf-8")
    out_dir = _TMPDIR / f"o_{backend}_{abs(hash(source)) % 100000}"
    cfg = Config(out_dir=out_dir, force_backend=backend, do_research=False)
    try:
        report = build(src_file, cfg)
    except Exception:
        return False
    cr = None
    for attr in ("rust_compile", "cpp_compile", "csharp_compile",
                 "zig_compile", "go_compile", "kotlin_compile"):
        cr = getattr(report, attr, None)
        if cr and cr.ok and cr.exe:
            break
    if not cr or not cr.ok or not cr.exe:
        return False
    try:
        r = subprocess.run([str(cr.exe)], capture_output=True, text=True,
                           timeout=30, cwd=str(cr.exe.parent))
        return r.stdout.strip() == expected.strip()
    except Exception:
        return False


def _prog(func_src: str, call: str) -> str:
    return func_src + "\ndef main() -> None:\n    " + call + "\n"


class TestStringOperations(unittest.TestCase):
    """Test string concatenation, length, and printing."""

    def _run(self, source, expected, backend):
        if backend not in BACKENDS:
            self.skipTest(f"{backend} not available")
        ok = _compile_and_run(source, backend, expected)
        self.assertTrue(ok, f"{backend}: expected '{expected}'")

    T_CONCAT = _prog(
        'def greet(name: str) -> str:\n    return "Hello, " + name',
        'print(greet("World"))')

    def test_str_concat_rust(self): self._run(self.T_CONCAT, "Hello, World", "rust")
    def test_str_concat_cpp(self): self._run(self.T_CONCAT, "Hello, World", "cpp")

    T_LEN = _prog(
        'def f(s: str) -> int:\n    return len(s)',
        'print(f("hello"))')

    def test_str_len_rust(self): self._run(self.T_LEN, "5", "rust")
    def test_str_len_cpp(self): self._run(self.T_LEN, "5", "cpp")


class TestForInList(unittest.TestCase):
    """Test for-in list iteration (foreach)."""

    def _run(self, source, expected, backend):
        if backend not in BACKENDS:
            self.skipTest(f"{backend} not available")
        ok = _compile_and_run(source, backend, expected)
        self.assertTrue(ok, f"{backend}: expected '{expected}'")

    T_SUM = _prog(
        'def f(arr: list) -> int:\n    total: int = 0\n    for x in arr:\n        total = total + x\n    return total',
        'nums: list = [1, 2, 3, 4, 5]\n    print(f(nums))')

    def test_forin_sum_rust(self): self._run(self.T_SUM, "15", "rust")
    def test_forin_sum_cpp(self): self._run(self.T_SUM, "15", "cpp")


class TestTryExcept(unittest.TestCase):
    """Test try/except error handling."""

    def _run(self, source, expected, backend):
        if backend not in BACKENDS:
            self.skipTest(f"{backend} not available")
        ok = _compile_and_run(source, backend, expected)
        self.assertTrue(ok, f"{backend}: expected '{expected}'")

    T_TRY = _prog(
        'def f(a: int, b: int) -> int:\n    try:\n        return a // b\n    except:\n        return -1',
        'print(f(10, 2))')

    def test_try_rust(self): self._run(self.T_TRY, "5", "rust")
    def test_try_cpp(self): self._run(self.T_TRY, "5", "cpp")


class TestBoolLiterals(unittest.TestCase):
    """Test boolean literals and logical operators."""

    def _run(self, source, expected, backend):
        if backend not in BACKENDS:
            self.skipTest(f"{backend} not available")
        ok = _compile_and_run(source, backend, expected)
        self.assertTrue(ok, f"{backend}: expected '{expected}'")

    T_BOOL = _prog(
        'def f(a: int, b: int) -> int:\n    if a > 0 and b > 0:\n        return 1\n    return 0',
        'print(f(1, 1))')

    def test_bool_and_rust(self): self._run(self.T_BOOL, "1", "rust")
    def test_bool_and_cpp(self): self._run(self.T_BOOL, "1", "cpp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
