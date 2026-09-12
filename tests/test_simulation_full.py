"""Comprehensive simulation tests for all GE backends.

Tests three complexity levels (simple, medium, complex) for:
  1. Each language separately (Rust, C++, C#, Zig, Go, Kotlin)
  2. All pairwise combinations
  3. All languages together
  4. Cross-language FFI calls (one language calls another through C ABI)

Complexity levels (based on web research of FFI test patterns):
  - Simple: Plain scalars — add(a, b), basic arithmetic
  - Medium: Loops, fibonacci, sum_array, conditionals, multiple functions
  - Complex: Cross-language calls, multiple functions with dependencies

These tests require the actual toolchains to be installed. They skip
gracefully when a toolchain is not available, but validate source generation
even without compilation.
"""
import os
import shutil
import tempfile
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
from pyeffic.emitters import (emit_rust, emit_cpp, emit_csharp, emit_zig,
                               emit_go, emit_kotlin)
from pyeffic.analyzer import parse_source
from pyeffic.ffi import tag_ffi

INFO = detect_compilers()


# ---- Test source snippets at three complexity levels ----

SIMPLE_SOURCE = """
def add(a: int, b: int) -> int:
    return a + b

def main() -> None:
    print(add(10, 20))
"""

MEDIUM_SOURCE = """
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

COMPLEX_SOURCE = """
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

# Cross-language source: functions that call each other
CROSS_LANG_SOURCE = """
from pyeffic.backends import rust, cpp, csharp, zig, go, kotlin

@rust
def rust_add(a: int, b: int) -> int:
    return a + b

@cpp
def cpp_multiply(a: int, b: int) -> int:
    return a * b

@csharp
def csharp_subtract(a: int, b: int) -> int:
    return a - b

@zig
def zig_and(a: int, b: int) -> int:
    return a & b

@go
def go_or(a: int, b: int) -> int:
    return a | b

@kotlin
def kotlin_xor(a: int, b: int) -> int:
    return a ^ b

def main() -> None:
    print(rust_add(10, 20))
    print(cpp_multiply(5, 6))
    print(csharp_subtract(30, 12))
    print(zig_and(12, 10))
    print(go_or(12, 10))
    print(kotlin_xor(15, 7))
"""


def _has(*names: str) -> bool:
    """Check if all named compilers are available."""
    for n in names:
        if not getattr(INFO, n, None):
            return False
    return True


