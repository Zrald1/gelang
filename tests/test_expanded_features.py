"""Tests for expanded Python subset support: built-ins, statements, OOP, inline escape hatch."""
import unittest
from pyeffic.analyzer import parse_source, parse_source_full
from pyeffic.emitters import (emit_rust, emit_cpp, emit_csharp,
                               emit_zig, emit_go, emit_kotlin)


# ---- Built-in functions ----

BUILTINS_SOURCE = """
def test_any(vals: list) -> bool:
    return any(vals)

def test_all(vals: list) -> bool:
    return all(vals)

def test_divmod(a: int, b: int) -> int:
    q, r = divmod(a, b)
    return q + r

def test_bin(n: int) -> str:
    return bin(n)

def test_hex(n: int) -> str:
    return hex(n)

def test_oct(n: int) -> str:
    return oct(n)

def test_chr(n: int) -> str:
    return chr(n)

def test_ord(s: str) -> int:
    return ord(s)

def test_isinstance(x: int) -> bool:
    return isinstance(x, int)

def test_repr_int(n: int) -> str:
    return repr(n)

def test_repr_str(s: str) -> str:
    return repr(s)

def test_hash(n: int) -> int:
    return hash(n)

def test_map(vals: list) -> list:
    return map(abs, vals)

def test_filter(vals: list) -> list:
    return filter(abs, vals)

def test_enumerate_list(vals: list) -> list:
    return enumerate(vals)

def test_zip_list(a: list, b: list) -> list:
    return zip(a, b)

def test_range_list(n: int) -> list:
    return range(0, n)
"""


class TestBuiltins(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(BUILTINS_SOURCE)

    def test_any_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".any(", prog)

    def test_any_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("any_of", prog)

    def test_any_csharp(self):
        prog, _ = emit_csharp(self.units, entry=None)
        self.assertIn(".Any(", prog)

    def test_all_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".all(", prog)

    def test_all_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("all_of", prog)

    def test_divmod_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        # divmod lowered to division and modulo
        idx = prog.find("test_divmod")
        self.assertTrue(idx >= 0)

    def test_bin_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("format!", prog)

    def test_hex_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("format!", prog)

    def test_chr_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("from_u32", prog)

    def test_chr_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("std::string(1", prog)

    def test_ord_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("as_bytes", prog)

    def test_isinstance(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            # isinstance(x, int) with x typed as int -> true
            self.assertIn("true", prog)

    def test_map_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".map(", prog)

    def test_filter_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".filter(", prog)

    def test_enumerate_list_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("enumerate", prog.lower())

    def test_zip_list_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("zip", prog)

    def test_range_as_value_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("collect", prog)

    def test_hash_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("hash", prog.lower())

    def test_all_backends_emit(self):
        """All 6 backends should emit without errors for builtins."""
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)


# ---- For-loop with enumerate/zip ----

FOR_LOOP_SOURCE = """
def test_enumerate_for(vals: list) -> None:
    for i, x in enumerate(vals):
        print(i)
        print(x)

def test_zip_for(a: list, b: list) -> None:
    for x, y in zip(a, b):
        print(x)
        print(y)
"""


class TestForLoops(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(FOR_LOOP_SOURCE)

    def test_enumerate_for_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".enumerate()", prog)

    def test_enumerate_for_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        # C++ uses index-based loop for enumerate
        self.assertIn("int64_t", prog)

    def test_enumerate_for_go(self):
        prog, _ = emit_go(self.units, entry=None)
        # Go: for i, v := range vals
        self.assertIn("range", prog)

    def test_zip_for_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".zip(", prog)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)


# ---- Missing statements ----

STATEMENTS_SOURCE = """
def test_del(vals: list) -> None:
    del vals[0]

def test_raise(x: int) -> int:
    if x < 0:
        raise ValueError('negative')
    return x

def test_assert(x: int) -> None:
    assert x > 0

def test_ternary(x: int) -> int:
    return 1 if x > 0 else 0

def test_tuple_unpack() -> int:
    a: int = 0
    b: int = 0
    a, b = 1, 2
    return a + b
"""


class TestStatements(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(STATEMENTS_SOURCE)

    def test_del_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("remove", prog)

    def test_del_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("erase", prog)

    def test_del_csharp(self):
        prog, _ = emit_csharp(self.units, entry=None)
        self.assertIn("RemoveAt", prog)

    def test_raise_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("panic!", prog)

    def test_raise_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("throw", prog)

    def test_assert_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("assert!", prog)

    def test_ternary_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("if", prog)

    def test_ternary_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("?", prog)

    def test_tuple_unpack_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        # a, b = 1, 2 -> let mut a = 1; let mut b = 2;
        self.assertIn("let mut", prog)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)


