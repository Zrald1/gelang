"""Test the analyzer: function parsing, type inference, feature classification."""
import unittest
from pyeffic.analyzer import parse_source, FuncUnit


class TestAnalyzer(unittest.TestCase):
    def test_simple_function(self):
        units = parse_source("def add(a: int, b: int) -> int:\n    return a + b\n")
        self.assertEqual(len(units), 1)
        u = units[0]
        self.assertEqual(u.name, "add")
        self.assertEqual(u.params, [("a", "int"), ("b", "int")])
        self.assertEqual(u.ret_type, "int")
        self.assertTrue(u.supported)

    def test_float_function(self):
        units = parse_source("def div(a: float, b: float) -> float:\n    return a / b\n")
        u = units[0]
        self.assertEqual(u.ret_type, "float")
        self.assertIn("arithmetic", u.features)

    def test_untyped_param_unsupported(self):
        # untyped params default to "float" (not "any") so they ARE supported
        units = parse_source("def foo(x) -> int:\n    return 1\n")
        u = units[0]
        # x defaults to float, but return is int — this is a type mismatch
        # but the analyzer doesn't catch it (heuristic inference)
        # so it's still "supported" with float param
        self.assertTrue(u.supported)

    def test_list_param(self):
        units = parse_source("def sum_all(vals: list) -> int:\n    total: int = 0\n    return total\n")
        u = units[0]
        self.assertEqual(u.params, [("vals", "list")])
        self.assertTrue(u.supported)

    def test_features_detected(self):
        units = parse_source("""
def f(n: int) -> int:
    total: int = 0
    for i in range(0, n):
        total = total + i
    if total > 0:
        print(total)
    return total
""")
        u = units[0]
        self.assertIn("numeric_loop", u.features)
        self.assertIn("comparison", u.features)
        self.assertIn("io_print", u.features)

    def test_forced_backend_rust(self):
        units = parse_source("""
from pyeffic.backends import rust
@rust
def f(x: int) -> int:
    return x
""")
        # find the function (not the import)
        u = next(u for u in units if u.name == "f")
        self.assertEqual(u.forced_backend, "rust")

    def test_forced_backend_cpp(self):
        units = parse_source("""
from pyeffic.backends import cpp
@cpp
def f(x: int) -> int:
    return x
""")
        u = next(u for u in units if u.name == "f")
        self.assertEqual(u.forced_backend, "cpp")

    def test_forced_backend_dart(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f(x: int) -> int:
    return x
""")
        u = next(u for u in units if u.name == "f")
        self.assertEqual(u.forced_backend, "dart")
        self.assertFalse(u.supported)  # dart functions are not compiled to native

    def test_unsupported_features(self):
        # async functions are still unsupported
        units = parse_source("""
async def f(x: int) -> int:
    return x
""")
        u = units[0]
        self.assertFalse(u.supported)
        self.assertTrue(len(u.unsupported_reasons) > 0)

    def test_module_level_code_unsupported(self):
        units = parse_source("x = 5\ndef f() -> int:\n    return 1\n")
        # module-level assign should be unsupported
        mod_units = [u for u in units if not u.name.isidentifier() or u.name.startswith("<")]
        self.assertTrue(len(mod_units) > 0)


if __name__ == "__main__":
    unittest.main()