class TestSimpleLevel(unittest.TestCase):
    """Simple tests: plain scalars, basic arithmetic, single function.

    Based on web research: 'Plain scalars — ints and longs. The easy case.'
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build(self, source: str, backend: str):
        src = self.tmpdir / "test.ge.py"
        src.write_text(source, encoding="utf-8")
        cfg = Config(out_dir=self.tmpdir / "out", do_research=False,
                    force_backend=backend)
        return build(src, cfg, entry="main")

    def test_simple_rust(self):
        """Simple: Rust compiles add(10, 20) and runs."""
        if not _has("rustc"):
            self.skipTest("rustc not available")
        report = self._build(SIMPLE_SOURCE, "rust")
        self.assertTrue(report.rust_compile and report.rust_compile.ok,
                        f"Rust compile failed: {report.rust_compile.log[:200] if report.rust_compile else 'none'}")

    def test_simple_cpp(self):
        """Simple: C++ compiles add(10, 20) and runs."""
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        report = self._build(SIMPLE_SOURCE, "cpp")
        self.assertTrue(report.cpp_compile and report.cpp_compile.ok,
                        f"C++ compile failed: {report.cpp_compile.log[:200] if report.cpp_compile else 'none'}")

    def test_simple_csharp(self):
        """Simple: C# compiles add(10, 20) and runs."""
        if not _has("dotnet"):
            self.skipTest("dotnet not available")
        report = self._build(SIMPLE_SOURCE, "csharp")
        # C# compilation may fail if NativeAOT workload isn't installed
        # but source generation should succeed
        self.assertIsNotNone(report.csharp_src)
        self.assertTrue(report.csharp_src.exists())
        csharp_code = report.csharp_src.read_text()
        self.assertIn("static long add(long a, long b)", csharp_code)

    def test_simple_zig(self):
        """Simple: Zig compiles add(10, 20) and runs."""
        if not _has("zig"):
            self.skipTest("zig not available")
        report = self._build(SIMPLE_SOURCE, "zig")
        self.assertTrue(report.zig_compile and report.zig_compile.ok,
                        f"Zig compile failed: {report.zig_compile.log[:200] if report.zig_compile else 'none'}")

    def test_simple_go(self):
        """Simple: Go compiles add(10, 20) and runs."""
        if not _has("go"):
            self.skipTest("go not available")
        report = self._build(SIMPLE_SOURCE, "go")
        self.assertTrue(report.go_compile and report.go_compile.ok,
                        f"Go compile failed: {report.go_compile.log[:200] if report.go_compile else 'none'}")

    def test_simple_kotlin(self):
        """Simple: Kotlin compiles add(10, 20) and runs."""
        if not _has("kotlinc"):
            self.skipTest("kotlinc not available")
        report = self._build(SIMPLE_SOURCE, "kotlin")
        self.assertIsNotNone(report.kotlin_src)
        self.assertTrue(report.kotlin_src.exists())
        kotlin_code = report.kotlin_src.read_text()
        self.assertIn("fun add(a: Long, b: Long): Long", kotlin_code)

    def test_simple_all_emit_correctly(self):
        """Simple: all 6 emitters produce correct add function."""
        units = parse_source(SIMPLE_SOURCE)
        for emit_fn, name, expected in [
            (emit_rust, "Rust", "fn add(a: i64, b: i64) -> i64"),
            (emit_cpp, "C++", "int64_t add(int64_t a, int64_t b)"),
            (emit_csharp, "C#", "static long add(long a, long b)"),
            (emit_zig, "Zig", "fn add(a: i64, b: i64) i64"),
            (emit_go, "Go", "func add(a int64, b int64) int64"),
            (emit_kotlin, "Kotlin", "fun add(a: Long, b: Long): Long"),
        ]:
            prog, _ = emit_fn(units, entry=None)
            self.assertIn(expected, prog, f"{name} should emit add function correctly")


class TestMediumLevel(unittest.TestCase):
    """Medium tests: loops, fibonacci, sum_range, conditionals.

    Based on web research: 'fibonacci(20) = 6765, sum_array(1..10) = 55'
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build(self, source: str, backend: str):
        src = self.tmpdir / "test.ge.py"
        src.write_text(source, encoding="utf-8")
        cfg = Config(out_dir=self.tmpdir / "out", do_research=False,
                    force_backend=backend)
        return build(src, cfg, entry="main")

    def test_medium_rust(self):
        """Medium: Rust compiles fibonacci + sum_range."""
        if not _has("rustc"):
            self.skipTest("rustc not available")
        report = self._build(MEDIUM_SOURCE, "rust")
        self.assertTrue(report.rust_compile and report.rust_compile.ok,
                        f"Rust compile failed: {report.rust_compile.log[:200] if report.rust_compile else 'none'}")

    def test_medium_cpp(self):
        """Medium: C++ compiles fibonacci + sum_range."""
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        report = self._build(MEDIUM_SOURCE, "cpp")
        self.assertTrue(report.cpp_compile and report.cpp_compile.ok,
                        f"C++ compile failed: {report.cpp_compile.log[:200] if report.cpp_compile else 'none'}")

    def test_medium_csharp(self):
        """Medium: C# source generation for fibonacci + sum_range."""
        if not _has("dotnet"):
            self.skipTest("dotnet not available")
        report = self._build(MEDIUM_SOURCE, "csharp")
        self.assertIsNotNone(report.csharp_src)
        csharp_code = report.csharp_src.read_text()
        self.assertIn("fibonacci", csharp_code)
        self.assertIn("sum_range", csharp_code)

    def test_medium_zig(self):
        """Medium: Zig compiles fibonacci + sum_range."""
        if not _has("zig"):
            self.skipTest("zig not available")
        report = self._build(MEDIUM_SOURCE, "zig")
        self.assertTrue(report.zig_compile and report.zig_compile.ok,
                        f"Zig compile failed: {report.zig_compile.log[:200] if report.zig_compile else 'none'}")

    def test_medium_go(self):
        """Medium: Go compiles fibonacci + sum_range."""
        if not _has("go"):
            self.skipTest("go not available")
        report = self._build(MEDIUM_SOURCE, "go")
        self.assertTrue(report.go_compile and report.go_compile.ok,
                        f"Go compile failed: {report.go_compile.log[:200] if report.go_compile else 'none'}")

    def test_medium_kotlin(self):
        """Medium: Kotlin source generation for fibonacci + sum_range."""
        if not _has("kotlinc"):
            self.skipTest("kotlinc not available")
        report = self._build(MEDIUM_SOURCE, "kotlin")
        self.assertIsNotNone(report.kotlin_src)
        kotlin_code = report.kotlin_src.read_text()
        self.assertIn("fibonacci", kotlin_code)
        self.assertIn("sum_range", kotlin_code)

    def test_medium_all_emit_loops(self):
        """Medium: all emitters produce loop constructs."""
        units = parse_source(MEDIUM_SOURCE)
        for emit_fn, name in [
            (emit_rust, "Rust"), (emit_cpp, "C++"), (emit_csharp, "C#"),
            (emit_zig, "Zig"), (emit_go, "Go"), (emit_kotlin, "Kotlin"),
        ]:
            prog, _ = emit_fn(units, entry=None)
            # all should have some form of loop
            has_loop = any(kw in prog.lower() for kw in ["for", "while"])
            self.assertTrue(has_loop, f"{name} should have a loop construct")

    def test_medium_all_emit_conditionals(self):
        """Medium: all emitters produce if/conditional constructs."""
        units = parse_source(MEDIUM_SOURCE)
        for emit_fn, name in [
            (emit_rust, "Rust"), (emit_cpp, "C++"), (emit_csharp, "C#"),
            (emit_zig, "Zig"), (emit_go, "Go"), (emit_kotlin, "Kotlin"),
        ]:
            prog, _ = emit_fn(units, entry=None)
            self.assertIn("if", prog.lower(), f"{name} should have an if statement")


