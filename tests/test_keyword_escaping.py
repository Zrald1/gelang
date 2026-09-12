"""Tests for identifier escaping in target languages.

GE identifiers are legal Python names, but some of them collide with
reserved words in the target languages (`base` in C#, `match` in Rust, ...).
Every reference — signature, expression, assignment target, declaration —
must escape consistently, or the emitted code fails to compile.
"""
import unittest

from pyeffic.analyzer import parse_source_full
from pyeffic.emitters import emit_cpp, emit_csharp, emit_go, emit_kotlin, emit_rust


def _emit(source: str, emitter):
    units, classes = parse_source_full(source)
    supported = [u for u in units if u.supported and u.body is not None]
    prog, _emitted = emitter(supported, entry="main", classes=classes)
    return prog


class TestCSharpKeywordEscaping(unittest.TestCase):
    SRC = (
        "def f(base: int, years: int) -> int:\n"
        "    result: int = base\n"
        "    for i in range(0, years):\n"
        "        result = result + result // 10\n"
        "    return result\n"
        "\n"
        "\n"
        "def main() -> None:\n"
        "    print(f(100, 2))\n"
    )

    def test_base_parameter_escaped_everywhere(self):
        prog = _emit(self.SRC, emit_csharp)
        # the signature and the body reference must both use @base
        self.assertIn("@base", prog)
        # a bare `base` reference would be CS1511
        import re
        bare = re.findall(r"(?<![@\w])base\b", prog)
        self.assertEqual(bare, [], f"unescaped `base` in:\n{prog}")

    def test_other_keywords(self):
        # C# reserved words that are still legal GE identifiers
        # (`class` is a Python keyword too, so it cannot appear here)
        kws = ("base", "static", "event", "lock", "namespace", "params",
               "virtual", "override")
        params = ", ".join(f"{k}: int" for k in kws)
        body = " + ".join(kws)
        src = f"def g({params}) -> int:\n    return {body}\n"
        prog = _emit(src, emit_csharp)
        for kw in kws:
            self.assertIn("@" + kw, prog, kw)

    def test_non_keyword_untouched(self):
        src = "def g(value: int) -> int:\n    return value\n"
        prog = _emit(src, emit_csharp)
        self.assertIn("value", prog)
        self.assertNotIn("@value", prog)


class TestRustKeywordEscaping(unittest.TestCase):
    def test_match_parameter_escaped(self):
        src = (
            "def f(match: int, type: int) -> int:\n"
            "    return match + type\n"
        )
        prog = _emit(src, emit_rust)
        self.assertIn("r#match", prog)
        self.assertIn("r#type", prog)

    def test_self_renamed(self):
        src = "def f() -> int:\n    self: int = 1\n    return self\n"
        prog = _emit(src, emit_rust)
        self.assertIn("_self", prog)
        self.assertNotIn(" self ", prog)


class TestOtherBackendsStillClean(unittest.TestCase):
    """Backends without a keyword collision must be unaffected."""

    SRC = "def f(base: int) -> int:\n    return base + 1\n"

    def test_cpp(self):
        prog = _emit(self.SRC, emit_cpp)
        self.assertIn("base", prog)
        self.assertNotIn("@base", prog)

    def test_go(self):
        prog = _emit(self.SRC, emit_go)
        self.assertIn("base", prog)

    def test_kotlin(self):
        prog = _emit(self.SRC, emit_kotlin)
        self.assertIn("base", prog)


class TestKeywordBuildEndToEnd(unittest.TestCase):
    """A parameter named `base` must compile and run on the real toolchains."""

    SRC = (
        "def f(base: int, years: int) -> int:\n"
        "    result: int = base\n"
        "    for i in range(0, years):\n"
        "        result = result + result // 10\n"
        "    return result\n"
        "\n"
        "\n"
        "def main() -> None:\n"
        "    print(f(100, 2))\n"
    )

    def _build_and_run(self, backend: str) -> str | None:
        import subprocess
        import tempfile
        from pathlib import Path
        from pyeffic.config import Config, detect_compilers
        from pyeffic.pipeline import build

        info = detect_compilers()
        available = {
            "rust": bool(info.rustc),
            "cpp": bool(info.cpp),
            "csharp": bool(info.dotnet),
        }
        if not available.get(backend):
            return None

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "m.ge.py"
            src.write_text(self.SRC, encoding="utf-8")
            cfg = Config(out_dir=root / "ge_build", do_research=False,
                         force_backend=backend)
            report = build(src, cfg, entry="main")
            cr = {
                "rust": report.rust_compile,
                "cpp": report.cpp_compile,
                "csharp": report.csharp_compile,
            }[backend]
            if cr is None or not cr.ok:
                self.fail(f"{backend} compile failed: "
                          f"{(cr.log if cr else 'no compile result')[:800]}")
            r = subprocess.run([str(cr.exe)], capture_output=True, text=True,
                               timeout=90)
            return r.stdout

    def test_rust(self):
        out = self._build_and_run("rust")
        if out is None:
            self.skipTest("rustc not available")
        self.assertIn("121", out)

    def test_cpp(self):
        out = self._build_and_run("cpp")
        if out is None:
            self.skipTest("C++ compiler not available")
        self.assertIn("121", out)

    def test_csharp(self):
        out = self._build_and_run("csharp")
        if out is None:
            self.skipTest("C# toolchain not available")
        self.assertIn("121", out)


if __name__ == "__main__":
    unittest.main()