# ---- Set/dict comprehensions ----

COMP_SOURCE = """
def test_set_comp(n: int) -> int:
    s = {x for x in range(0, n)}
    return 0

def test_dict_comp(n: int) -> int:
    d = {x: x * 2 for x in range(0, n)}
    return 0
"""


class TestComprehensions(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(COMP_SOURCE)

    def test_set_comp_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("HashSet", prog)

    def test_set_comp_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("set<int64_t>", prog)

    def test_dict_comp_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("HashMap", prog)

    def test_dict_comp_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("map<int64_t", prog)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)


# ---- OOP features ----

OOP_SOURCE = """
class Animal:
    name: str
    age: int

    def __init__(self, name: str, age: int):
        pass

    def speak(self) -> str:
        return 'generic'

class Dog(Animal):
    breed: str

    def __init__(self, name: str, age: int, breed: str):
        pass

    def speak(self) -> str:
        return 'woof'

    @property
    def info(self) -> str:
        return 'dog'

    @staticmethod
    def create(name: str) -> Dog:
        return Dog(name, 0, 'unknown')
"""


class TestOOP(unittest.TestCase):
    def setUp(self):
        self.units, self.classes = parse_source_full(OOP_SOURCE)

    def test_class_parsed(self):
        self.assertEqual(len(self.classes), 2)
        self.assertEqual(self.classes[0].name, "Animal")
        self.assertEqual(self.classes[1].name, "Dog")

    def test_inheritance_parsed(self):
        self.assertIn("Animal", self.classes[1].bases)

    def test_property_parsed(self):
        self.assertIn("info", self.classes[1].properties)

    def test_static_method_parsed(self):
        self.assertIn("create", self.classes[1].static_methods)

    def test_methods_emitted_rust(self):
        prog, _ = emit_rust(self.units, entry=None, classes=self.classes)
        self.assertIn("Animal_speak", prog)
        self.assertIn("Dog_speak", prog)

    def test_struct_emitted_rust(self):
        prog, _ = emit_rust(self.units, entry=None, classes=self.classes)
        self.assertIn("struct Animal", prog)
        self.assertIn("struct Dog", prog)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None, classes=self.classes)
            self.assertTrue(len(prog) > 0)


# ---- Inline escape hatch ----

INLINE_SOURCE = """
def test_inline_rust() -> int:
    return ge_inline('rust', '42')

def test_inline_cpp() -> int:
    return ge_inline('cpp', '42')

def test_raw() -> int:
    return ge_raw('42')
"""


class TestInlineEscape(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(INLINE_SOURCE)

    def test_inline_rust_emits_code(self):
        prog, _ = emit_rust(self.units, entry=None)
        # When targeting Rust, ge_inline('rust', '42') should emit '42'
        self.assertIn("42", prog)

    def test_inline_cpp_skips_rust(self):
        prog, _ = emit_cpp(self.units, entry=None)
        # When targeting C++, ge_inline('rust', ...) should be skipped
        self.assertIn("skipped", prog)

    def test_inline_cpp_emits_code(self):
        prog, _ = emit_cpp(self.units, entry=None)
        # When targeting C++, ge_inline('cpp', '42') should emit '42'
        self.assertIn("42", prog)

    def test_raw_emits_all(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertIn("42", prog)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)


# ---- Match statement ----

MATCH_SOURCE = """
def test_match(x: int) -> int:
    match x:
        case 1:
            return 10
        case 2:
            return 20
        case _:
            return 0
"""


class TestMatch(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(MATCH_SOURCE)

    def test_match_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        # match lowered to if-else chains
        self.assertIn("if", prog)

    def test_match_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        self.assertIn("if", prog)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)


# ---- Combined: all features in one source ----

COMBINED_SOURCE = """
def compute_stats(vals: list) -> int:
    total: int = 0
    for i, x in enumerate(vals):
        total = total + x
        if x > 10:
            total = total + 1
        else:
            total = total - 1
    has_any = any(vals)
    has_all = all(vals)
    result = total if has_any else 0
    assert result >= 0
    return result

def process_pairs(a: list, b: list) -> None:
    for x, y in zip(a, b):
        print(x + y)

def transform(vals: list) -> list:
    return map(abs, vals)
"""


class TestCombined(unittest.TestCase):
    def setUp(self):
        self.units = parse_source(COMBINED_SOURCE)

    def test_all_backends_emit(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)
            # Should not have "unsupported" comments for our features
            self.assertNotIn("unsupported stmt", prog)

    def test_enumerate_in_combined_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("enumerate", prog.lower())

    def test_zip_in_combined_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn("zip", prog)

    def test_map_in_combined_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        self.assertIn(".map(", prog)


# ---- Production-grade feature tests ----

HETEROGENEOUS_SOURCE = """
def greet(names: list[str]) -> int:
    return len(names)

def average(vals: list[float]) -> float:
    total: float = 0.0
    for x in vals:
        total = total + x
    return total
"""

CLASS_TYPED_SOURCE = """
class Point:
    x: int
    y: int

def use(p: Point) -> int:
    return p.x
"""

SILENT_FAILURE_SOURCE = """
def slice_test(vals: list) -> int:
    x = vals[0:3]
    return len(x)
"""


class TestHeterogeneousContainers(unittest.TestCase):
    """Production: list[str], list[float] should use correct element types."""

    def setUp(self):
        self.units = parse_source(HETEROGENEOUS_SOURCE)

    def test_list_str_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        # list[str] should use String element type, not i64
        self.assertIn("String", prog)
        self.assertIn("&[String]", prog)

    def test_list_str_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None)
        # list[str] should use std::string element type
        self.assertIn("std::string", prog)
        self.assertIn("std::vector<std::string>", prog)

    def test_list_float_rust(self):
        prog, _ = emit_rust(self.units, entry=None)
        # list[float] should use f64 element type
        self.assertIn("&[f64]", prog)

    def test_elem_types_tracked(self):
        # The analyzer should track element types
        u0 = self.units[0]  # greet
        u1 = self.units[1]  # average
        self.assertEqual(u0.param_elem_types.get("names"), "str")
        self.assertEqual(u1.param_elem_types.get("vals"), "float")


