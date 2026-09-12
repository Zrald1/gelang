"""Test the Rust and C++ emitters: Python AST → native code generation."""
import unittest
from pyeffic.analyzer import parse_source
from pyeffic.emitters import emit_rust, emit_cpp


class TestRustEmitter(unittest.TestCase):
    def test_simple_function(self):
        units = parse_source("def add(a: int, b: int) -> int:\n    return a + b\n")
        prog, emitted = emit_rust(units, entry=None)
        self.assertIn("fn add(a: i64, b: i64) -> i64", prog)
        self.assertIn("return (a + b);", prog)

    def test_float_function(self):
        units = parse_source("def div(a: float, b: float) -> float:\n    return a / b\n")
        prog, _ = emit_rust(units, entry=None)
        self.assertIn("f64", prog)

    def test_for_loop(self):
        units = parse_source("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        total = total + i\n    return total\n")
        prog, _ = emit_rust(units, entry=None)
        self.assertIn("for i in (0..n)", prog)

    def test_if_else(self):
        units = parse_source("def f(x: int) -> int:\n    if x > 0:\n        return x\n    else:\n        return 0\n")
        prog, _ = emit_rust(units, entry=None)
        self.assertIn("if ((x > 0))", prog)
        self.assertIn("return 0;", prog)

    def test_list_param(self):
        units = parse_source("def f(vals: list) -> int:\n    return vals[0]\n")
        prog, _ = emit_rust(units, entry=None)
        self.assertIn("&[i64]", prog)

    def test_library_mode(self):
        units = parse_source("def f(x: int) -> int:\n    return x\n")
        # mark as FFI export for library mode
        from pyeffic.ffi import tag_ffi
        tag_ffi(units)
        prog, _ = emit_rust(units, entry=None, library_mode=True)
        self.assertIn("extern \"C\"", prog)

    def test_print(self):
        units = parse_source("def f() -> None:\n    print(42)\n")
        prog, _ = emit_rust(units, entry=None)
        self.assertIn('println!("{}", 42)', prog)

    def test_len_call(self):
        units = parse_source("def f(vals: list) -> int:\n    return len(vals)\n")
        prog, _ = emit_rust(units, entry=None)
        self.assertIn(".len() as i64", prog)


class TestCppEmitter(unittest.TestCase):
    def test_simple_function(self):
        units = parse_source("def add(a: int, b: int) -> int:\n    return a + b\n")
        prog, emitted = emit_cpp(units, entry=None)
        self.assertIn("int64_t add(int64_t a, int64_t b)", prog)
        self.assertIn("return (a + b);", prog)

    def test_float_function(self):
        units = parse_source("def div(a: float, b: float) -> float:\n    return a / b\n")
        prog, _ = emit_cpp(units, entry=None)
        self.assertIn("double", prog)

    def test_for_loop(self):
        units = parse_source("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        total = total + i\n    return total\n")
        prog, _ = emit_cpp(units, entry=None)
        self.assertIn("for (int64_t i = 0; i < n; ++i)", prog)

    def test_includes(self):
        units = parse_source("def f() -> int:\n    return 0\n")
        prog, _ = emit_cpp(units, entry=None)
        self.assertIn("#include <cstdint>", prog)
        self.assertIn("#include <vector>", prog)

    def test_library_mode(self):
        units = parse_source("def f(x: int) -> int:\n    return x\n")
        # mark as FFI export for library mode
        from pyeffic.ffi import tag_ffi
        tag_ffi(units)
        prog, _ = emit_cpp(units, entry=None, library_mode=True)
        self.assertIn('extern "C"', prog)


if __name__ == "__main__":
    unittest.main()
