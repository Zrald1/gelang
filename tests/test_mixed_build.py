"""Tests for mixed-backend native builds and the TypeScript flavour.

These cover the pieces that let one `ge build` produce a single executable
from a program that mixes Rust and C++ functions:

  - frontend detection for .ge.py / .ge.ts
  - cross-backend call detection
  - extern "C" declaration generation on both sides
  - module resolution across flavours
"""
import ast
import tempfile
import unittest
from pathlib import Path

from pyeffic.frontends import TYPESCRIPT_SUFFIXES, frontend_for, python_flavour_of
from pyeffic.frontends.typescript import ts_to_python
from pyeffic.modules import _find_module, resolve_imports


class TestExtensionRouting(unittest.TestCase):
    def test_ge_ts_is_typescript(self):
        self.assertEqual(frontend_for("app/memory.ge.ts"), "typescript")
        self.assertEqual(frontend_for("APP/MEMORY.GE.TS"), "typescript")

    def test_ge_py_is_python(self):
        self.assertEqual(frontend_for("app/memory.ge.py"), "python")

    def test_canonical_ts_suffix_first(self):
        # .ge.ts is the canonical TypeScript extension
        self.assertEqual(TYPESCRIPT_SUFFIXES[0], ".ge.ts")

    def test_legacy_ts_ge_py_still_accepted(self):
        self.assertEqual(frontend_for("app/memory.ts.ge.py"), "typescript")

    def test_python_flavour_of(self):
        self.assertTrue(python_flavour_of("app/m.ge.ts").endswith("m.ge.py"))
        self.assertTrue(python_flavour_of("app/m.ge.py").endswith("m.ge.py"))


class TestDecoratorsInTsFlavour(unittest.TestCase):
    def test_cpp_decorator(self):
        py = ts_to_python("@cpp\nexport function f(a: number): number { return a; }")
        self.assertIn("@cpp", py)
        self.assertIn("def f(a: int) -> int:", py)

    def test_rust_decorator(self):
        py = ts_to_python("@rust\nexport function g(): number { return 1; }")
        self.assertIn("@rust", py)

    def test_decorator_sets_forced_backend(self):
        from pyeffic.frontends.typescript import parse_ts_source_full
        units, _ = parse_ts_source_full(
            "@cpp\nexport function draw(): number { return 0; }\n"
            "@rust\nexport function calc(): number { return 1; }\n")
        by_name = {u.name: u for u in units}
        self.assertEqual(by_name["draw"].forced_backend, "cpp")
        self.assertEqual(by_name["calc"].forced_backend, "rust")


class TestRelativeImports(unittest.TestCase):
    def test_parent_relative_import(self):
        py = ts_to_python('import { a } from "../memory/limits";')
        self.assertIn("from memory.limits import a", py)

    def test_sibling_relative_import(self):
        py = ts_to_python('import { b } from "./theme";')
        self.assertIn("from theme import b", py)

    def test_grandparent_relative_import(self):
        py = ts_to_python('import { c } from "../../shared/util";')
        self.assertIn("from shared.util import c", py)


class TestIntrinsicPayloads(unittest.TestCase):
    def test_template_payload_kept_raw(self):
        src = 'gePreamble("cpp", `\n#include <windows.h>\nstatic int x = 1;\n`);'
        py = ts_to_python(src)
        # the payload must reach the emitter byte-for-byte
        tree = ast.parse(py)
        call = tree.body[0].value
        payload = ast.literal_eval(call.args[1])
        self.assertIn("#include <windows.h>", payload)
        self.assertIn("static int x = 1;", payload)

    def test_escaped_quotes_decoded_in_string_args(self):
        src = 'geInline("cpp", "return ge_env_len(\\"KEY\\");");'
        py = ts_to_python(src)
        tree = ast.parse(py)
        payload = ast.literal_eval(tree.body[0].value.args[1])
        self.assertEqual(payload, 'return ge_env_len("KEY");')

    def test_template_escapes_survive(self):
        # raw string: the template must contain the two-character escape \r,
        # not an actual carriage return
        src = r'geInline("cpp", `\r\n`);'
        py = ts_to_python(src)
        tree = ast.parse(py)
        payload = ast.literal_eval(tree.body[0].value.args[1])
        # the C++ escape sequence must survive as an escape, not a real CRLF
        self.assertEqual(payload, "\\r\\n")


