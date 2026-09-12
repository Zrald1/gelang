"""Tests for new GE features: comprehensions, lambdas, with statements, generators, stdlib."""
import unittest
import tempfile
import subprocess
from pathlib import Path
from pyeffic.pipeline import build
from pyeffic.config import Config


def _run_backend(source: str, backend: str) -> str | None:
    """Build and run source with the given backend, return stdout or None on failure."""
    tmpdir = Path(tempfile.mkdtemp())
    src = tmpdir / "test.ge.py"
    src.write_text(source, encoding="utf-8")
    cfg = Config(out_dir=tmpdir / "out", force_backend=backend, do_research=False)
    try:
        report = build(src, cfg)
        cr = getattr(report, backend + "_compile", None)
        if cr and cr.ok and cr.exe:
            r = subprocess.run([str(cr.exe)], capture_output=True, text=True,
                             timeout=30, cwd=str(cr.exe.parent))
            return r.stdout.strip()
    except Exception:
        pass
    return None


class TestListComprehensions(unittest.TestCase):
    def test_rust_comprehension(self):
        out = _run_backend("""
def main() -> None:
    s: list = [x * x for x in range(5)]
    print(s[0])
    print(s[4])
""", "rust")
        self.assertEqual(out, "0\n16")

    def test_cpp_comprehension(self):
        out = _run_backend("""
def main() -> None:
    s: list = [x * x for x in range(5)]
    print(s[0])
    print(s[4])
""", "cpp")
        self.assertEqual(out, "0\n16")

    def test_csharp_comprehension(self):
        out = _run_backend("""
def main() -> None:
    s: list = [x * x for x in range(5)]
    print(s[0])
    print(s[4])
""", "csharp")
        self.assertEqual(out, "0\n16")

    def test_go_comprehension(self):
        out = _run_backend("""
def main() -> None:
    s: list = [x * x for x in range(5)]
    print(s[0])
    print(s[4])
""", "go")
        self.assertEqual(out, "0\n16")

    def test_kotlin_comprehension(self):
        out = _run_backend("""
def main() -> None:
    s: list = [x * x for x in range(5)]
    print(s[0])
    print(s[4])
""", "kotlin")
        self.assertEqual(out, "0\n16")


class TestGenerators(unittest.TestCase):
    def test_rust_generator(self):
        out = _run_backend("""
def gen_squares(n: int) -> list:
    for i in range(n):
        yield i * i

def main() -> None:
    r: list = gen_squares(5)
    print(r[0])
    print(r[4])
""", "rust")
        self.assertEqual(out, "0\n16")

    def test_cpp_generator(self):
        out = _run_backend("""
def gen_squares(n: int) -> list:
    for i in range(n):
        yield i * i

def main() -> None:
    r: list = gen_squares(5)
    print(r[0])
    print(r[4])
""", "cpp")
        self.assertEqual(out, "0\n16")

    def test_go_generator(self):
        out = _run_backend("""
def gen_squares(n: int) -> list:
    for i in range(n):
        yield i * i

def main() -> None:
    r: list = gen_squares(5)
    print(r[0])
    print(r[4])
""", "go")
        self.assertEqual(out, "0\n16")


class TestMutableListParams(unittest.TestCase):
    def test_rust_mutlist(self):
        out = _run_backend("""
def add_one(items: list) -> None:
    for i in range(len(items)):
        items[i] = items[i] + 1

def main() -> None:
    nums: list = [1, 2, 3]
    add_one(nums)
    print(nums[0])
    print(nums[2])
""", "rust")
        self.assertEqual(out, "2\n4")

    def test_go_mutlist(self):
        out = _run_backend("""
def add_one(items: list) -> None:
    for i in range(len(items)):
        items[i] = items[i] + 1

def main() -> None:
    nums: list = [1, 2, 3]
    add_one(nums)
    print(nums[0])
    print(nums[2])
""", "go")
        self.assertEqual(out, "2\n4")


class TestStdlibMath(unittest.TestCase):
    def test_rust_sqrt(self):
        out = _run_backend("""
def main() -> None:
    x: float = sqrt(16.0)
    print(x)
""", "rust")
        self.assertEqual(out, "4")

    def test_cpp_floor(self):
        out = _run_backend("""
def main() -> None:
    x: float = floor(3.7)
    print(x)
""", "cpp")
        self.assertEqual(out, "3")

    def test_go_ceil(self):
        out = _run_backend("""
def main() -> None:
    x: float = ceil(2.1)
    print(x)
""", "go")
        self.assertEqual(out, "3")


class TestModuleImports(unittest.TestCase):
    def test_import_resolution(self):
        from pyeffic.modules import resolve_imports
        tmpdir = Path(tempfile.mkdtemp())
        mod_src = "def square(x: int) -> int:\n    return x * x\n"
        (tmpdir / "math_utils.ge.py").write_text(mod_src, encoding="utf-8")
        main_src = "from math_utils import square\ndef main() -> None:\n    print(square(5))\n"
        src = tmpdir / "test.ge.py"
        src.write_text(main_src, encoding="utf-8")
        units, classes, warnings = resolve_imports(main_src, src)
        self.assertEqual(len(warnings), 0)
        names = [u.name for u in units]
        self.assertIn("square", names)
        self.assertIn("main", names)


class TestErrorDiagnostics(unittest.TestCase):
    def test_type_mismatch_diagnostic(self):
        from pyeffic.typecheck import check_source
        source = 'def main() -> None:\n    x: str = 5\n'
        reporter = check_source(source, file="test.ge.py", entry="main")
        errors = [d for d in reporter.diagnostics if d.severity == "error"]
        self.assertTrue(any("GE002" in d.code for d in errors))

    def test_untyped_param_diagnostic(self):
        from pyeffic.typecheck import check_source
        source = 'def f(x):\n    return x\n\ndef main() -> None:\n    print(f(1))\n'
        reporter = check_source(source, file="test.ge.py", entry="main")
        errors = [d for d in reporter.diagnostics if d.severity == "error"]
        self.assertTrue(any("GE003" in d.code for d in errors))

    def test_undefined_function_diagnostic(self):
        from pyeffic.typecheck import check_source
        source = 'def main() -> None:\n    print(undefined_func())\n'
        reporter = check_source(source, file="test.ge.py", entry="main")
        errors = [d for d in reporter.diagnostics if d.severity == "error"]
        self.assertTrue(any("GE007" in d.code for d in errors))

    def test_missing_entry_diagnostic(self):
        from pyeffic.typecheck import check_source
        source = 'def f() -> int:\n    return 1\n'
        reporter = check_source(source, file="test.ge.py", entry="main")
        errors = [d for d in reporter.diagnostics if d.severity == "error"]
        self.assertTrue(any("GE008" in d.code for d in errors))


class TestBackendCapabilityMatrix(unittest.TestCase):
    def test_matrix_file_exists(self):
        """The BACKEND_CAPABILITIES.md file should exist."""
        p = Path(__file__).parent.parent / "BACKEND_CAPABILITIES.md"
        self.assertTrue(p.exists())

    def test_matrix_documents_all_backends(self):
        """The matrix should document all 6 backends."""
        p = Path(__file__).parent.parent / "BACKEND_CAPABILITIES.md"
        content = p.read_text(encoding="utf-8")
        for backend in ["Rust", "C\\+\\+", "C#", "Zig", "Go", "Kotlin"]:
            import re
            self.assertTrue(re.search(backend, content))


if __name__ == "__main__":
    unittest.main()
