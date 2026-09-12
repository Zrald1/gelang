"""Simulation tests: test combining different languages, separate languages,
UI+backend integration, no backend, no UI, and all combinations.

These tests verify that the GE pipeline correctly handles:
  1. Combined backends (Rust + C++ + C# + Zig + Go in one program)
  2. Separate single-backend builds (Rust only, C++ only, etc.)
  3. UI + backend integration (UI DSL + native backend)
  4. No backend (UI only, Dart only)
  5. No UI (backend only, no Flutter)
  6. All backends with UI
"""
import unittest
import tempfile
from pathlib import Path
from pyeffic.analyzer import parse_source
from pyeffic.emitters import (emit_rust, emit_cpp, emit_csharp, emit_zig, emit_go,
                               emit_dart_functions)
from pyeffic.ui_dsl import parse_ui_dsl, ui_dsl_to_flutter, collect_state_from_screen
from pyeffic.config import Config, detect_compilers
from pyeffic.pipeline import build, build_flutter
from pyeffic.backends import rust, cpp, dart, csharp, zig, go


class TestCombinedBackends(unittest.TestCase):
    """Test that multiple backends can be used in one program."""

    def test_all_decorators_parsed(self):
        """Test that all 6 backend decorators are parsed correctly."""
        source = """
from pyeffic.backends import rust, cpp, dart, csharp, zig, go

@rust
def rust_fn(x: int) -> int:
    return x

@cpp
def cpp_fn(x: int) -> int:
    return x

@dart
def dart_fn(x: int) -> int:
    return x

@csharp
def csharp_fn(x: int) -> int:
    return x

@zig
def zig_fn(x: int) -> int:
    return x

@go
def go_fn(x: int) -> int:
    return x
"""
        units = parse_source(source)
        backends = {u.name: u.forced_backend for u in units if u.name.endswith("_fn")}
        self.assertEqual(backends["rust_fn"], "rust")
        self.assertEqual(backends["cpp_fn"], "cpp")
        self.assertEqual(backends["dart_fn"], "dart")
        self.assertEqual(backends["csharp_fn"], "csharp")
        self.assertEqual(backends["zig_fn"], "zig")
        self.assertEqual(backends["go_fn"], "go")

    def test_all_emitters_produce_code(self):
        """Test that all 6 emitters produce valid code for a simple function."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
"""
        units = parse_source(source)

        # Rust
        prog, _ = emit_rust(units, entry=None)
        self.assertIn("fn add(a: i64, b: i64) -> i64", prog)

        # C++
        prog, _ = emit_cpp(units, entry=None)
        self.assertIn("int64_t add(int64_t a, int64_t b)", prog)

        # C#
        prog, _ = emit_csharp(units, entry=None)
        self.assertIn("static long add(long a, long b)", prog)

        # Zig
        prog, _ = emit_zig(units, entry=None)
        self.assertIn("fn add(a: i64, b: i64) i64", prog)

        # Go
        prog, _ = emit_go(units, entry=None)
        self.assertIn("func add(a int64, b int64) int64", prog)

    def test_all_emitters_produce_library_mode(self):
        """Test that all emitters produce C ABI exports in library mode."""
        source = """
def compute(x: int) -> int:
    return x * 2
"""
        units = parse_source(source)
        from pyeffic.ffi import tag_ffi
        tag_ffi(units)

        # Rust library mode
        prog, _ = emit_rust(units, entry=None, library_mode=True)
        self.assertIn("extern \"C\"", prog)

        # C++ library mode
        prog, _ = emit_cpp(units, entry=None, library_mode=True)
        self.assertIn('extern "C"', prog)

        # C# library mode
        prog, _ = emit_csharp(units, entry=None, library_mode=True)
        self.assertIn("UnmanagedCallersOnly", prog)

        # Zig library mode
        prog, _ = emit_zig(units, entry=None, library_mode=True)
        self.assertIn("export fn", prog)

        # Go library mode
        prog, _ = emit_go(units, entry=None, library_mode=True)
        self.assertIn("//export", prog)

    def test_mixed_rust_cpp_compilation(self):
        """Test that Rust + C++ can be compiled together."""
        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc not available")

        source = """
from pyeffic.backends import rust, cpp

@rust
def rust_add(a: int, b: int) -> int:
    return a + b

@cpp
def cpp_mul(a: int, b: int) -> int:
    return a * b

def main() -> None:
    print(rust_add(3, 4))
    print(cpp_mul(5, 6))
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(source, encoding="utf-8")
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                        force_backend="rust")
            report = build(src, cfg, entry="main")
            # at least one backend should compile
            compiled = any(
                cr and cr.ok for cr in
                (report.rust_compile, report.cpp_compile)
            )
            self.assertTrue(compiled, "At least one backend should compile")


class TestSeparateBackends(unittest.TestCase):
    """Test each backend separately."""

    def _compile_single_backend(self, source: str, backend: str):
        """Compile a source with a single forced backend. Returns (report, tmpdir)."""
        info = detect_compilers()
        tmpdir = tempfile.mkdtemp()
        src = Path(tmpdir) / "test.ge.py"
        src.write_text(source, encoding="utf-8")
        cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                    force_backend=backend)
        report = build(src, cfg, entry="main")
        return report, Path(tmpdir)

    def test_rust_only(self):
        """Test Rust-only build."""
        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc not available")
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""
        report, tmpdir = self._compile_single_backend(source, "rust")
        self.assertTrue(report.rust_compile and report.rust_compile.ok)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cpp_only(self):
        """Test C++-only build."""
        info = detect_compilers()
        if not info.cpp:
            self.skipTest("C++ compiler not available")
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""
        report, tmpdir = self._compile_single_backend(source, "cpp")
        self.assertTrue(report.cpp_compile and report.cpp_compile.ok)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_csharp_emission(self):
        """Test C# code emission (compilation may not be available)."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""
        report, tmpdir = self._compile_single_backend(source, "csharp")
        self.assertIsNotNone(report.csharp_src)
        self.assertTrue(report.csharp_src.exists())
        csharp_code = report.csharp_src.read_text()
        self.assertIn("static long add(long a, long b)", csharp_code)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_zig_emission(self):
        """Test Zig code emission."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""
        report, tmpdir = self._compile_single_backend(source, "zig")
        self.assertIsNotNone(report.zig_src)
        self.assertTrue(report.zig_src.exists())
        zig_code = report.zig_src.read_text()
        self.assertIn("fn add(a: i64, b: i64) i64", zig_code)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_go_emission(self):
        """Test Go code emission."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(10, 20))