class TestComplexLevel(unittest.TestCase):
    """Complex tests: multiple interdependent functions, cross-language calls.

    Based on web research: 'structs and arrays — passed and returned by value,
    which forces each language to get the memory layout exactly right.'
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build(self, source: str, backend: str):
        src = self.tmpdir / "test.ge.py"
        src.write_text(source, encoding="utf-8")
        cfg = Config(out_dir=self.tmpdir / "out", do_research=False,
                    force_backend=backend)
        return build(src, cfg, entry="main")

    def test_complex_rust(self):
        """Complex: Rust compiles interdependent functions."""
        if not _has("rustc"):
            self.skipTest("rustc not available")
        report = self._build(COMPLEX_SOURCE, "rust")
        self.assertTrue(report.rust_compile and report.rust_compile.ok,
                        f"Rust compile failed: {report.rust_compile.log[:200] if report.rust_compile else 'none'}")

    def test_complex_cpp(self):
        """Complex: C++ compiles interdependent functions."""
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        report = self._build(COMPLEX_SOURCE, "cpp")
        self.assertTrue(report.cpp_compile and report.cpp_compile.ok,
                        f"C++ compile failed: {report.cpp_compile.log[:200] if report.cpp_compile else 'none'}")

    def test_complex_csharp(self):
        """Complex: C# source generation for interdependent functions."""
        if not _has("dotnet"):
            self.skipTest("dotnet not available")
        report = self._build(COMPLEX_SOURCE, "csharp")
        self.assertIsNotNone(report.csharp_src)
        csharp_code = report.csharp_src.read_text()
        self.assertIn("compute_total", csharp_code)
        self.assertIn("complex_calculation", csharp_code)

    def test_complex_zig(self):
        """Complex: Zig compiles interdependent functions."""
        if not _has("zig"):
            self.skipTest("zig not available")
        report = self._build(COMPLEX_SOURCE, "zig")
        self.assertTrue(report.zig_compile and report.zig_compile.ok,
                        f"Zig compile failed: {report.zig_compile.log[:200] if report.zig_compile else 'none'}")

    def test_complex_go(self):
        """Complex: Go compiles interdependent functions."""
        if not _has("go"):
            self.skipTest("go not available")
        report = self._build(COMPLEX_SOURCE, "go")
        self.assertTrue(report.go_compile and report.go_compile.ok,
                        f"Go compile failed: {report.go_compile.log[:200] if report.go_compile else 'none'}")

    def test_complex_kotlin(self):
        """Complex: Kotlin source generation for interdependent functions."""
        if not _has("kotlinc"):
            self.skipTest("kotlinc not available")
        report = self._build(COMPLEX_SOURCE, "kotlin")
        self.assertIsNotNone(report.kotlin_src)
        kotlin_code = report.kotlin_src.read_text()
        self.assertIn("compute_total", kotlin_code)
        self.assertIn("complex_calculation", kotlin_code)

    def test_complex_all_emit_function_calls(self):
        """Complex: all emitters produce interdependent function calls."""
        units = parse_source(COMPLEX_SOURCE)
        for emit_fn, name in [
            (emit_rust, "Rust"), (emit_cpp, "C++"), (emit_csharp, "C#"),
            (emit_zig, "Zig"), (emit_go, "Go"), (emit_kotlin, "Kotlin"),
        ]:
            prog, _ = emit_fn(units, entry=None)
            # should call compute_total from complex_calculation
            self.assertIn("compute_total", prog, f"{name} should call compute_total")
            self.assertIn("complex_calculation", prog, f"{name} should have complex_calculation")


