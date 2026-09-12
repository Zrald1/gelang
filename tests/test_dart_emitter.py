"""Test the Dart emitter: Python functions → Dart source for @dart backend."""
import unittest
from pyeffic.analyzer import parse_source
from pyeffic.emitters.dart import emit_dart_functions, DartEmitter


class TestDartEmitter(unittest.TestCase):
    def test_simple_function(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def add(a: int, b: int) -> int:
    return a + b
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("int add(int a, int b)", result)
        self.assertIn("return (a + b);", result)

    def test_float_function(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def div(a: float, b: float) -> float:
    return a / b
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("double div(double a, double b)", result)

    def test_for_loop(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f(n: int) -> int:
    total: int = 0
    for i in range(0, n):
        total = total + i
    return total
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("for (int i = 0; i < n; i++)", result)

    def test_if_else(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f(x: int) -> int:
    if x > 0:
        return x
    else:
        return 0
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("if (((x > 0)))", result)
        self.assertIn("return 0;", result)

    def test_floor_division(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f(a: int, b: int) -> int:
    return a // b
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("~/", result)  # Dart integer division

    def test_print(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f() -> None:
    print(42)
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("print(42)", result)

    def test_len_call(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f(vals: list) -> int:
    return len(vals)
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn(".length", result)

    def test_void_function(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f() -> None:
    print(1)
""")
        dart_units = [u for u in units if u.forced_backend == "dart" and u.body is not None]
        result = emit_dart_functions(dart_units)
        self.assertIn("void f()", result)

    def test_no_dart_functions(self):
        result = emit_dart_functions([])
        self.assertIn("AUTO-GENERATED", result)


if __name__ == "__main__":
    unittest.main()
