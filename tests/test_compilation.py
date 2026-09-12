"""Test end-to-end compilation: Python source → Rust binary → execute → verify output."""
import unittest
import tempfile
import os
from pathlib import Path
from pyeffic.config import Config, detect_compilers
from pyeffic.pipeline import build


class TestEndToEndCompilation(unittest.TestCase):
    """Test that GE source compiles to a native binary and produces correct output."""

    @classmethod
    def setUpClass(cls):
        cls.info = detect_compilers()
        cls.has_rust = cls.info.rustc is not None

    def _compile_and_run(self, source: str) -> str:
        """Compile source to a native binary, run it, return stdout."""
        if not self.has_rust:
            self.skipTest("rustc not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(source, encoding="utf-8")
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                        force_backend="rust")  # force Rust for consistent testing
            report = build(src, cfg, entry="main")
            if not report.rust_compile or not report.rust_compile.ok:
                self.fail(f"Compilation failed: {report.rust_compile.log[:500] if report.rust_compile else 'no compile'}")
            exe = report.rust_compile.exe
            import subprocess
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            return r.stdout.strip()

    def test_simple_arithmetic(self):
        source = """
def main() -> None:
    print(2 + 3)
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "5")

    def test_function_call(self):
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "30")

    def test_for_loop_sum(self):
        source = """
def sum_n(n: int) -> int:
    total: int = 0
    for i in range(0, n):
        total = total + i
    return total
def main() -> None:
    print(sum_n(5))
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "10")  # 0+1+2+3+4 = 10

    def test_if_else(self):
        source = """
def classify(x: int) -> int:
    if x > 0:
        return 1
    return 0
def main() -> None:
    print(classify(5))
    print(classify(-3))
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "1\n0")

    def test_while_loop(self):
        source = """
def countdown(n: int) -> int:
    count: int = 0
    while n > 0:
        n = n - 1
        count = count + 1
    return count
def main() -> None:
    print(countdown(5))
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "5")

    def test_list_indexing(self):
        source = """
def get_first(vals: list) -> int:
    return vals[0]
def main() -> None:
    vals: list = [10, 20, 30]
    print(get_first(vals))
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "10")

    def test_nested_function_calls(self):
        source = """
def double(x: int) -> int:
    return x * 2
def quadruple(x: int) -> int:
    return double(double(x))
def main() -> None:
    print(quadruple(5))
"""
        output = self._compile_and_run(source)
        self.assertEqual(output, "20")

    def test_myrent_logic(self):
        """Test the core MyRent late_fee calculation."""
        source = """
def late_fee(days_late: int, rent: int, grace: int, flat_cents: int,
             pct_bps: int, daily_cents: int, max_cents: int) -> int:
    if days_late <= grace:
        return 0
    effective: int = days_late - grace
    fee: int = flat_cents
    fee = fee + rent * pct_bps // 10000
    fee = fee + effective * daily_cents
    if max_cents > 0:
        if fee > max_cents:
            fee = max_cents
    return fee
def main() -> None:
    print(late_fee(5, 95000, 3, 2500, 500, 500, 10000))
"""
        output = self._compile_and_run(source)
        # days_late=5, grace=3, effective=2
        # fee = 2500 + 95000*500//10000 + 2*500 = 2500 + 4750 + 1000 = 8250
        self.assertEqual(output, "8250")


if __name__ == "__main__":
    unittest.main()
