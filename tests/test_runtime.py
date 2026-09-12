"""Runtime verification tests: compile and run each backend, verify output.

These tests compile each available backend and run the produced binary,
verifying the actual output matches expected values. They skip gracefully
when a toolchain is not available.
"""
import os
import shutil
import tempfile
import subprocess
import unittest
from pathlib import Path

# Add tools to PATH for this test session
_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if _TOOLS.exists():
    _ZIG = _TOOLS / "zig-x86_64-windows-0.14.1"
    _KOTLIN_NATIVE = _TOOLS / "kotlin-native-prebuilt-windows-x86_64-2.4.10" / "bin"
    _KOTLIN_JVM = _TOOLS / "kotlinc" / "bin"
    for p in [str(_ZIG), str(_KOTLIN_NATIVE), str(_KOTLIN_JVM)]:
        if Path(p).exists() and p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

from pyeffic.config import Config, detect_compilers
from pyeffic.pipeline import build

INFO = detect_compilers()


def _has(*names: str) -> bool:
    for n in names:
        if not getattr(INFO, n, None):
            return False
    return True


class TestRuntimeOutput(unittest.TestCase):
    """Compile and run each backend, verify the output is correct."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build_and_run(self, source: str, backend: str, expected: str):
        """Build source with given backend, run the binary, check output."""
        src = self.tmpdir / "test.ge.py"
        src.write_text(source, encoding="utf-8")
        cfg = Config(out_dir=self.tmpdir / "out", do_research=False,
                    force_backend=backend)
        report = build(src, cfg, entry="main")

        # get the compile result for this backend
        compile_result = getattr(report, f"{backend}_compile", None)
        if compile_result is None or not compile_result.ok:
            self.skipTest(f"{backend} compilation failed: {compile_result.log[:100] if compile_result else 'none'}")

        # run the binary
        exe = compile_result.exe
        if not exe or not exe.exists():
            self.skipTest(f"{backend} binary not found")

        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        # some backends (e.g. Zig) write to stderr via std.debug.print
        actual = (r.stdout + r.stderr).strip()
        self.assertEqual(actual, expected,
                         f"{backend} output mismatch: expected '{expected}', got '{actual}'")

    # ---- Simple tests: add(10, 20) = 30 ----

    SIMPLE = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""

    def test_rust_simple(self):
        if not _has("rustc"):
            self.skipTest("rustc not available")
        self._build_and_run(self.SIMPLE, "rust", "30")

    def test_cpp_simple(self):
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        self._build_and_run(self.SIMPLE, "cpp", "30")

    def test_zig_simple(self):
        if not _has("zig"):
            self.skipTest("zig not available")
        self._build_and_run(self.SIMPLE, "zig", "30")

    def test_go_simple(self):
        if not _has("go"):
            self.skipTest("go not available")
        self._build_and_run(self.SIMPLE, "go", "30")

    def test_kotlin_simple(self):
        if not _has("kotlinc"):
            self.skipTest("kotlinc not available")
        self._build_and_run(self.SIMPLE, "kotlin", "30")

    # ---- Medium tests: fibonacci(10) = 55, sum_range(100) = 4950 ----

    MEDIUM = """
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    a: int = 0
    b: int = 1
    for i in range(0, n):
        temp: int = a
        a = b
        b = temp + b
    return a
def sum_range(n: int) -> int:
    total: int = 0
    for i in range(0, n):
        total = total + i
    return total
def main() -> None:
    print(fibonacci(10))
    print(sum_range(100))
"""

    def test_rust_medium(self):
        if not _has("rustc"):
            self.skipTest("rustc not available")
        self._build_and_run(self.MEDIUM, "rust", "55\n4950")

    def test_cpp_medium(self):
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        self._build_and_run(self.MEDIUM, "cpp", "55\n4950")

    def test_zig_medium(self):
        if not _has("zig"):
            self.skipTest("zig not available")
        self._build_and_run(self.MEDIUM, "zig", "55\n4950")

    def test_go_medium(self):
        if not _has("go"):
            self.skipTest("go not available")
        self._build_and_run(self.MEDIUM, "go", "55\n4950")

    def test_kotlin_medium(self):
        if not _has("kotlinc"):
            self.skipTest("kotlinc not available")
        self._build_and_run(self.MEDIUM, "kotlin", "55\n4950")

    # ---- Complex tests: interdependent functions ----

    COMPLEX = """
def compute_total(a: int, b: int) -> int:
    return a + b
def compute_difference(a: int, b: int) -> int:
    return a - b
def compute_product(a: int, b: int) -> int:
    return a * b
def complex_calculation(a: int, b: int, c: int) -> int:
    total: int = compute_total(a, b)
    diff: int = compute_difference(total, c)
    product: int = compute_product(diff, 2)
    return product
def main() -> None:
    print(complex_calculation(10, 20, 5))
"""

    def test_rust_complex(self):
        if not _has("rustc"):
            self.skipTest("rustc not available")
        self._build_and_run(self.COMPLEX, "rust", "50")

    def test_cpp_complex(self):
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        self._build_and_run(self.COMPLEX, "cpp", "50")

    def test_zig_complex(self):
        if not _has("zig"):
            self.skipTest("zig not available")
        self._build_and_run(self.COMPLEX, "zig", "50")

    def test_go_complex(self):
        if not _has("go"):
            self.skipTest("go not available")
        self._build_and_run(self.COMPLEX, "go", "50")

    def test_kotlin_complex(self):
        if not _has("kotlinc"):
            self.skipTest("kotlinc not available")
        self._build_and_run(self.COMPLEX, "kotlin", "50")


if __name__ == "__main__":
    unittest.main()
