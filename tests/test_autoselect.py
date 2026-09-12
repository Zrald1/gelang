"""Tests for the auto-selection rule engine and Kotlin backend.

The auto-selector picks the best backend for each function based on:
  - Function features (arithmetic, concurrency, I/O, etc.)
  - Function name patterns (compute -> C++, fetch -> Go, build -> Dart, etc.)
  - Body patterns (network calls, async calls, etc.)

When no @rust/@cpp/@csharp/@zig/@go/@kotlin decorator is specified,
the auto-selector decides which backend to use.
"""
import unittest
import ast
from pyeffic.analyzer import parse_source, FuncUnit
from pyeffic.autoselect import select_backend, score_backend, auto_select_backends, explain_selection
from pyeffic.emitters import emit_kotlin
from pyeffic.backends import kotlin


class TestAutoSelectionRules(unittest.TestCase):
    """Test that the auto-selector picks the right backend based on function characteristics."""

    def _parse_function(self, source: str) -> FuncUnit:
        """Parse a single function from source and return its FuncUnit."""
        units = parse_source(source)
        # return the first supported function (not 'build')
        for u in units:
            if u.supported and u.name != "build":
                return u
        return units[0]

    def test_compute_function_selects_cpp_or_rust(self):
        """Functions named 'compute_*' should select C++ or Rust (performance-critical)."""
        source = """
def compute_total(a: int, b: int) -> int:
    return a + b
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertIn(backend, ("cpp", "rust"), f"compute should be cpp/rust, got {backend}")

    def test_network_function_selects_go(self):
        """Functions named 'fetch_*' or 'request_*' should select Go (network services)."""
        source = """
def fetch_data(url: int) -> int:
    return url
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "go", f"fetch should be go, got {backend}")

    def test_build_function_selects_dart(self):
        """Functions named 'build' should select Dart (Flutter UI)."""
        source = """
def build():
    pass
"""
        units = parse_source(source)
        # find the build function
        build_unit = None
        for u in units:
            if u.name == "build":
                build_unit = u
                break
        self.assertIsNotNone(build_unit)
        backend, reasons = select_backend(build_unit)
        self.assertEqual(backend, "dart", f"build should be dart, got {backend}")

    def test_memory_function_selects_zig(self):
        """Functions named 'alloc_*' or 'buffer_*' should select Zig (manual memory control)."""
        source = """
def alloc_buffer(size: int) -> int:
    return size
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "zig", f"alloc should be zig, got {backend}")

    def test_business_function_selects_csharp(self):
        """Functions named 'business_*' or 'validate_*' should select C# (enterprise logic)."""
        source = """
def validate_business_rule(amount: int) -> int:
    return amount
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "csharp", f"validate_business should be csharp, got {backend}")

    def test_concurrent_function_selects_go(self):
        """Functions named 'concurrent_*' or 'async_*' should select Go (goroutines)."""
        source = """
def async_handler(request: int) -> int:
    return request
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "go", f"async should be go, got {backend}")

    def test_safe_function_selects_rust(self):
        """Functions named 'safe_*' or 'secure_*' should select Rust (memory safety)."""
        source = """
def safe_verify_token(token: int) -> int:
    return token
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "rust", f"safe should be rust, got {backend}")

    def test_game_function_selects_cpp(self):
        """Functions named 'render_*' or 'physics_*' should select C++ (game engines)."""
        source = """
def render_mesh(vertices: int) -> int:
    return vertices
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "cpp", f"render should be cpp, got {backend}")

    def test_android_function_selects_kotlin(self):
        """Functions named 'android_*' should select Kotlin (Android-native)."""
        source = """
def android_lifecycle(state: int) -> int:
    return state
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "kotlin", f"android should be kotlin, got {backend}")

    def test_default_selection_is_rust(self):
        """When no pattern matches, default to Rust (safest general-purpose)."""
        source = """
def foo(x: int) -> int:
    return x
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertEqual(backend, "rust", f"default should be rust, got {backend}")

    def test_arithmetic_heavy_selects_cpp_or_rust(self):
        """Functions with heavy arithmetic should prefer C++ or Rust."""
        source = """
def calculate(x: int, y: int) -> int:
    total: int = 0
    for i in range(0, y):
        total = total + x * y
    return total
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertIn(backend, ("cpp", "rust"), f"arithmetic should be cpp/rust, got {backend}")

    def test_selection_returns_reasons(self):
        """The auto-selector should return reasons explaining the choice."""
        source = """
def compute_hash(data: int) -> int:
    return data
"""
        unit = self._parse_function(source)
        backend, reasons = select_backend(unit)
        self.assertIsInstance(reasons, list)
        self.assertTrue(len(reasons) > 0, "should have at least one reason")

    def test_explain_selection_returns_string(self):
        """explain_selection should return a human-readable explanation."""
        source = """
def compute_hash(data: int) -> int:
    return data
"""
        unit = self._parse_function(source)
        explanation = explain_selection(unit)
        self.assertIsInstance(explanation, str)
        self.assertIn("compute_hash", explanation)
        self.assertIn("->", explanation)

    def test_score_backend_returns_all_backends(self):
        """score_backend should return scores for all 7 backends."""
        source = """
def foo(x: int) -> int:
    return x
"""
        unit = self._parse_function(source)
        scores = score_backend(unit)
        expected_backends = {"rust", "cpp", "csharp", "zig", "go", "kotlin", "dart"}
        self.assertEqual(set(scores.keys()), expected_backends)

    def test_auto_select_backends_for_multiple_functions(self):
        """auto_select_backends should handle multiple functions."""
        source = """
def compute_total(a: int, b: int) -> int:
    return a + b

