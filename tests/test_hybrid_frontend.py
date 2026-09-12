"""Tests for the hybrid `.ge` frontend.

A single `.ge` file may mix Python-flavoured and TypeScript-flavoured
definitions. The frontend classifies each top-level chunk and lowers it, so
one file compiles to every backend.
"""
import tempfile
import unittest
from pathlib import Path

from pyeffic.frontends import (
    ALL_SUFFIXES,
    HYBRID_SUFFIXES,
    frontend_for,
    is_ge_source,
    python_flavour_of,
)
from pyeffic.frontends.hybrid import (
    chunk_flavours,
    hybrid_to_python,
    split_chunks,
)
from pyeffic.modules import _find_module, resolve_imports

MIXED = '''"""Mixed module."""
from __future__ import annotations
from pyeffic.backends import cpp, rust


def double(x: int) -> int:
    return x * 2


export function triple(x: number): number {
    return x * 3;
}

const LIMIT: number = 12;

@rust
def clamp(v: int) -> int:
    if v > LIMIT:
        return LIMIT
    return v


@cpp
export function render(v: number): number {
    return double(v) + triple(v);
}


def main() -> int:
    print(render(10))
    return 0
'''


class TestExtensionRouting(unittest.TestCase):
    def test_ge_is_hybrid(self):
        self.assertEqual(frontend_for("main.ge"), "hybrid")
        self.assertEqual(frontend_for("app/math.ge"), "hybrid")

    def test_single_flavour_still_routed(self):
        self.assertEqual(frontend_for("m.ge.py"), "python")
        self.assertEqual(frontend_for("m.ge.ts"), "typescript")

    def test_ge_not_confused_with_ge_py(self):
        # `.ge` must not swallow `.ge.py`
        self.assertEqual(frontend_for("m.ge.py"), "python")
        self.assertEqual(frontend_for("m.ge.ts"), "typescript")

    def test_is_ge_source(self):
        for name in ("a.ge", "a.ge.py", "a.ge.ts"):
            self.assertTrue(is_ge_source(name), name)
        self.assertFalse(is_ge_source("a.py"))
        self.assertFalse(is_ge_source("a.rs"))

    def test_python_flavour_of(self):
        self.assertTrue(python_flavour_of("app/m.ge").endswith("m.ge.py"))
        self.assertTrue(python_flavour_of("app/m.ge.ts").endswith("m.ge.py"))

    def test_canonical_extension_is_ge(self):
        self.assertEqual(HYBRID_SUFFIXES, (".ge",))
        self.assertIn(".ge", ALL_SUFFIXES)


class TestChunkSplitting(unittest.TestCase):
    def test_flavours_detected(self):
        chunks = split_chunks(MIXED)
        by_flavour: dict[str, int] = {}
        for c in chunks:
            by_flavour[c.flavour] = by_flavour.get(c.flavour, 0) + 1
        self.assertGreater(by_flavour.get("python", 0), 0)
        self.assertGreater(by_flavour.get("typescript", 0), 0)

    def test_python_function_is_one_chunk(self):
        chunks = split_chunks(MIXED)
        double = next(c for c in chunks if "def double" in c.text)
        self.assertEqual(double.flavour, "python")
        self.assertIn("return x * 2", double.text)
        # the next function must not leak into this chunk
        self.assertNotIn("def triple", double.text)

    def test_typescript_function_is_one_chunk(self):
        chunks = split_chunks(MIXED)
        triple = next(c for c in chunks if "function triple" in c.text)
        self.assertEqual(triple.flavour, "typescript")
        self.assertIn("return x * 3;", triple.text)
        self.assertNotIn("const LIMIT", triple.text)

    def test_const_chunk_is_typescript(self):
        chunks = split_chunks(MIXED)
        lim = next(c for c in chunks if "LIMIT" in c.text)
        self.assertEqual(lim.flavour, "typescript")

    def test_imports_split_by_flavour(self):
        src = (
            "from app.core import add\n"
            'import { helper } from "./util";\n'
        )
        chunks = split_chunks(src)
        self.assertEqual(chunks[0].flavour, "python")
        self.assertEqual(chunks[1].flavour, "typescript")

    def test_explicit_marker_overrides(self):
        src = (
            "# ge:typescript\n"
            "const X: number = 1;\n"
            "\n"
            "// ge:python\n"
            "def f() -> int:\n"
            "    return 1\n"
        )
        chunks = split_chunks(src)
        marked = [c for c in chunks if c.explicit]
        self.assertEqual(len(marked), 2)
        self.assertEqual(marked[0].flavour, "typescript")
        self.assertEqual(marked[1].flavour, "python")

    def test_marker_can_pin_an_ambiguous_chunk(self):
        # a python-style header with a braced body is auto-detected, but the
        # marker can also force it
        src = "# ge:typescript\nconst A: number = 2;\n"
        chunks = split_chunks(src)
        self.assertEqual(chunks[0].flavour, "typescript")


class TestBracedBodyWithPythonHeader(unittest.TestCase):
    """`def f(...) -> T:` followed by a braced body is accepted."""

    def test_auto_detected(self):
        src = (
            "def clamp(v: int) -> int:\n"
            "    if (v > 10) {\n"
            "        return 10;\n"
            "    }\n"
            "    return v;\n"
        )
        chunks = split_chunks(src)
        self.assertEqual(chunks[0].flavour, "typescript")

    def test_lowers_correctly(self):
        src = (
            "def clamp(v: int) -> int:\n"
            "    if (v > 10) {\n"
            "        return 10;\n"
            "    }\n"
            "    return v;\n"
        )
        py = hybrid_to_python(src)
        self.assertIn("def clamp(v: int) -> int:", py)
        self.assertIn("if v > 10:", py)
        self.assertIn("return 10", py)

    def test_python_body_stays_python(self):
        src = (
            "def f(n: int) -> int:\n"
            "    if n > 0:\n"
            "        return n\n"
            "    return 0\n"
        )
        chunks = split_chunks(src)
        self.assertEqual(chunks[0].flavour, "python")


