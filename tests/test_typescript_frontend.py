"""Tests for the TypeScript-flavoured GE frontend.

The frontend lowers a typed TypeScript subset into the shared IR, so every
existing backend works with it unchanged.
"""
import unittest

from pyeffic.frontends import frontend_for, is_ge_source, python_flavour_of
from pyeffic.frontends.typescript import (
    TypeScriptSyntaxError,
    map_type,
    parse_ts_source_full,
    tokenize,
    ts_to_python,
)


class TestFrontendDetection(unittest.TestCase):
    def test_typescript_flavours(self):
        for name in ["app/math.ts.ge.py", "app/math.ge.ts", "x.TS.GE.PY"]:
            self.assertEqual(frontend_for(name), "typescript", name)

    def test_python_flavour(self):
        for name in ["app/math.ge.py", "main.ge.py", "x.py"]:
            self.assertEqual(frontend_for(name), "python", name)

    def test_is_ge_source(self):
        self.assertTrue(is_ge_source("a.ge.py"))
        self.assertTrue(is_ge_source("a.ts.ge.py"))
        self.assertTrue(is_ge_source("a.ge.ts"))
        self.assertFalse(is_ge_source("a.rs"))

    def test_python_flavour_of(self):
        self.assertTrue(python_flavour_of("app/m.ts.ge.py").endswith("m.ge.py"))
        self.assertTrue(python_flavour_of("app/m.ge.ts").endswith("m.ge.py"))
        self.assertTrue(python_flavour_of("app/m.ge.py").endswith("m.ge.py"))


class TestTokenizer(unittest.TestCase):
    def test_operators_longest_first(self):
        toks = tokenize("a === b !== c == d")
        ops = [t.value for t in toks if t.kind == "op"]
        self.assertEqual(ops, ["===", "!==", "=="])

    def test_string_and_template(self):
        toks = tokenize('let a = "x"; let b = `hi ${a}`;')
        kinds = [t.kind for t in toks]
        self.assertIn("string", kinds)
        self.assertIn("template", kinds)

    def test_comments_skipped(self):
        toks = tokenize("// line\n/* block */ let x = 1;")
        idents = [t.value for t in toks if t.kind == "ident"]
        self.assertEqual(idents, ["let", "x"])

    def test_line_numbers(self):
        toks = tokenize("let a = 1;\nlet b = 2;")
        b_tok = next(t for t in toks if t.value == "b")
        self.assertEqual(b_tok.line, 2)


class TestTypeMapping(unittest.TestCase):
    def test_scalars(self):
        self.assertEqual(map_type("number"), "int")
        self.assertEqual(map_type("string"), "str")
        self.assertEqual(map_type("boolean"), "bool")
        self.assertEqual(map_type("void"), "None")

    def test_arrays(self):
        self.assertEqual(map_type("number[]"), "list")
        self.assertEqual(map_type("string[]"), "list")
        self.assertEqual(map_type("Array<number>"), "list")


class TestLowering(unittest.TestCase):
    def test_function_signature(self):
        py = ts_to_python("function f(a: number, b: string): number { return a; }")
        self.assertIn("def f(a: int, b: str) -> int:", py)

    def test_void_return(self):
        py = ts_to_python("function f(): void { }")
        self.assertIn("def f():", py)
        self.assertNotIn("->", py)

    def test_operators(self):
        py = ts_to_python("function f(a: number): boolean { return a === 1 && a !== 2; }")
        self.assertIn("==", py)
        self.assertIn("!=", py)
        self.assertIn("and", py)

    def test_if_else_chain(self):
        py = ts_to_python(
            "function f(x: number): string {"
            "  if (x > 0) { return 'p'; }"
            "  else if (x < 0) { return 'n'; }"
            "  else { return 'z'; }"
            "}")
        self.assertIn("if ", py)
        self.assertIn("elif ", py)
        self.assertIn("else:", py)

    def test_while_loop(self):
        py = ts_to_python("function f(n: number): number { let i: number = 0; while (i < n) { i = i + 1; } return i; }")
        self.assertIn("while ", py)

    def test_for_loop_becomes_while(self):
        py = ts_to_python(
            "function f(n: number): number {"
            "  let t: number = 0;"
            "  for (let i: number = 0; i < n; i = i + 1) { t = t + i; }"
            "  return t;"
            "}")
        self.assertIn("while ", py)
        self.assertIn("i = i + 1", py)

    def test_console_log(self):
        py = ts_to_python("function f(): void { console.log(1); }")
        self.assertIn("print(1)", py)

    def test_math_helpers(self):
        py = ts_to_python("function f(a: number): number { return Math.pow(a, 2); }")
        self.assertIn("pow(a, 2)", py)

    def test_length_becomes_len(self):
        py = ts_to_python("function f(a: number[]): number { return a.length; }")
        self.assertIn("len(a)", py)

    def test_push_becomes_append(self):
        py = ts_to_python("function f(a: number[]): void { a.push(1); }")
        self.assertIn("a.append(1)", py)

    def test_template_literal_becomes_fstring(self):
        py = ts_to_python('function f(n: number): string { return `v=${n}`; }')
        self.assertIn('f"v={n}"', py)

    def test_boolean_literals(self):
        py = ts_to_python("function f(): boolean { return true; }")
        self.assertIn("True", py)

    def test_imports_lowered(self):
        py = ts_to_python('import { a, b } from "./util";')
        self.assertIn("from util import a, b", py)

    def test_export_ignored(self):
        py = ts_to_python("export function f(): number { return 1; }")
        self.assertIn("def f() -> int:", py)
        self.assertNotIn("export", py)

    def test_interface_skipped(self):
        py = ts_to_python("interface P { x: number; }\nfunction f(): number { return 1; }")
        self.assertIn("def f() -> int:", py)
        self.assertNotIn("interface", py)

    def test_intrinsics_mapped(self):
        py = ts_to_python('gePreamble("cpp", "code");')
        self.assertIn("ge_preamble(", py)
        self.assertIn('"cpp"', py)
        self.assertIn('"code"', py)


