"""Tests for GE scaffolding and inspector widget."""
import unittest
import tempfile
import shutil
from pathlib import Path
from pyeffic.scaffold import create_project_noninteractive, ALL_PLATFORMS, ALL_BACKENDS


class TestScaffolding(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_all_platforms_all_backends(self):
        proj = create_project_noninteractive("test_app", self.tmpdir,
                                             platforms=ALL_PLATFORMS,
                                             backends=ALL_BACKENDS)
        self.assertTrue(proj.exists())
        self.assertTrue((proj / "app" / "main.ge.py").exists())
        self.assertTrue((proj / "desktop" / "main.ge.py").exists())
        self.assertTrue((proj / "web" / "main.ge.py").exists())
        self.assertTrue((proj / "mobile" / "main.ge.py").exists())
        self.assertTrue((proj / "backend" / "main.ge.py").exists())
        self.assertTrue((proj / "ui" / "main.ge.ui").exists())
        self.assertTrue((proj / "tests" / "test_app.py").exists())
        self.assertTrue((proj / "ge.toml").exists())
        self.assertTrue((proj / "README.md").exists())

    def test_create_desktop_only(self):
        proj = create_project_noninteractive("desk_app", self.tmpdir,
                                             platforms=["desktop"],
                                             backends=["rust"])
        self.assertTrue((proj / "desktop" / "main.ge.py").exists())
        self.assertFalse((proj / "web").exists())
        self.assertFalse((proj / "mobile").exists())

    def test_create_web_only(self):
        proj = create_project_noninteractive("web_app", self.tmpdir,
                                             platforms=["web"],
                                             backends=["go"])
        self.assertTrue((proj / "web" / "main.ge.py").exists())
        self.assertFalse((proj / "desktop").exists())

    def test_ge_toml_contains_backends(self):
        proj = create_project_noninteractive("config_app", self.tmpdir,
                                             platforms=["desktop"],
                                             backends=["rust", "cpp"])
        toml = (proj / "ge.toml").read_text(encoding="utf-8")
        self.assertIn("rust", toml)
        self.assertIn("cpp", toml)

    def test_ge_toml_contains_platforms(self):
        proj = create_project_noninteractive("plat_app", self.tmpdir,
                                             platforms=["desktop", "mobile"],
                                             backends=["rust"])
        toml = (proj / "ge.toml").read_text(encoding="utf-8")
        self.assertIn("desktop", toml)
        self.assertIn("mobile", toml)

    def test_app_main_has_greet(self):
        proj = create_project_noninteractive("greet_app", self.tmpdir)
        content = (proj / "app" / "main.ge.py").read_text(encoding="utf-8")
        self.assertIn("def greet", content)
        self.assertIn("def main", content)

    def test_readme_has_structure(self):
        proj = create_project_noninteractive("readme_app", self.tmpdir)
        content = (proj / "README.md").read_text(encoding="utf-8")
        self.assertIn("app/", content)
        self.assertIn("desktop/", content)
        self.assertIn("backend/", content)

    def test_directory_already_exists(self):
        create_project_noninteractive("dup_app", self.tmpdir)
        with self.assertRaises(FileExistsError):
            create_project_noninteractive("dup_app", self.tmpdir)


class TestInspectorWidget(unittest.TestCase):
    def test_inspector_components_generated(self):
        from pyeffic.dartgen import generate_main
        from pyeffic.ui import parse_ui

        ui_source = '''
def build():
    return Column([
        Text("Hello", style="fontSize:24; bold:true"),
        ElevatedButton("Click", on_click=Action(call="do_something", update="result")),
    ])
'''
        tree = parse_ui(ui_source)
        dart = generate_main(tree, [], "Test App")

        self.assertIn("GeTagged", dart)
        self.assertIn("GeInspector", dart)
        self.assertIn("GeInspectorToggle", dart)
        self.assertIn("Clipboard", dart)
        self.assertIn("services.dart", dart)

    def test_widget_refs_are_unique(self):
        from pyeffic.dartgen import generate_main
        from pyeffic.ui import parse_ui

        ui_source = '''
def build():
    return Column([
        Text("First"),
        Text("Second"),
        Text("Third"),
    ])
'''
        tree = parse_ui(ui_source)
        dart = generate_main(tree, [], "Test App")

        # Each widget should have a unique ref
        import re
        refs = re.findall(r"ref: '(ge:[^']+)'", dart)
        self.assertGreater(len(refs), 3)  # at least 4 widgets (Column + 3 Text)
        self.assertEqual(len(refs), len(set(refs)), "Refs should be unique")

    def test_inspector_toggle_is_fab(self):
        from pyeffic.dartgen import generate_main
        from pyeffic.ui import parse_ui

        ui_source = '''
def build():
    return Column([Text("Test")])
'''
        tree = parse_ui(ui_source)
        dart = generate_main(tree, [], "Test")

        self.assertIn("FloatingActionButton", dart)
        self.assertIn("GeInspectorToggle", dart)

    def test_inspector_disabled_by_default(self):
        from pyeffic.dartgen import generate_main
        from pyeffic.ui import parse_ui

        ui_source = '''
def build():
    return Column([Text("Test")])
'''
        tree = parse_ui(ui_source)
        dart = generate_main(tree, [], "Test")

        self.assertIn("isEnabled = false", dart)


class TestCreateCommand(unittest.TestCase):
    def test_create_help(self):
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        old_argv = sys.argv
        captured = StringIO()
        try:
            sys.argv = ["ge", "create", "--help"]
            sys.stdout = captured
            with self.assertRaises(SystemExit):
                main()
        finally:
            sys.argv = old_argv
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("create", output)
        self.assertIn("--platforms", output)
        self.assertIn("--backends", output)


if __name__ == "__main__":
    unittest.main()
