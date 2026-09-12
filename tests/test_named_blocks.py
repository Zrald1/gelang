"""Tests for named `<block>` tags and `@block(...)` calls in .ge files.

A named block gives a chunk a name and makes it callable from anywhere else
in the file (or from another file that imports it), regardless of which
flavour either side is written in.
"""
import ast
import tempfile
import unittest
from pathlib import Path

from pyeffic.frontends.hybrid import (
    Chunk,
    hybrid_to_python,
    split_chunks,
)

BLOCKS = '''"""Named blocks."""
from __future__ import annotations
from pyeffic.backends import cpp, rust


<double>
@rust
def double(x: int) -> int:
    return x * 2
</double>


<triple:typescript>
export function triple(x: number): number {
    return x * 3;
}
</triple>


<limit>
LIMIT: int = 12
</limit>


<clamp:python>
def clamp(v: int) -> int:
    if v > LIMIT:
        return LIMIT
    return v
</clamp>


<render:typescript>
@cpp
export function render(v: number): number {
    return @double(v) + @triple(v);
}
</render>
'''


class TestBlockParsing(unittest.TestCase):
    def test_block_names_captured(self):
        names = [c.block_name for c in split_chunks(BLOCKS) if c.block_name]
        self.assertEqual(names, ["double", "triple", "limit", "clamp", "render"])

    def test_tags_are_stripped(self):
        py = hybrid_to_python(BLOCKS)
        self.assertNotIn("<double>", py)
        self.assertNotIn("</double>", py)
        self.assertNotIn("<render:typescript>", py)

    def test_explicit_language_tag(self):
        chunks = {c.block_name: c for c in split_chunks(BLOCKS) if c.block_name}
        self.assertEqual(chunks["triple"].flavour, "typescript")
        self.assertEqual(chunks["clamp"].flavour, "python")

    def test_auto_detected_language(self):
        chunks = {c.block_name: c for c in split_chunks(BLOCKS) if c.block_name}
        # <double> has no tag, content decides
        self.assertEqual(chunks["double"].flavour, "python")

    def test_lang_alias_ts(self):
        src = "<x:ts>\nexport function x(): number { return 1; }\n</x>\n"
        chunks = split_chunks(src)
        self.assertEqual(chunks[0].flavour, "typescript")

    def test_lang_alias_py(self):
        src = "<x:py>\ndef x() -> int:\n    return 1\n</x>\n"
        chunks = split_chunks(src)
        self.assertEqual(chunks[0].flavour, "python")

    def test_unclosed_block_errors(self):
        from pyeffic.frontends.typescript import TypeScriptSyntaxError
        with self.assertRaises(TypeScriptSyntaxError):
            split_chunks("<x>\ndef x() -> int:\n    return 1\n")

    def test_mismatched_close_errors(self):
        from pyeffic.frontends.typescript import TypeScriptSyntaxError
        with self.assertRaises(TypeScriptSyntaxError):
            split_chunks("<x>\ndef x() -> int:\n    return 1\n</y>\n")


class TestBlockCalls(unittest.TestCase):
    def test_call_lowered_to_function(self):
        py = hybrid_to_python(BLOCKS)
        self.assertIn("return double(v) + triple(v)", py)
        self.assertNotIn("@double(", py)
        self.assertNotIn("@triple(", py)

    def test_block_name_resolves_to_single_function(self):
        # the block is named `calc` but defines `compute`
        src = (
            "<calc>\n"
            "def compute(x: int) -> int:\n"
            "    return x + 1\n"
            "</calc>\n"
            "\n"
            "<use:typescript>\n"
            "export function use(x: number): number {\n"
            "    return @calc(x);\n"
            "}\n"
            "</use>\n"
        )
        py = hybrid_to_python(src)
        self.assertIn("return compute(x)", py)

    def test_call_from_python_block(self):
        src = (
            "<inc>\n"
            "def inc(x: int) -> int:\n"
            "    return x + 1\n"
            "</inc>\n"
            "\n"
            "<use>\n"
            "def use(x: int) -> int:\n"
            "    return @inc(x)\n"
            "</use>\n"
        )
        py = hybrid_to_python(src)
        self.assertIn("return inc(x)", py)

    def test_call_before_definition(self):
        # the call site may precede the block it names
        src = (
            "<use:typescript>\n"
            "export function use(x: number): number {\n"
            "    return @inc(x);\n"
            "}\n"
            "</use>\n"
            "\n"
            "<inc>\n"
            "def inc(x: int) -> int:\n"
            "    return x + 1\n"
            "</inc>\n"
        )
        py = hybrid_to_python(src)
        self.assertIn("return inc(x)", py)

    def test_decorators_are_not_rewritten(self):
        py = hybrid_to_python(BLOCKS)
        self.assertIn("@cpp", py)
        self.assertIn("@rust", py)

    def test_call_inside_string_untouched(self):
        src = (
            "<use>\n"
            "def use() -> int:\n"
            "    print(\"call @missing(1) here\")\n"
            "    return 0\n"
            "</use>\n"
        )
        py = hybrid_to_python(src)
        self.assertIn("@missing(1)", py)

    def test_unknown_block_name_left_as_plain_call(self):
        src = (
            "<use:typescript>\n"
            "export function use(x: number): number {\n"
            "    return @nowhere(x);\n"
            "}\n"
            "</use>\n"
        )
        py = hybrid_to_python(src)
        self.assertIn("nowhere(x)", py)

    def test_result_is_valid_python(self):
        ast.parse(hybrid_to_python(BLOCKS))


