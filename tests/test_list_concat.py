"""Regression tests for list concatenation (list + list) and module-level constants.

These verify the GE compiler fixes for:
- Rust/C++/Kotlin/Go/C#/Zig emitting valid code for `list + list` expressions.
- Module-level constants being inlined into native code instead of unresolved.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from pyeffic.analyzer import collect_constants, parse_source_full
from pyeffic.emitters.rust import emit_rust, SPEC as RUST_SPEC
from pyeffic.emitters.cpp import emit_cpp, SPEC as CPP_SPEC
from pyeffic.emitters.kotlin import emit_kotlin, SPEC as KOTLIN_SPEC
from pyeffic.emitters.go import emit_go, SPEC as GO_SPEC
from pyeffic.emitters.csharp import emit_csharp, SPEC as CSHARP_SPEC
from pyeffic.emitters.zig import emit_zig, SPEC as ZIG_SPEC


LIST_CONCAT_SOURCE = """\
NODE_SIZE: int = 5
EDGE_SIZE: int = 2

def concat_lists(a: list, b: list) -> list:
    return a + b

def build_node(nid: int, ntype: int, x: int, y: int) -> list:
    return [nid, ntype, x, y, 0]

def append_node(graph: list, nid: int, ntype: int, x: int, y: int) -> list:
    node: list = build_node(nid, ntype, x, y)
    return graph + node

def main() -> int:
    g: list = [1, 2, 3]
    g = g + [4, 5, 6]
    print(g[0])
    print(g[3])
    n: list = build_node(10, 1, 5, 5)
    print(n[0])
    g2 = append_node(g, 20, 2, 10, 10)
    print(g2[6])
    return 0
"""


def _supported_units(source: str):
    units, classes = parse_source_full(source)
    supported = [u for u in units if u.supported and u.body is not None]
    return supported, classes


class TestCollectConstants(unittest.TestCase):
    def test_collects_annotated_constants(self) -> None:
        constants = collect_constants(LIST_CONCAT_SOURCE)
        self.assertEqual(constants["NODE_SIZE"], 5)
        self.assertEqual(constants["EDGE_SIZE"], 2)

    def test_collects_plain_assignment(self) -> None:
        src = "X = 42\nY: int = 10\n"
        constants = collect_constants(src)
        self.assertEqual(constants["X"], 42)
        self.assertEqual(constants["Y"], 10)

    def test_ignores_non_constant(self) -> None:
        src = "X = 42\nY = some_func()\n"
        constants = collect_constants(src)
        self.assertEqual(constants, {"X": 42})


class TestListConcatRust(unittest.TestCase):
    def test_rust_emits_valid_list_concat(self) -> None:
        units, classes = _supported_units(LIST_CONCAT_SOURCE)
        constants = collect_constants(LIST_CONCAT_SOURCE)
        prog, _ = emit_rust(units, entry="main", classes=classes, constants=constants)
        # Must not contain Vec + Vec (invalid Rust)
        self.assertNotIn("Vec<i64> + Vec<i64>", prog)
        # Must contain a valid extend/concat strategy
        self.assertIn("extend", prog)

    def test_rust_inlines_constants(self) -> None:
        src = """\
SIZE: int = 5
def get_size() -> int:
    return SIZE
def main() -> int:
    print(get_size())
    return 0
"""
        units, classes = _supported_units(src)
        constants = collect_constants(src)
        prog, _ = emit_rust(units, entry="main", classes=classes, constants=constants)
        # The constant SIZE should be inlined as 5, not left as an unresolved name
        self.assertIn("5", prog)
        # No bare unresolved `SIZE` reference in function bodies
        self.assertNotIn("return SIZE", prog)


class TestListConcatCpp(unittest.TestCase):
    def test_cpp_emits_valid_list_concat(self) -> None:
        units, classes = _supported_units(LIST_CONCAT_SOURCE)
        constants = collect_constants(LIST_CONCAT_SOURCE)
        prog, _ = emit_cpp(units, entry="main", classes=classes, constants=constants)
        # Must use insert/extend strategy
        self.assertIn("insert", prog)


class TestListConcatKotlin(unittest.TestCase):
    def test_kotlin_emits_valid_list_concat(self) -> None:
        units, classes = _supported_units(LIST_CONCAT_SOURCE)
        constants = collect_constants(LIST_CONCAT_SOURCE)
        prog, _ = emit_kotlin(units, entry="main", classes=classes, constants=constants)
        # Should use addAll strategy
        self.assertIn("addAll", prog)


class TestListConcatGo(unittest.TestCase):
    def test_go_emits_valid_list_concat(self) -> None:
        units, classes = _supported_units(LIST_CONCAT_SOURCE)
        constants = collect_constants(LIST_CONCAT_SOURCE)
        prog, _ = emit_go(units, entry="main", classes=classes, constants=constants)
        # Go uses append(a, b...) for slice concatenation
        self.assertIn("append", prog)


class TestListConcatCSharp(unittest.TestCase):
    def test_csharp_emits_valid_list_concat(self) -> None:
        units, classes = _supported_units(LIST_CONCAT_SOURCE)
        constants = collect_constants(LIST_CONCAT_SOURCE)
        prog, _ = emit_csharp(units, entry="main", classes=classes, constants=constants)
        # C# uses Concat().ToList() for list concatenation
        self.assertIn("Concat", prog)


class TestListConcatZig(unittest.TestCase):
    def test_zig_emits_valid_list_concat(self) -> None:
        units, classes = _supported_units(LIST_CONCAT_SOURCE)
        constants = collect_constants(LIST_CONCAT_SOURCE)
        prog, _ = emit_zig(units, entry="main", classes=classes, constants=constants)
        # Zig uses appendSlice for slice concatenation
        self.assertIn("appendSlice", prog)


class TestInferTypeListConcat(unittest.TestCase):
    def test_list_plus_list_infers_list(self) -> None:
        from pyeffic.emitters.base import Emitter
        emitter = Emitter(RUST_SPEC)
        # a + b where both are lists
        node = ast.parse("a + b", mode="eval").body
        emitter.var_types["a"] = "list"
        emitter.var_types["b"] = "list"
        result = emitter.infer_type(node)
        self.assertEqual(result, "list")

    def test_str_plus_str_infers_str(self) -> None:
        from pyeffic.emitters.base import Emitter
        emitter = Emitter(RUST_SPEC)
        node = ast.parse("a + b", mode="eval").body
        emitter.var_types["a"] = "str"
        emitter.var_types["b"] = "str"
        result = emitter.infer_type(node)
        self.assertEqual(result, "str")


if __name__ == "__main__":
    unittest.main()