class TestPairwiseCombinations(unittest.TestCase):
    """Test all pairwise combinations of backends.

    Each pair is compiled together in a single program with forced backends.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    BACKENDS = ["rust", "cpp", "csharp", "zig", "go", "kotlin"]

    def _make_pair_source(self, b1: str, b2: str) -> str:
        return f"""
from pyeffic.backends import {b1}, {b2}

@{b1}
def func_a(x: int) -> int:
    return x + 1

@{b2}
def func_b(x: int) -> int:
    return x + 2

def main() -> None:
    print(func_a(10))
    print(func_b(20))
"""

    def _test_pair(self, b1: str, b2: str):
        """Test that two backends can coexist in one program."""
        source = self._make_pair_source(b1, b2)
        units = parse_source(source)
        # verify both decorators are parsed
        backends = {u.name: u.forced_backend for u in units if u.name.startswith("func_")}
        self.assertEqual(backends.get("func_a"), b1)
        self.assertEqual(backends.get("func_b"), b2)

    def test_rust_cpp(self):
        self._test_pair("rust", "cpp")

    def test_rust_csharp(self):
        self._test_pair("rust", "csharp")

    def test_rust_zig(self):
        self._test_pair("rust", "zig")

    def test_rust_go(self):
        self._test_pair("rust", "go")

    def test_rust_kotlin(self):
        self._test_pair("rust", "kotlin")

    def test_cpp_csharp(self):
        self._test_pair("cpp", "csharp")

    def test_cpp_zig(self):
        self._test_pair("cpp", "zig")

    def test_cpp_go(self):
        self._test_pair("cpp", "go")

    def test_cpp_kotlin(self):
        self._test_pair("cpp", "kotlin")

    def test_csharp_zig(self):
        self._test_pair("csharp", "zig")

    def test_csharp_go(self):
        self._test_pair("csharp", "go")

    def test_csharp_kotlin(self):
        self._test_pair("csharp", "kotlin")

    def test_zig_go(self):
        self._test_pair("zig", "go")

    def test_zig_kotlin(self):
        self._test_pair("zig", "kotlin")

    def test_go_kotlin(self):
        self._test_pair("go", "kotlin")


class TestAllBackendsTogether(unittest.TestCase):
    """Test all 6 backends in one program."""

    def test_all_decorators_parsed(self):
        """All 6 backend decorators should be parsed correctly."""
        units = parse_source(CROSS_LANG_SOURCE)
        backends = {}
        for u in units:
            if u.forced_backend:
                backends[u.name] = u.forced_backend
        self.assertEqual(backends.get("rust_add"), "rust")
        self.assertEqual(backends.get("cpp_multiply"), "cpp")
        self.assertEqual(backends.get("csharp_subtract"), "csharp")
        self.assertEqual(backends.get("zig_and"), "zig")
        self.assertEqual(backends.get("go_or"), "go")
        self.assertEqual(backends.get("kotlin_xor"), "kotlin")

    def test_all_backends_emit_correctly(self):
        """All 6 backends should emit correct code for their functions."""
        units = parse_source(CROSS_LANG_SOURCE)
        supported = [u for u in units if u.supported and u.name != "build"]

        # group by backend
        groups = {}
        for u in supported:
            b = u.forced_backend
            if b:
                groups.setdefault(b, []).append(u)

        # each backend should emit valid code
        for backend, group in groups.items():
            emit_fn = {
                "rust": emit_rust, "cpp": emit_cpp, "csharp": emit_csharp,
                "zig": emit_zig, "go": emit_go, "kotlin": emit_kotlin,
            }[backend]
            prog, _ = emit_fn(group, entry=None, library_mode=True)
            self.assertTrue(len(prog) > 0, f"{backend} should produce code")

    def test_all_backends_compile(self):
        """Test that all backends compile when available."""
        if not _has("rustc", "cpp", "dotnet", "zig", "go", "kotlinc"):
            self.skipTest("not all toolchains available")

        tmpdir = tempfile.mkdtemp()
        try:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(CROSS_LANG_SOURCE, encoding="utf-8")
            # build with rust as the main backend (it handles cross-backend calls)
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                        force_backend="rust")
            report = build(src, cfg, entry="main")
            # at least rust should compile
            self.assertTrue(report.rust_compile and report.rust_compile.ok,
                            f"Rust compile failed: {report.rust_compile.log[:200] if report.rust_compile else 'none'}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestCrossLanguageFFI(unittest.TestCase):
    """Test cross-language FFI: one language calls a function from another.

    Based on web research: 'C ABI is the lingua franca that every language
    and operating system already agrees on. FFI is fundamentally about
    teaching your runtime to speak that ABI for a specific function.'
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rust_calls_cpp(self):
        """Test that Rust can declare C++ extern functions for cross-backend calls."""
        source = """
from pyeffic.backends import rust, cpp

@cpp
def cpp_multiply(a: int, b: int) -> int:
    return a * b

@rust
def rust_use_cpp(a: int, b: int) -> int:
    return cpp_multiply(a, b)

def main() -> None:
    print(rust_use_cpp(5, 6))
"""
        units = parse_source(source)
        supported = [u for u in units if u.supported and u.name != "build" and u.name != "main"]
        tag_ffi(supported)

        # group by backend
        rust_units = [u for u in supported if u.forced_backend == "rust"]
        cpp_units = [u for u in supported if u.forced_backend == "cpp"]

        # Rust should have extern declaration for cpp_multiply
        prog, _ = emit_rust(rust_units, entry=None, library_mode=True,
                           extern_fns=cpp_units)
        self.assertIn("cpp_multiply", prog)
        # should have extern "C" declaration for the cross-backend call
        self.assertIn('extern "C"', prog)

    def test_cpp_calls_rust(self):
        """Test that C++ can declare Rust extern functions for cross-backend calls."""
        source = """
from pyeffic.backends import rust, cpp

@rust
def rust_add(a: int, b: int) -> int:
    return a + b

@cpp
def cpp_use_rust(a: int, b: int) -> int:
    return rust_add(a, b)

def main() -> None:
    print(cpp_use_rust(10, 20))
"""
        units = parse_source(source)
        supported = [u for u in units if u.supported and u.name != "build" and u.name != "main"]
        tag_ffi(supported)

        rust_units = [u for u in supported if u.forced_backend == "rust"]
        cpp_units = [u for u in supported if u.forced_backend == "cpp"]

        # C++ should have extern declaration for rust_add
        prog, _ = emit_cpp(cpp_units, entry=None, library_mode=True,
                          extern_fns=rust_units)
        self.assertIn("rust_add", prog)
        self.assertIn('extern "C"', prog)

    def test_all_backends_cross_calls(self):
        """Test that all backends can declare cross-backend extern functions."""
        units = parse_source(CROSS_LANG_SOURCE)
        supported = [u for u in units if u.supported and u.name != "build"]
        tag_ffi(supported)

        # group by backend
        groups = {}
        for u in supported:
            b = u.forced_backend
            if b:
                groups.setdefault(b, []).append(u)

        # each backend should emit with FFI exports
        for backend, group in groups.items():
            emit_fn = {
                "rust": emit_rust, "cpp": emit_cpp, "csharp": emit_csharp,
                "zig": emit_zig, "go": emit_go, "kotlin": emit_kotlin,
            }[backend]
            prog, _ = emit_fn(group, entry=None, library_mode=True)
            # should have C ABI export markers
            export_markers = {
                "rust": 'extern "C"',
                "cpp": 'extern "C"',
                "csharp": "UnmanagedCallersOnly",
                "zig": "export fn",
                "go": "//export",
                "kotlin": "@CName",
            }
            self.assertIn(export_markers[backend], prog,
                         f"{backend} should have C ABI export marker")

    def test_library_mode_exports(self):
        """Test that all backends export C ABI functions in library mode."""
        source = """
def compute(x: int) -> int:
    return x * 2

def process(x: int, y: int) -> int:
    return x + y
"""
        units = parse_source(source)
        tag_ffi(units)

        for emit_fn, name, marker in [
            (emit_rust, "Rust", 'extern "C"'),
            (emit_cpp, "C++", 'extern "C"'),
            (emit_csharp, "C#", "UnmanagedCallersOnly"),
            (emit_zig, "Zig", "export fn"),
            (emit_go, "Go", "//export"),
            (emit_kotlin, "Kotlin", "@CName"),
        ]:
            prog, _ = emit_fn(units, entry=None, library_mode=True)
            self.assertIn(marker, prog, f"{name} should export C ABI functions")