class TestBlocksBuildToIR(unittest.TestCase):
    def test_units_from_blocks(self):
        from pyeffic.frontends.hybrid import parse_hybrid_source_full
        units, _classes = parse_hybrid_source_full(BLOCKS)
        by_name = {u.name: u for u in units}
        for n in ("double", "triple", "clamp", "render"):
            self.assertIn(n, by_name, n)
        self.assertEqual(by_name["render"].forced_backend, "cpp")

    def test_block_constant_collected(self):
        from pyeffic.frontends.hybrid import collect_hybrid_constants
        consts = collect_hybrid_constants(BLOCKS)
        self.assertEqual(consts.get("LIMIT"), 12)


class TestCompilerModulesNotResolved(unittest.TestCase):
    """`from pyeffic.backends import rust` is an intrinsic, not user code."""

    def test_backend_import_does_not_pull_compiler_sources(self):
        from pyeffic.modules import resolve_imports
        src = (
            "from pyeffic.backends import cpp, rust\n"
            "\n"
            "<f>\n"
            "@rust\n"
            "def f(x: int) -> int:\n"
            "    return x\n"
            "</f>\n"
        )
        units, _classes, warnings = resolve_imports(src, Path("main.ge"))
        names = [u.name for u in units]
        self.assertIn("f", names)
        # the decorator names must not appear as program functions
        for bogus in ("cpp", "rust", "dart", "csharp", "zig", "go", "kotlin"):
            self.assertNotIn(bogus, names, bogus)
        self.assertEqual(warnings, [])

    def test_future_import_is_silent(self):
        from pyeffic.modules import resolve_imports
        src = "from __future__ import annotations\ndef f() -> int:\n    return 1\n"
        _units, _classes, warnings = resolve_imports(src, Path("main.ge"))
        self.assertEqual(warnings, [])


class TestBlocksEndToEnd(unittest.TestCase):
    """Named blocks across two files, compiled and run."""

    def test_build_and_run(self):
        from pyeffic.config import Config, detect_compilers
        from pyeffic.pipeline import build

        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc is required")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "math.ge").write_text(
                "<double>\n"
                "def double(x: int) -> int:\n"
                "    return x * 2\n"
                "</double>\n"
                "\n"
                "<triple:typescript>\n"
                "export function triple(x: number): number {\n"
                "    return x * 3;\n"
                "}\n"
                "</triple>\n"
                "\n"
                "<combo:typescript>\n"
                "export function combo(x: number): number {\n"
                "    return @double(x) + @triple(x);\n"
                "}\n"
                "</combo>\n"
            )
            (root / "app" / "main.ge").write_text(
                "from app.math import double, triple, combo\n"
            )
            entry = root / "main.ge"
            entry.write_text(
                "from app.main import double, triple, combo\n"
                "\n"
                "def main() -> int:\n"
                "    print(@double(21))\n"
                "    print(@triple(7))\n"
                "    print(@combo(10))\n"
                "    return 0\n"
            )

            cfg = Config(out_dir=root / "ge_build", do_research=False,
                         force_backend="rust")
            report = build(entry, cfg, entry="main")
            self.assertFalse(report.errors.has_errors(),
                             msg=str(report.errors.diagnostics[:3]))
            self.assertTrue(report.rust_compile and report.rust_compile.ok,
                            msg=(report.rust_compile.log[:1200]
                                 if report.rust_compile else "no compile"))

            import subprocess
            r = subprocess.run([str(report.rust_compile.exe)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0)
            self.assertIn("42", r.stdout)   # @double(21)
            self.assertIn("21", r.stdout)   # @triple(7)
            self.assertIn("50", r.stdout)   # @combo(10) crosses blocks


if __name__ == "__main__":
    unittest.main()
