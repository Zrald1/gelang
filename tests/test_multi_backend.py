"""Test multi-backend: @rust/@cpp/@dart decorator handling in the analyzer."""
import unittest
from pyeffic.analyzer import parse_source


class TestMultiBackend(unittest.TestCase):
    def test_rust_decorator(self):
        units = parse_source("""
from pyeffic.backends import rust
@rust
def f(x: int) -> int:
    return x
""")
        u = next(u for u in units if u.name == "f")
        self.assertEqual(u.forced_backend, "rust")
        self.assertTrue(u.supported)

    def test_cpp_decorator(self):
        units = parse_source("""
from pyeffic.backends import cpp
@cpp
def f(x: int) -> int:
    return x
""")
        u = next(u for u in units if u.name == "f")
        self.assertEqual(u.forced_backend, "cpp")
        self.assertTrue(u.supported)

    def test_dart_decorator(self):
        units = parse_source("""
from pyeffic.backends import dart
@dart
def f(x: int) -> int:
    return x
""")
        u = next(u for u in units if u.name == "f")
        self.assertEqual(u.forced_backend, "dart")
        self.assertFalse(u.supported)  # dart functions are not compiled to native

    def test_mixed_decorators(self):
        units = parse_source("""
from pyeffic.backends import rust, cpp, dart
@rust
def rust_fn(x: int) -> int:
    return x
@cpp
def cpp_fn(x: int) -> int:
    return x
@dart
def dart_fn(x: int) -> int:
    return x
""")
        rust_u = next(u for u in units if u.name == "rust_fn")
        cpp_u = next(u for u in units if u.name == "cpp_fn")
        dart_u = next(u for u in units if u.name == "dart_fn")
        self.assertEqual(rust_u.forced_backend, "rust")
        self.assertEqual(cpp_u.forced_backend, "cpp")
        self.assertEqual(dart_u.forced_backend, "dart")
        self.assertTrue(rust_u.supported)
        self.assertTrue(cpp_u.supported)
        self.assertFalse(dart_u.supported)

    def test_no_decorator_uses_default(self):
        units = parse_source("def f(x: int) -> int:\n    return x\n")
        u = units[0]
        self.assertIsNone(u.forced_backend)
        self.assertTrue(u.supported)

    def test_backends_module_imports(self):
        """Verify that the backends module exports the decorators."""
        from pyeffic.backends import rust, cpp, dart
        self.assertTrue(callable(rust))
        self.assertTrue(callable(cpp))
        self.assertTrue(callable(dart))
        # decorators should be identity functions at Python runtime
        def foo():
            return 42
        self.assertIs(rust(foo), foo)
        self.assertIs(cpp(foo), foo)
        self.assertIs(dart(foo), foo)


if __name__ == "__main__":
    unittest.main()
