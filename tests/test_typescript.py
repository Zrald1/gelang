"""Test the TypeScript → Python transpiler."""
import unittest
from pyeffic.ts2py import transpile


class TestTypeScriptTranspiler(unittest.TestCase):
    def test_simple_function(self):
        ts = "function add(a: number, b: number): number {\n    return a + b;\n}\n"
        py = transpile(ts)
        self.assertIn("def add(a: int, b: int) -> int:", py)
        self.assertIn("return a + b", py)

    def test_let_declaration(self):
        ts = "function f(): number {\n    let x: number = 5;\n    return x;\n}\n"
        py = transpile(ts)
        self.assertIn("x: int = 5", py)

    def test_if_else(self):
        ts = "function f(x: number): number {\n    if (x > 0) {\n        return x;\n    } else {\n        return 0;\n    }\n}\n"
        py = transpile(ts)
        self.assertIn("if x > 0:", py)
        self.assertIn("return 0", py)

    def test_for_loop(self):
        ts = "function f(n: number): number {\n    let total: number = 0;\n    for (let i = 0; i < n; i++) {\n        total = total + i;\n    }\n    return total;\n}\n"
        py = transpile(ts)
        # the frontend lowers C-style for loops to an equivalent while loop,
        # which also covers non-unit steps (i += 2, i = i * 2, ...)
        self.assertIn("i: int = 0", py)
        self.assertIn("while i < n:", py)
        self.assertIn("i = i + 1", py)
        self.assertIn("total = total + i", py)

    def test_array_literal(self):
        ts = "function f(): number {\n    let arr: number[] = [1, 2, 3];\n    return arr[0];\n}\n"
        py = transpile(ts)
        self.assertIn("arr: list = [1, 2, 3]", py)
        self.assertIn("arr[0]", py)

    def test_console_log(self):
        ts = "function f(): void {\n    console.log(\"hello\");\n}\n"
        py = transpile(ts)
        self.assertIn("print(\"hello\")", py)

    def test_type_mapping_number_to_int(self):
        ts = "function f(x: number): number {\n    return x;\n}\n"
        py = transpile(ts)
        self.assertIn("int", py)
        self.assertNotIn("float", py)

    def test_type_mapping_string(self):
        ts = "function f(s: string): string {\n    return s;\n}\n"
        py = transpile(ts)
        self.assertIn("str", py)

    def test_type_mapping_boolean(self):
        ts = "function f(b: boolean): boolean {\n    return b;\n}\n"
        py = transpile(ts)
        self.assertIn("bool", py)

    def test_integer_division(self):
        ts = "function f(a: number, b: number): number {\n    return Math.idiv(a, b);\n}\n"
        py = transpile(ts)
        self.assertIn("//", py)  # floor division operator

    def test_array_length(self):
        ts = "function f(arr: number[]): number {\n    return arr.length;\n}\n"
        py = transpile(ts)
        self.assertIn("len(arr)", py)

    def test_while_loop(self):
        ts = "function f(n: number): number {\n    while (n > 0) {\n        n = n - 1;\n    }\n    return n;\n}\n"
        py = transpile(ts)
        self.assertIn("while n > 0:", py)

    def test_import_statement(self):
        ts = 'import { Text, Column } from "ge/widgets";\nfunction f(): void {}\n'
        py = transpile(ts)
        self.assertIn("from pyeffic.widgets import", py)


if __name__ == "__main__":
    unittest.main()