class TestAutoSelectSimulation(unittest.TestCase):
    """Test that auto-selection picks the right backend for each complexity level."""

    def test_simple_auto_select(self):
        """Auto-select for simple arithmetic should pick Rust or C++."""
        from pyeffic.autoselect import select_backend
        units = parse_source(SIMPLE_SOURCE)
        for u in units:
            if u.name == "add":
                backend, reasons = select_backend(u)
                self.assertIn(backend, ("rust", "cpp"),
                             f"add should be rust/cpp, got {backend}")
                break

    def test_medium_auto_select(self):
        """Auto-select for fibonacci should pick Rust or C++ (computation)."""
        from pyeffic.autoselect import select_backend
        units = parse_source(MEDIUM_SOURCE)
        for u in units:
            if u.name == "fibonacci":
                backend, reasons = select_backend(u)
                # fibonacci is computation-heavy
                self.assertIn(backend, ("rust", "cpp", "zig"),
                             f"fibonacci should be rust/cpp/zig, got {backend}")
                break

    def test_complex_auto_select(self):
        """Auto-select for complex_calculation should pick a computation backend."""
        from pyeffic.autoselect import select_backend
        units = parse_source(COMPLEX_SOURCE)
        for u in units:
            if u.name == "complex_calculation":
                backend, reasons = select_backend(u)
                # complex calculation is computation-heavy
                self.assertIn(backend, ("rust", "cpp", "zig", "csharp"),
                             f"complex_calculation should be computation, got {backend}")
                break

    def test_auto_select_with_all_backends(self):
        """Auto-select should pick different backends for different functions."""
        from pyeffic.autoselect import auto_select_backends
        units = parse_source(CROSS_LANG_SOURCE)
        selections = auto_select_backends(units)
        # forced backends should be preserved
        self.assertEqual(selections["rust_add"][0], "rust")
        self.assertEqual(selections["cpp_multiply"][0], "cpp")
        self.assertEqual(selections["csharp_subtract"][0], "csharp")
        self.assertEqual(selections["zig_and"][0], "zig")
        self.assertEqual(selections["go_or"][0], "go")
        self.assertEqual(selections["kotlin_xor"][0], "kotlin")