class TestLowering(unittest.TestCase):
    def test_one_python_source(self):
        py = hybrid_to_python(MIXED)
        # every definition survives
        for name in ("def double", "def triple", "SCALE", "def clamp",
                     "def render", "def main"):
            if name == "SCALE":
                continue
            self.assertIn(name, py, name)
        self.assertIn("LIMIT: int = 12", py)

    def test_decorators_preserved(self):
        py = hybrid_to_python(MIXED)
        self.assertIn("@rust", py)
        self.assertIn("@cpp", py)

    def test_typescript_body_lowered(self):
        py = hybrid_to_python(MIXED)
        # `while (i <= n) { ... }` style must become python
        self.assertIn("while i <= n:", hybrid_to_python(
            "export function f(n: number): number {\n"
            "  let i: number = 0;\n"
            "  while (i <= n) {\n"
            "    i = i + 1;\n"
            "  }\n"
            "  return i;\n"
            "}\n"))

    def test_result_is_valid_python(self):
        import ast
        ast.parse(hybrid_to_python(MIXED))

    def test_chunk_flavours_report(self):
        rows = chunk_flavours(MIXED)
        self.assertTrue(all(isinstance(r[0], int) for r in rows))
        self.assertTrue(any(r[1] == "typescript" for r in rows))


class TestIRFromHybrid(unittest.TestCase):
    def test_units_and_backends(self):
        from pyeffic.frontends.hybrid import parse_hybrid_source_full
        units, _classes = parse_hybrid_source_full(MIXED)
        by_name = {u.name: u for u in units}
        self.assertIn("double", by_name)
        self.assertIn("triple", by_name)
        self.assertIn("clamp", by_name)
        self.assertIn("render", by_name)
        self.assertIn("main", by_name)
        # decorators set the backend from either flavour
        self.assertEqual(by_name["clamp"].forced_backend, "rust")
        self.assertEqual(by_name["render"].forced_backend, "cpp")

    def test_typescript_types_mapped(self):
        from pyeffic.frontends.hybrid import parse_hybrid_source_full
        units, _ = parse_hybrid_source_full(MIXED)
        triple = next(u for u in units if u.name == "triple")
        self.assertEqual(triple.params, [("x", "int")])
        self.assertEqual(triple.ret_type, "int")


class TestModuleResolutionWithGe(unittest.TestCase):
    def test_ge_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "m.ge").write_text("def f() -> int:\n    return 1\n")
            found = _find_module("app.m", root)
            self.assertIsNotNone(found)
            self.assertTrue(str(found).endswith("m.ge"))

    def test_ge_preferred_over_single_flavour(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "m.ge").write_text("def f() -> int:\n    return 1\n")
            (root / "app" / "m.ge.py").write_text("def g() -> int:\n    return 2\n")
            found = _find_module("app.m", root)
            self.assertTrue(str(found).endswith("m.ge"))

    def test_mixed_project_resolves_across_extensions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "a.ge").write_text(
                "def from_ge() -> int:\n    return 1\n")
            (root / "app" / "b.ge.py").write_text(
                "def from_py() -> int:\n    return 2\n")
            (root / "app" / "c.ge.ts").write_text(
                "export function from_ts(): number { return 3; }\n")
            (root / "main.ge").write_text(
                "from app.a import from_ge\n"
                "from app.b import from_py\n"
                "from app.c import from_ts\n"
                "def main() -> int:\n    return 0\n")

            src = (root / "main.ge").read_text()
            units, _classes, _warnings = resolve_imports(src, root / "main.ge")
            names = {u.name for u in units}
            for n in ("from_ge", "from_py", "from_ts", "main"):
                self.assertIn(n, names, n)


class TestHybridBuildEndToEnd(unittest.TestCase):
    """One `.ge` file, mixed flavours, compiled to native code."""

    def test_build_and_run(self):
        from pyeffic.config import Config, detect_compilers
        from pyeffic.pipeline import build

        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc is required")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            entry = root / "main.ge"
            entry.write_text(
                '"""Mixed-flavour entry."""\n'
                "from pyeffic.backends import rust\n"
                "\n"
                "def double(x: int) -> int:\n"
                "    return x * 2\n"
                "\n"
                "export function triple(x: number): number {\n"
                "    return x * 3;\n"
                "}\n"
                "\n"
                "def main() -> int:\n"
                "    print(double(21))\n"
                "    print(triple(7))\n"
                "    return 0\n"
            )

            cfg = Config(out_dir=root / "ge_build", do_research=False,
                         force_backend="rust")
            report = build(entry, cfg, entry="main")

            self.assertFalse(report.errors.has_errors(),
                             msg=str(report.errors.diagnostics[:3]))
            self.assertIsNotNone(report.rust_compile)
            self.assertTrue(report.rust_compile.ok, msg=report.rust_compile.log[:1200])

            import subprocess
            r = subprocess.run([str(report.rust_compile.exe)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0)
            self.assertIn("42", r.stdout)   # double(21)
            self.assertIn("21", r.stdout)   # triple(7)


if __name__ == "__main__":
    unittest.main()
