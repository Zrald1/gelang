"""Test the FFI module: function tagging and type mapping."""
import unittest
from pyeffic.analyzer import parse_source
from pyeffic.ffi import tag_ffi, dart_name, DART_FFI_TYPE, DART_NATIVE_TYPE


class TestFFI(unittest.TestCase):
    def test_tag_ffi_scalar_functions(self):
        units = parse_source("""
def compute() -> int:
    return 42
def helper(vals: list) -> int:
    return vals[0]
""")
        tag_ffi(units)
        # compute() has all scalar params -> FFI export
        compute = next(u for u in units if u.name == "compute")
        self.assertTrue(compute.ffi_export)
        # helper(vals: list) has list param -> not FFI export
        helper = next(u for u in units if u.name == "helper")
        self.assertFalse(helper.ffi_export)

    def test_tag_ffi_with_scalar_params(self):
        units = parse_source("def compute(x: int, y: int) -> int:\n    return x + y\n")
        tag_ffi(units)
        self.assertTrue(units[0].ffi_export)

    def test_tag_ffi_void_return(self):
        units = parse_source("def do_something() -> None:\n    print(42)\n")
        tag_ffi(units)
        self.assertTrue(units[0].ffi_export)

    def test_dart_name_conversion(self):
        # dart_name converts snake_case to camelCase
        self.assertEqual(dart_name("compute_total"), "computeTotal")
        self.assertEqual(dart_name("simple"), "simple")

    def test_dart_ffi_type_mapping(self):
        self.assertEqual(DART_FFI_TYPE["int"], "Int64")
        self.assertEqual(DART_FFI_TYPE["float"], "Double")
        self.assertEqual(DART_FFI_TYPE["bool"], "Bool")
        self.assertEqual(DART_FFI_TYPE["None"], "Void")

    def test_dart_native_type_mapping(self):
        self.assertEqual(DART_NATIVE_TYPE["int"], "int")
        self.assertEqual(DART_NATIVE_TYPE["float"], "double")
        self.assertEqual(DART_NATIVE_TYPE["bool"], "bool")
        self.assertEqual(DART_NATIVE_TYPE["None"], "void")


if __name__ == "__main__":
    unittest.main()