class TestModuleResolutionAcrossFlavours(unittest.TestCase):
    def test_dotted_name_does_not_match_sibling_leaf(self):
        """`app.main` must never resolve to a sibling `main.ge.py`."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "desktop").mkdir()
            (root / "desktop" / "main.ge.py").write_text(
                "def entry() -> int:\n    return 0\n")
            (root / "app" / "main.ge.py").write_text(
                "def appmain() -> int:\n    return 1\n")

            found = _find_module("app.main", root / "desktop")
            self.assertIsNotNone(found)
            self.assertTrue(str(found).replace("\\", "/").endswith("app/main.ge.py"),
                            f"resolved to {found}")

    def test_ts_flavour_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "m.ge.ts").write_text(
                "export function f(): number { return 1; }\n")
            found = _find_module("app.m", root)
            self.assertIsNotNone(found)
            self.assertTrue(str(found).endswith("m.ge.ts"))

    def test_python_flavour_preferred_over_ts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "m.ge.py").write_text("def f() -> int:\n    return 1\n")
            (root / "app" / "m.ge.ts").write_text(
                "export function g(): number { return 2; }\n")
            found = _find_module("app.m", root)
            self.assertTrue(str(found).endswith("m.ge.py"))

    def test_mixed_flavour_project_resolves(self):
        """A project mixing .ge.py and .ge.ts resolves both."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "core").mkdir()
            (root / "app" / "core" / "add.ge.py").write_text(
                "from pyeffic.backends import rust\n\n"
                "@rust\n"
                "def add(a: int, b: int) -> int:\n    return a + b\n")
            (root / "app" / "core" / "mul.ge.ts").write_text(
                "@rust\n"
                "export function mul(a: number, b: number): number { return a * b; }\n")
            (root / "app" / "main.ge.py").write_text(
                "from app.core.add import add\n"
                "from app.core.mul import mul\n")
            (root / "entry.ge.py").write_text(
                "from app.main import add, mul\n"
                "def main() -> int:\n    return 0\n")

            src = (root / "entry.ge.py").read_text()
            units, _classes, _warnings = resolve_imports(src, root / "entry.ge.py")
            names = {u.name for u in units}
            self.assertIn("add", names)
            self.assertIn("mul", names)
            self.assertIn("main", names)


class TestMixedBuildGrouping(unittest.TestCase):
    """The mixed build must split units by backend and link them."""

    def test_backend_split(self):
        from pyeffic.frontends.typescript import parse_ts_source_full
        units, _ = parse_ts_source_full(
            "@cpp\nexport function render(): number { return 0; }\n"
            "@rust\nexport function shell(): number { return 1; }\n"
            "export function entry(): number { return 2; }\n")
        groups: dict[str, list] = {}
        for u in units:
            b = u.forced_backend or "rust"
            groups.setdefault(b, []).append(u)
        self.assertEqual(len(groups["cpp"]), 1)
        self.assertEqual(len(groups["rust"]), 2)

    def test_cross_calls_detected(self):
        """A C++ function calling a Rust function is found by call-graph walk."""
        from pyeffic.frontends.typescript import parse_ts_source_full
        units, _ = parse_ts_source_full(
            "@rust\nexport function mem_max(): number { return 8; }\n"
            "@cpp\nexport function layout(): number { return mem_max(); }\n")
        by_name = {u.name: u for u in units}
        called = set()
        for node in ast.walk(by_name["layout"].body):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
        self.assertIn("mem_max", called)


class TestMixedBuildEndToEnd(unittest.TestCase):
    """Compile a tiny mixed Rust+C++ program and run it."""

    def test_build_and_run(self):
        from pyeffic.config import Config, detect_compilers
        from pyeffic.pipeline import build_native_mixed

        info = detect_compilers()
        if not (info.rustc and info.cpp):
            self.skipTest("rustc and a C++ compiler are required")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "core.ge.ts").write_text(
                "@rust\n"
                "export function twice(x: number): number { return x * 2; }\n"
                "\n"
                "@cpp\n"
                "export function plus_one(x: number): number { return twice(x) + 1; }\n"
            )
            entry = root / "main.ge.py"
            entry.write_text(
                "from app.core import twice, plus_one\n"
                "\n"
                "def main() -> int:\n"
                "    print(plus_one(20))\n"
                "    return 0\n"
            )

            cfg = Config(out_dir=root / "ge_build", do_research=False)
            report = build_native_mixed(entry, cfg, entry="main")

            self.assertFalse(report.errors.has_errors(),
                             msg=report.compile_log[:1500])
            self.assertTrue(report.compile_ok, msg=report.compile_log[:1500])
            self.assertIn("rust", report.group_sizes)
            self.assertIn("cpp", report.group_sizes)
            self.assertIn("cpp", report.objects)
            self.assertIsNotNone(report.exe)

            import subprocess
            r = subprocess.run([str(report.exe)], capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 0)
            # plus_one(20) -> twice(20) + 1 -> 41, crossing the C ABI twice
            self.assertIn("41", r.stdout)


if __name__ == "__main__":
    unittest.main()
