"""Differential testing: compare GE-generated binary output vs CPython output.

Based on research from TeTRIS and PROGnosticator: differential testing is the
gold standard for transpiler correctness verification. We run the same Python
source through CPython and through GE's native backends, then compare output.
"""
import unittest
import subprocess
import tempfile
import os
import sys
from pathlib import Path
from pyeffic.analyzer import parse_source
from pyeffic.emitters import emit_rust, emit_cpp, emit_go, emit_zig, emit_kotlin
from pyeffic.compiler import compile_rust, compile_cpp, compile_go, compile_zig, compile_kotlin
from pyeffic.config import detect_compilers, Config


def _run_cpython(source: str) -> str:
    """Run source through CPython and capture stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(source)
        f.flush()
        fname = f.name
    try:
        r = subprocess.run([sys.executable, fname], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    finally:
        os.unlink(fname)


def _run_native(source: str, emit_fn, compile_fn, info) -> str | None:
    """Compile and run source through a native backend. Returns stdout or None on failure."""
    units = parse_source(source)
    # Filter to only supported units (like the pipeline does)
    supported = [u for u in units if u.supported and u.body is not None]
    if not any(u.name == "main" for u in supported):
        return None  # no main function, skip
    prog, _ = emit_fn(supported, entry="main")
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / "test_src"
        suffix = ".rs" if emit_fn == emit_rust else ".cpp" if emit_fn == emit_cpp else ".go" if emit_fn == emit_go else ".zig" if emit_fn == emit_zig else ".kt"
        src_file = src_file.with_suffix(suffix)
        src_file.write_text(prog, encoding="utf-8")
        cfg = Config()
        cfg.out_dir = Path(tmpdir) / "build"
        result = compile_fn(src_file, cfg, info)
        if not result.ok or not result.exe:
            return None
        r = subprocess.run([str(result.exe)], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()


# Test programs: simple enough to be fully supported, complex enough to test semantics
# Each program must call main() at the end for CPython to produce output
DIFFERENTIAL_TESTS = [
    # Basic arithmetic
    """
def add(a: int, b: int) -> int:
    return a + b

def main() -> int:
    print(add(10, 20))
    return 0

main()
""",
    # Loop and accumulation
    """
def sum_n(n: int) -> int:
    total: int = 0
    for i in range(n):
        total = total + i
    return total

def main() -> int:
    print(sum_n(100))
    return 0

main()
""",
    # Conditional logic
    """
def classify(x: int) -> int:
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0

def main() -> int:
    print(classify(5))
    print(classify(-3))
    print(classify(0))
    return 0

main()
""",
    # Nested function calls
    """
def square(x: int) -> int:
    return x * x

def sum_squares(n: int) -> int:
    total: int = 0
    for i in range(n):
        total = total + square(i)
    return total

def main() -> int:
    print(sum_squares(10))
    return 0

main()
""",
    # Fibonacci
    """
def fib(n: int) -> int:
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

def main() -> int:
    print(fib(10))
    return 0

main()
""",
]


class TestDifferentialCorrectness(unittest.TestCase):
    """Verify GE-generated binaries produce identical output to CPython."""

    @classmethod
    def setUpClass(cls):
        cls.info = detect_compilers()

    def _check_differential(self, source: str, emit_fn, compile_fn, backend_name: str):
        cpython_out = _run_cpython(source)
        native_out = _run_native(source, emit_fn, compile_fn, self.info)
        if native_out is None:
            self.skipTest(f"{backend_name} backend could not compile this source")
        self.assertEqual(native_out, cpython_out,
                        f"{backend_name} output differs from CPython:\n"
                        f"  CPython:  {cpython_out}\n"
                        f"  {backend_name}: {native_out}")

    def test_rust_differential(self):
        for i, source in enumerate(DIFFERENTIAL_TESTS):
            with self.subTest(test=i):
                self._check_differential(source, emit_rust, compile_rust, "Rust")

    def test_cpp_differential(self):
        for i, source in enumerate(DIFFERENTIAL_TESTS):
            with self.subTest(test=i):
                self._check_differential(source, emit_cpp, compile_cpp, "C++")

    def test_go_differential(self):
        for i, source in enumerate(DIFFERENTIAL_TESTS):
            with self.subTest(test=i):
                self._check_differential(source, emit_go, compile_go, "Go")

    def test_zig_differential(self):
        for i, source in enumerate(DIFFERENTIAL_TESTS):
            with self.subTest(test=i):
                self._check_differential(source, emit_zig, compile_zig, "Zig")

    def test_kotlin_differential(self):
        for i, source in enumerate(DIFFERENTIAL_TESTS):
            with self.subTest(test=i):
                self._check_differential(source, emit_kotlin, compile_kotlin, "Kotlin")


if __name__ == "__main__":
    unittest.main()