def fetch_data(url: int) -> int:
    return url

def safe_verify(token: int) -> int:
    return token
"""
        units = parse_source(source)
        selections = auto_select_backends(units)
        self.assertIn("compute_total", selections)
        self.assertIn("fetch_data", selections)
        self.assertIn("safe_verify", selections)
        # fetch_data should be go
        self.assertEqual(selections["fetch_data"][0], "go")
        # safe_verify should be rust
        self.assertEqual(selections["safe_verify"][0], "rust")

    def test_forced_backend_not_overridden(self):
        """Functions with forced_backend should not be auto-selected."""
        source = """
from pyeffic.backends import rust

@rust
def compute_total(a: int, b: int) -> int:
    return a + b
"""
        units = parse_source(source)
        selections = auto_select_backends(units)
        # compute_total should be forced to rust, not auto-selected
        self.assertEqual(selections["compute_total"][0], "rust")
        self.assertIn("forced", selections["compute_total"][1][0])


class TestKotlinBackend(unittest.TestCase):
    """Test the Kotlin backend emitter and decorator."""

    def test_kotlin_decorator_is_identity(self):
        """The @kotlin decorator should be an identity function at runtime."""
        def foo():
            return 42
        self.assertIs(kotlin(foo), foo)

    def test_kotlin_decorator_parsed(self):
        """The @kotlin decorator should be parsed correctly."""
        source = """
from pyeffic.backends import kotlin

@kotlin
def android_function(x: int) -> int:
    return x
"""
        units = parse_source(source)
        for u in units:
            if u.name == "android_function":
                self.assertEqual(u.forced_backend, "kotlin")
                return
        self.fail("android_function not found")

    def test_kotlin_emitter_produces_code(self):
        """The Kotlin emitter should produce valid Kotlin code."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
"""
        units = parse_source(source)
        prog, emitted = emit_kotlin(units, entry=None)
        self.assertIn("fun add(a: Long, b: Long): Long", prog)
        self.assertIn("return (a + b)", prog)

    def test_kotlin_emitter_library_mode(self):
        """The Kotlin emitter should add @CName in library mode."""
        source = """
def compute(x: int) -> int:
    return x * 2
"""
        units = parse_source(source)
        from pyeffic.ffi import tag_ffi
        tag_ffi(units)
        prog, _ = emit_kotlin(units, entry=None, library_mode=True)
        self.assertIn("@CName", prog)

    def test_kotlin_emitter_handles_loops(self):
        """The Kotlin emitter should handle for loops."""
        source = """
def sum_range(n: int) -> int:
    total: int = 0
    for i in range(0, n):
        total = total + i
    return total
"""
        units = parse_source(source)
        prog, _ = emit_kotlin(units, entry=None)
        self.assertIn("for (i in 0", prog)
        self.assertIn("until n", prog)
        self.assertIn("total", prog)

    def test_kotlin_emitter_handles_conditionals(self):
        """The Kotlin emitter should handle if/else."""
        source = """
def classify(x: int) -> int:
    if x > 0:
        return 1
    return 0
"""
        units = parse_source(source)
        prog, _ = emit_kotlin(units, entry=None)
        self.assertIn("if", prog)
        self.assertIn("x > 0", prog)

    def test_kotlin_emitter_types(self):
        """The Kotlin emitter should map types correctly."""
        source = """
def f(a: int, b: float, c: bool) -> int:
    return a
"""
        units = parse_source(source)
        prog, _ = emit_kotlin(units, entry=None)
        self.assertIn("Long", prog)  # int -> Long
        self.assertIn("Double", prog)  # float -> Double
        self.assertIn("Boolean", prog)  # bool -> Boolean

    def test_kotlin_emitter_main_wrapper(self):
        """The Kotlin emitter should wrap non-main functions in a main()."""
        source = """
def compute(x: int) -> int:
    return x * 2
"""
        units = parse_source(source)
        prog, _ = emit_kotlin(units, entry="compute")
        self.assertIn("fun main()", prog)
        self.assertIn("compute()", prog)


class TestAutoSelectionIntegration(unittest.TestCase):
    """Test auto-selection integration with the build pipeline."""

    def test_auto_select_in_build(self):
        """Test that auto-selection works in the build pipeline (no forced backend)."""
        import tempfile
        from pathlib import Path
        from pyeffic.config import Config
        from pyeffic.pipeline import build

        source = """
def compute_total(a: int, b: int) -> int:
    return a + b

def main() -> None:
    print(compute_total(10, 20))
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(source, encoding="utf-8")
            # no force_backend — auto-select should kick in
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False)
            report = build(src, cfg, entry="main")
            # the program decision should have a backend
            self.assertIsNotNone(report.program_decision)
            # should produce some source file
            self.assertTrue(
                report.rust_src or report.cpp_src or report.csharp_src or
                report.zig_src or report.go_src or report.kotlin_src,
                "should produce at least one backend source file"
            )

    def test_mixed_auto_and_forced_backends(self):
        """Test that forced and auto-selected backends can coexist."""
        source = """
from pyeffic.backends import rust

@rust
def safe_logic(x: int) -> int:
    return x

def fetch_data(url: int) -> int:
    return url

def compute_hash(data: int) -> int:
    return data
"""
        units = parse_source(source)
        selections = auto_select_backends(units)
        # safe_logic is forced to rust
        self.assertEqual(selections["safe_logic"][0], "rust")
        # fetch_data should be auto-selected to go
        self.assertEqual(selections["fetch_data"][0], "go")
        # compute_hash should be auto-selected to cpp or rust
        self.assertIn(selections["compute_hash"][0], ("cpp", "rust"))


if __name__ == "__main__":
    unittest.main()