"""
        report, tmpdir = self._compile_single_backend(source, "go")
        self.assertIsNotNone(report.go_src)
        self.assertTrue(report.go_src.exists())
        go_code = report.go_src.read_text()
        self.assertIn("func add(a int64, b int64) int64", go_code)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestUIDSL(unittest.TestCase):
    """Test the GE UI DSL parser and Flutter generator."""

    def test_parse_simple_screen(self):
        ui_source = '''
Screen "Test App" {
    state: counter: int = 0
    Column {
        Text "Hello World" style="fontSize:20; bold:true"
        Text state="counter"
        Divider
        ElevatedButton "Increment" on_click=Action(call="increment", update="counter")
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        self.assertEqual(screen.title, "Test App")
        self.assertEqual(len(screen.state_vars), 1)
        self.assertEqual(screen.state_vars[0].name, "counter")
        self.assertEqual(screen.state_vars[0].type, "int")
        self.assertEqual(screen.state_vars[0].default, 0)
        self.assertIsNotNone(screen.root)
        self.assertEqual(screen.root.kind, "Column")
        self.assertEqual(len(screen.root.children), 4)

    def test_parse_nested_containers(self):
        ui_source = '''
Screen "Nested" {
    Column {
        Row {
            Text "Left"
            Text "Right"
        }
        Divider
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        self.assertEqual(screen.root.kind, "Column")
        self.assertEqual(len(screen.root.children), 2)
        self.assertEqual(screen.root.children[0].kind, "Row")
        self.assertEqual(len(screen.root.children[0].children), 2)

    def test_parse_state_declarations(self):
        ui_source = '''
Screen "States" {
    state: total: int = 100
    state: name: str = "Default"
    state: active: bool = true
    Column {
        Text state="total"
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        self.assertEqual(len(screen.state_vars), 3)
        self.assertEqual(screen.state_vars[0].name, "total")
        self.assertEqual(screen.state_vars[0].type, "int")
        self.assertEqual(screen.state_vars[0].default, 100)
        self.assertEqual(screen.state_vars[1].name, "name")
        self.assertEqual(screen.state_vars[1].type, "str")
        self.assertEqual(screen.state_vars[1].default, "Default")
        self.assertEqual(screen.state_vars[2].name, "active")
        self.assertEqual(screen.state_vars[2].type, "bool")
        self.assertEqual(screen.state_vars[2].default, True)

    def test_parse_style_strings(self):
        ui_source = '''
Screen "Styled" {
    Column {
        Text "Title" style="fontSize:24; bold:true; color:#1565C0"
        Text "Body" style="fontSize:14; color:grey600"
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        title = screen.root.children[0]
        self.assertEqual(title.text, "Title")
        self.assertIn("fontSize", title.style_dict)
        self.assertEqual(title.style_dict["fontSize"], 24)

    def test_parse_actions(self):
        ui_source = '''
Screen "Actions" {
    state: result: int = 0
    Column {
        ElevatedButton "Compute" on_click=Action(call="compute", args=[], update="result")
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        button = screen.root.children[0]
        self.assertEqual(button.kind, "ElevatedButton")
        self.assertEqual(button.label, "Compute")
        self.assertIsNotNone(button.action)
        self.assertEqual(button.action["call"], "compute")
        self.assertEqual(button.action["update"], "result")

    def test_collect_state(self):
        ui_source = '''
Screen "State Test" {
    state: a: int = 0
    state: b: int = 0
    Column {
        Text state="a"
        Text state="b"
        Text "static"
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        states = collect_state_from_screen(screen)
        self.assertIn("a", states)
        self.assertIn("b", states)

    def test_flutter_generation(self):
        ui_source = '''
Screen "Test App" {
    state: counter: int = 0
    Column {
        Text "Counter" style="headline"
        Text state="counter" style="value"
        ElevatedButton "Increment" on_click=Action(call="increment", update="counter")
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        dart = ui_dsl_to_flutter(screen)
        self.assertIn("class TestAppScreen extends StatefulWidget", dart)
        self.assertIn("int counter = 0", dart)
        self.assertIn("Scaffold", dart)
        self.assertIn("AppBar", dart)
        self.assertIn("Column", dart)
        self.assertIn("ElevatedButton", dart)

    def test_sized_box(self):
        ui_source = '''
Screen "Spacing" {
    Column {
        Text "Above"
        SizedBox height=20
        Text "Below"
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        sized = screen.root.children[1]
        self.assertEqual(sized.kind, "SizedBox")
        self.assertEqual(sized.props.get("height"), 20)

    def test_divider(self):
        ui_source = '''
Screen "Divider Test" {
    Column {
        Text "Above"
        Divider
        Text "Below"
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        self.assertEqual(screen.root.children[1].kind, "Divider")


class TestUIBackendIntegration(unittest.TestCase):
    """Test UI + backend integration scenarios."""

    def test_ui_with_rust_backend(self):
        """Test UI DSL combined with Rust backend."""
        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc not available")

        ge_source = '''
def compute_total() -> int:
    return 42

def main() -> None:
    print(compute_total())

def build():
    from pyeffic.widgets import Text, Column
    return Column([
        Text("Total"),
        Text("42"),
    ])
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(ge_source, encoding="utf-8")
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                        force_backend="rust")
            report = build_flutter(src, cfg, app_name="test_ui_rust",
                                   lib_basename="ge_logic")
            self.assertIsNotNone(report.main_dart)
            self.assertTrue(report.main_dart.exists())
            # Flutter artifacts live under the mobile bucket
            # check backend/ folder exists
            backend_dir = (Path(tmpdir) / "out" / "mobile"
                           / "test_ui_rust" / "backend")
            self.assertTrue(backend_dir.exists())
            # check ui/ folder exists
            ui_dir = Path(tmpdir) / "out" / "mobile" / "test_ui_rust" / "ui"
            self.assertTrue(ui_dir.exists())

    def test_ui_dsl_with_backend(self):
        """Test standalone UI DSL file combined with backend."""
        ui_source = '''
Screen "MyRent" {
    state: total: int = 0
    Column {
        Text "Total Rent" style="headline"
        Text state="total" style="value"
        ElevatedButton "Refresh" on_click=Action(call="compute_total", update="total")
    }
}
'''
        screen = parse_ui_dsl(ui_source)
        dart = ui_dsl_to_flutter(screen)
        self.assertIn("MyRentScreen", dart)
        self.assertIn("compute_total", dart)

    def test_no_backend_ui_only(self):
        """Test UI-only build (no native backend, Dart only)."""
        ge_source = '''
from pyeffic.backends import dart

@dart
def format_message(name: str) -> str:
    return name

def build():
    from pyeffic.widgets import Text, Column
    return Column([
        Text("Hello"),
        Text("World"),
    ])
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(ge_source, encoding="utf-8")
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False)
            report = build_flutter(src, cfg, app_name="ui_only",
                                   lib_basename="ge_logic")
            # should still generate Dart files even without native backend
            self.assertIsNotNone(report.main_dart)
            self.assertTrue(report.main_dart.exists())

    def test_no_ui_backend_only(self):
        """Test backend-only build (no UI, no Flutter)."""
        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc not available")

        ge_source = '''
def compute(a: int, b: int) -> int:
    return a + b

def main() -> None:
    print(compute(10, 20))
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(ge_source, encoding="utf-8")
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                        force_backend="rust")
            report = build(src, cfg, entry="main")
            self.assertTrue(report.rust_compile and report.rust_compile.ok)
            # no Flutter files should be generated
            self.assertIsNone(report.main_dart if hasattr(report, 'main_dart') else None)


class TestAllCombinations(unittest.TestCase):
    """Test all combinations of backends and UI."""

    def test_all_backends_emit_correct_types(self):
        """Test that all backends emit correct type mappings."""
        source = """