class TestIR(unittest.TestCase):
    def test_units_and_types(self):
        src = (
            "function add(a: number, b: number): number { return a + b; }\n"
            "function greet(n: string): string { return n; }\n"
        )
        units, _classes = parse_ts_source_full(src)
        names = {u.name for u in units}
        self.assertEqual(names, {"add", "greet"})

        add_u = next(u for u in units if u.name == "add")
        self.assertEqual(add_u.params, [("a", "int"), ("b", "int")])
        self.assertEqual(add_u.ret_type, "int")
        self.assertTrue(add_u.supported)

    def test_preamble_collected(self):
        src = 'gePreamble("rust", "// raw");\nfunction f(): number { return 1; }\n'
        from pyeffic.frontends.typescript import collect_ts_preamble
        pre = collect_ts_preamble(src)
        self.assertIn("rust", pre)
        self.assertIn("// raw", pre["rust"])

    def test_constants_collected(self):
        src = "const LIMIT: number = 10;\nfunction f(): number { return 1; }\n"
        from pyeffic.frontends.typescript import collect_ts_constants
        consts = collect_ts_constants(src)
        self.assertEqual(consts.get("LIMIT"), 10)


class TestErrorReporting(unittest.TestCase):
    def test_unknown_character(self):
        with self.assertRaises(TypeScriptSyntaxError):
            ts_to_python("function f(): number { return 1 @ 2; }")

    def test_unterminated_string(self):
        with self.assertRaises(TypeScriptSyntaxError):
            ts_to_python('let a = "abc')

    def test_missing_brace(self):
        with self.assertRaises(TypeScriptSyntaxError):
            ts_to_python("function f(): number { return 1;")

    def test_error_has_line(self):
        try:
            ts_to_python("function f(): number {\n  return 1 @ 2;\n}")
        except TypeScriptSyntaxError as exc:
            self.assertEqual(exc.line, 2)
        else:
            self.fail("expected TypeScriptSyntaxError")


class TestModuleResolution(unittest.TestCase):
    def test_find_module_prefers_python_flavour(self):
        import tempfile
        from pathlib import Path
        from pyeffic.modules import _find_module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "m.ge.py").write_text("def f() -> int:\n    return 1\n")
            (root / "app" / "m.ts.ge.py").write_text("function g(): number { return 2; }\n")
            found = _find_module("app.m", root)
            self.assertIsNotNone(found)
            self.assertTrue(str(found).endswith("m.ge.py"))

    def test_find_module_falls_back_to_typescript(self):
        import tempfile
        from pathlib import Path
        from pyeffic.modules import _find_module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "t.ts.ge.py").write_text("function g(): number { return 2; }\n")
            found = _find_module("app.t", root)
            self.assertIsNotNone(found)
            self.assertTrue(str(found).endswith("t.ts.ge.py"))

    def test_resolve_imports_transitive(self):
        import tempfile
        from pathlib import Path
        from pyeffic.modules import resolve_imports

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "leaf.ts.ge.py").write_text(
                "export function leaf(x: number): number { return x + 1; }\n")
            (root / "app" / "mid.ts.ge.py").write_text(
                'import { leaf } from "./leaf";\n'
                "export function mid(x: number): number { return leaf(x); }\n")
            (root / "main.ts.ge.py").write_text(
                'import { mid } from "./app/mid";\n'
                "function main(): number { return mid(1); }\n")

            source = (root / "main.ts.ge.py").read_text()
            units, _classes, warnings = resolve_imports(source, root / "main.ts.ge.py")
            names = {u.name for u in units}
            self.assertIn("mid", names, "transitive import 'mid' missing")
            self.assertIn("leaf", names, "transitive import 'leaf' missing")


if __name__ == "__main__":
    unittest.main()