class TestClassTypedParams(unittest.TestCase):
    """Production: class-typed parameters should not be marked unsupported."""

    def setUp(self):
        self.units, self.classes = parse_source_full(CLASS_TYPED_SOURCE)

    def test_class_param_supported(self):
        u = self.units[0]
        self.assertTrue(u.supported, f"Function should be supported, reasons: {u.unsupported_reasons}")
        # Parameter should be typed as Point, not 'any'
        self.assertEqual(u.params[0][1], "Point")

    def test_class_param_rust(self):
        prog, _ = emit_rust(self.units, entry=None, classes=self.classes)
        # Should emit fn use(p: Point) -> i64
        self.assertIn("Point", prog)
        self.assertIn("p.x", prog)

    def test_class_param_cpp(self):
        prog, _ = emit_cpp(self.units, entry=None, classes=self.classes)
        # Should emit int64_t use(const Point& p)
        self.assertIn("Point", prog)


class TestSilentFailureDetection(unittest.TestCase):
    """Production: unsupported features must be tracked, not silently emitted."""

    def setUp(self):
        self.units = parse_source(SILENT_FAILURE_SOURCE)

    def test_slice_marked_unsupported(self):
        # List slicing is not fully supported — the function should be marked unsupported
        prog, _ = emit_rust(self.units, entry=None)
        # The function should have been marked unsupported during emission
        u = self.units[0]
        self.assertFalse(u.supported, "List slicing should mark function as unsupported")
        self.assertTrue(len(u.unsupported_reasons) > 0, "Should have unsupported reasons")


class TestProductionGradeBackends(unittest.TestCase):
    """Production: all backends should emit valid code for supported features."""

    PRODUCTION_SOURCE = """
def compute(a: int, b: int) -> int:
    return a + b * 2

def loop_sum(n: int) -> int:
    total: int = 0
    for i in range(n):
        total = total + i
    return total

def conditional(x: int) -> int:
    if x > 0:
        return x
    else:
        return -x
"""

    def setUp(self):
        self.units = parse_source(self.PRODUCTION_SOURCE)

    def test_all_backends_emit_without_unsupported(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertTrue(len(prog) > 0)
            # No unsupported emissions for these basic features
            self.assertNotIn("unsupported", prog.lower(), f"{emit_fn.__name__} emitted unsupported code")

    def test_all_backends_preserve_function_names(self):
        for emit_fn in [emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go, emit_kotlin]:
            prog, _ = emit_fn(self.units, entry=None)
            self.assertIn("compute", prog, f"{emit_fn.__name__} missing compute function")
            self.assertIn("loop_sum", prog, f"{emit_fn.__name__} missing loop_sum function")
            self.assertIn("conditional", prog, f"{emit_fn.__name__} missing conditional function")


if __name__ == "__main__":
    unittest.main()