def f(a: int, b: float, c: bool) -> int:
    return a
"""
        units = parse_source(source)

        # Rust types
        prog, _ = emit_rust(units, entry=None)
        self.assertIn("i64", prog)
        self.assertIn("f64", prog)
        self.assertIn("bool", prog)

        # C++ types
        prog, _ = emit_cpp(units, entry=None)
        self.assertIn("int64_t", prog)
        self.assertIn("double", prog)

        # C# types
        prog, _ = emit_csharp(units, entry=None)
        self.assertIn("long", prog)
        self.assertIn("double", prog)

        # Zig types
        prog, _ = emit_zig(units, entry=None)
        self.assertIn("i64", prog)
        self.assertIn("f64", prog)

        # Go types
        prog, _ = emit_go(units, entry=None)
        self.assertIn("int64", prog)
        self.assertIn("float64", prog)

    def test_all_backends_handle_arithmetic(self):
        """Test that all backends can handle arithmetic operations."""
        source = """
def compute(a: int, b: int) -> int:
    total: int = 0
    for i in range(0, b):
        total = total + a
    return total
"""
        units = parse_source(source)

        for emit_fn, name in [(emit_rust, "Rust"), (emit_cpp, "C++"),
                               (emit_csharp, "C#"), (emit_zig, "Zig"),
                               (emit_go, "Go")]:
            prog, _ = emit_fn(units, entry=None)
            self.assertIn("total", prog.lower(), f"{name} should have total variable")
            # all backends use either 'for' or 'while' for loops
            self.assertTrue("for" in prog.lower() or "while" in prog.lower(),
                          f"{name} should have a loop")

    def test_all_backends_handle_conditionals(self):
        """Test that all backends can handle if/else."""
        source = """