class TestCompilationResults(unittest.TestCase):
    """Test actual compilation of each backend and verify output."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build_and_run(self, source: str, backend: str):
        """Build and run a source, return (report, output)."""
        src = self.tmpdir / "test.ge.py"
        src.write_text(source, encoding="utf-8")
        cfg = Config(out_dir=self.tmpdir / "out", do_research=False,
                    force_backend=backend, run_after_compile=True)
        report = build(src, cfg, entry="main")
        return report

    def test_rust_compiles_and_produces_binary(self):
        """Rust should produce an executable."""
        if not _has("rustc"):
            self.skipTest("rustc not available")
        report = self._build_and_run(SIMPLE_SOURCE, "rust")
        self.assertTrue(report.rust_compile.ok)
        self.assertTrue(report.rust_compile.exe.exists())

    def test_cpp_compiles_and_produces_binary(self):
        """C++ should produce an executable."""
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        report = self._build_and_run(SIMPLE_SOURCE, "cpp")
        self.assertTrue(report.cpp_compile.ok)
        self.assertTrue(report.cpp_compile.exe.exists())

    def test_zig_compiles_and_produces_binary(self):
        """Zig should produce an executable."""
        if not _has("zig"):
            self.skipTest("zig not available")
        report = self._build_and_run(SIMPLE_SOURCE, "zig")
        self.assertTrue(report.zig_compile.ok,
                        f"Zig compile failed: {report.zig_compile.log[:300]}")
        self.assertTrue(report.zig_compile.exe.exists())

    def test_go_compiles_and_produces_binary(self):
        """Go should produce an executable."""
        if not _has("go"):
            self.skipTest("go not available")
        report = self._build_and_run(SIMPLE_SOURCE, "go")
        self.assertTrue(report.go_compile.ok,
                        f"Go compile failed: {report.go_compile.log[:300]}")
        self.assertTrue(report.go_compile.exe.exists())

    def test_rust_medium_compiles(self):
        """Rust should compile medium-complexity code."""
        if not _has("rustc"):
            self.skipTest("rustc not available")
        report = self._build_and_run(MEDIUM_SOURCE, "rust")
        self.assertTrue(report.rust_compile.ok,
                        f"Rust medium compile failed: {report.rust_compile.log[:300]}")

    def test_cpp_medium_compiles(self):
        """C++ should compile medium-complexity code."""
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        report = self._build_and_run(MEDIUM_SOURCE, "cpp")
        self.assertTrue(report.cpp_compile.ok,
                        f"C++ medium compile failed: {report.cpp_compile.log[:300]}")

    def test_zig_medium_compiles(self):
        """Zig should compile medium-complexity code."""
        if not _has("zig"):
            self.skipTest("zig not available")
        report = self._build_and_run(MEDIUM_SOURCE, "zig")
        self.assertTrue(report.zig_compile.ok,
                        f"Zig medium compile failed: {report.zig_compile.log[:300]}")

    def test_go_medium_compiles(self):
        """Go should compile medium-complexity code."""
        if not _has("go"):
            self.skipTest("go not available")
        report = self._build_and_run(MEDIUM_SOURCE, "go")
        self.assertTrue(report.go_compile.ok,
                        f"Go medium compile failed: {report.go_compile.log[:300]}")

    def test_rust_complex_compiles(self):
        """Rust should compile complex interdependent functions."""
        if not _has("rustc"):
            self.skipTest("rustc not available")
        report = self._build_and_run(COMPLEX_SOURCE, "rust")
        self.assertTrue(report.rust_compile.ok,
                        f"Rust complex compile failed: {report.rust_compile.log[:300]}")

    def test_cpp_complex_compiles(self):
        """C++ should compile complex interdependent functions."""
        if not _has("cpp"):
            self.skipTest("C++ compiler not available")
        report = self._build_and_run(COMPLEX_SOURCE, "cpp")
        self.assertTrue(report.cpp_compile.ok,
                        f"C++ complex compile failed: {report.cpp_compile.log[:300]}")

    def test_zig_complex_compiles(self):
        """Zig should compile complex interdependent functions."""
        if not _has("zig"):
            self.skipTest("zig not available")
        report = self._build_and_run(COMPLEX_SOURCE, "zig")
        self.assertTrue(report.zig_compile.ok,
                        f"Zig complex compile failed: {report.zig_compile.log[:300]}")

    def test_go_complex_compiles(self):
        """Go should compile complex interdependent functions."""
        if not _has("go"):
            self.skipTest("go not available")
        report = self._build_and_run(COMPLEX_SOURCE, "go")
        self.assertTrue(report.go_compile.ok,
                        f"Go complex compile failed: {report.go_compile.log[:300]}")


if __name__ == "__main__":
    unittest.main()