def classify(x: int) -> int:
    if x > 0:
        return 1
    return 0
"""
        units = parse_source(source)

        for emit_fn, name in [(emit_rust, "Rust"), (emit_cpp, "C++"),
                               (emit_csharp, "C#"), (emit_zig, "Zig"),
                               (emit_go, "Go")]:
            prog, _ = emit_fn(units, entry=None)
            self.assertIn("if", prog.lower(), f"{name} should have if statement")

    def test_build_folder_structure(self):
        """Test that the build output has backend/ and ui/ folders."""
        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc not available")

        ge_source = '''
def compute() -> int:
    return 42

def main() -> None:
    print(compute())

def build():
    from pyeffic.widgets import Text, Column
    return Column([
        Text("Test"),
    ])
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.ge.py"
            src.write_text(ge_source, encoding="utf-8")
            cfg = Config(out_dir=Path(tmpdir) / "out", do_research=False,
                        force_backend="rust")
            report = build_flutter(src, cfg, app_name="folder_test",
                                   lib_basename="ge_logic")

            # Flutter artifacts live under the mobile bucket:
            #   out/mobile/<app>/{backend,ui,lib}
            project_dir = Path(tmpdir) / "out" / "mobile" / "folder_test"
            # backend/ folder should exist with native source
            self.assertTrue((project_dir / "backend").exists(),
                           "backend/ folder should exist")
            # ui/ folder should exist with Dart files
            self.assertTrue((project_dir / "ui").exists(),
                           "ui/ folder should exist")
            # lib/ folder should exist with Flutter files
            self.assertTrue((project_dir / "lib").exists(),
                           "lib/ folder should exist")
            # check that backend has .rs file
            rs_files = list((project_dir / "backend").glob("*.rs"))
            self.assertTrue(len(rs_files) > 0, "backend/ should have .rs file")
            # check that ui has main.dart
            self.assertTrue((project_dir / "ui" / "main.dart").exists(),
                           "ui/ should have main.dart")

    def test_decorators_are_identity_at_runtime(self):
        """Test that all backend decorators are identity functions at runtime."""
        def foo():
            return 42
        self.assertIs(rust(foo), foo)
        self.assertIs(cpp(foo), foo)
        self.assertIs(dart(foo), foo)
        self.assertIs(csharp(foo), foo)
        self.assertIs(zig(foo), foo)
        self.assertIs(go(foo), foo)


if __name__ == "__main__":
    unittest.main()
