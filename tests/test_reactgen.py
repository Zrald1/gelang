"""Tests for the React + TypeScript UI generator (reactgen)."""
import json
import tempfile
import unittest
from pathlib import Path

from pyeffic.reactgen import (
    _camel,
    _map_dsl_color,
    _style_to_react,
    generate_react_app,
    widget_to_jsx,
    write_react_app,
)
from pyeffic.ui_dsl import WidgetNode, parse_ui_dsl

SAMPLE_UI = '''Window {
  title: "Demo App"
  Column {
    padding: 16
    children:
      Text "Hello" style="headline"
      Text state="count" style="value"
      SizedBox height=12
      TextField state="query" hint="type here"
      ElevatedButton "Run" on_click=Action(call="compute_total_rent")
      Divider
  }
}
'''


class TestHelpers(unittest.TestCase):
    def test_camel(self):
        self.assertEqual(_camel("api_base_url"), "apiBaseUrl")
        self.assertEqual(_camel("count"), "count")

    def test_color_shades(self):
        self.assertEqual(_map_dsl_color("grey700"), "#334155")
        self.assertEqual(_map_dsl_color("blue500"), "#3b82f6")
        self.assertEqual(_map_dsl_color("red"), "var(--ge-danger)")

    def test_color_passthrough(self):
        self.assertEqual(_map_dsl_color("#ff0000"), "#ff0000")
        self.assertEqual(_map_dsl_color("rgb(1,2,3)"), "rgb(1,2,3)")

    def test_style_to_react_named(self):
        s = _style_to_react({}, "headline")
        self.assertIn("fontSize", s)
        self.assertIn("fontWeight", s)

    def test_style_to_react_bold(self):
        s = _style_to_react({"bold": True, "color": "blue500"}, None)
        self.assertIn('fontWeight: "700"', s)
        self.assertIn('color: "#3b82f6"', s)

    def test_style_empty_is_undefined(self):
        self.assertEqual(_style_to_react({}, None), "undefined")


class TestWidgetToJsx(unittest.TestCase):
    def test_text_literal(self):
        jsx = widget_to_jsx(WidgetNode(kind="Text", text="Hi"), 0)
        self.assertIn('<GeText text="Hi"', jsx)

    def test_text_state_binding(self):
        jsx = widget_to_jsx(WidgetNode(kind="Text", state="node_count"), 0)
        self.assertIn("nodeCount", jsx)

    def test_button_with_action(self):
        node = WidgetNode(kind="Button", label="Go")
        node.action = {"call": "compute_total_rent"}
        jsx = widget_to_jsx(node, 0)
        self.assertIn('label="Go"', jsx)
        self.assertIn('run("compute_total_rent")', jsx)

    def test_column_children(self):
        col = WidgetNode(kind="Column", children=[
            WidgetNode(kind="Text", text="a"),
            WidgetNode(kind="Text", text="b"),
        ])
        jsx = widget_to_jsx(col, 0)
        self.assertIn("<GeColumn", jsx)
        self.assertIn("</GeColumn>", jsx)
        self.assertIn('text="a"', jsx)
        self.assertIn('text="b"', jsx)

    def test_row(self):
        jsx = widget_to_jsx(WidgetNode(kind="Row"), 0)
        self.assertIn("<GeRow", jsx)

    def test_sized_box(self):
        node = WidgetNode(kind="SizedBox")
        node.props["height"] = 12
        jsx = widget_to_jsx(node, 0)
        self.assertIn("height={12}", jsx)

    def test_divider(self):
        self.assertIn("<GeDivider", widget_to_jsx(WidgetNode(kind="Divider"), 0))

    def test_text_field(self):
        node = WidgetNode(kind="TextField", state="query")
        jsx = widget_to_jsx(node, 0)
        self.assertIn("GeTextField", jsx)
        self.assertIn("setQuery", jsx)

    def test_unknown_kind_is_marked(self):
        jsx = widget_to_jsx(WidgetNode(kind="UnknownThing"), 0)
        self.assertIn("unsupported", jsx)


class TestGenerateApp(unittest.TestCase):
    def setUp(self):
        self.screen = parse_ui_dsl(SAMPLE_UI)
        self.files = generate_react_app(self.screen, "DemoApp")

    def test_expected_files(self):
        for rel in [
            "index.html", "package.json", "vite.config.ts", "tsconfig.json",
            "src/main.tsx", "src/App.tsx", "src/styles.css",
            "src/api/client.ts", "src/api/types.ts", "src/vite-env.d.ts",
        ]:
            self.assertIn(rel, self.files, rel)

    def test_component_per_file(self):
        for name in ["GeText", "GeButton", "GeColumn", "GeRow",
                     "GeContainer", "GeSizedBox", "GeDivider", "GeTextField"]:
            self.assertIn(f"src/components/{name}.tsx", self.files)

    def test_package_json_is_valid(self):
        pkg = json.loads(self.files["package.json"])
        self.assertEqual(pkg["name"], "demoapp")
        self.assertIn("react", pkg["dependencies"])
        self.assertIn("vite", pkg["devDependencies"])
        self.assertIn("typescript", pkg["devDependencies"])

    def test_tsconfig_is_valid(self):
        cfg = json.loads(self.files["tsconfig.json"])
        self.assertTrue(cfg["compilerOptions"]["strict"])
        self.assertEqual(cfg["compilerOptions"]["jsx"], "react-jsx")

    def test_app_uses_state_types(self):
        app = self.files["src/App.tsx"]
        # count is numeric, query is a text field so it becomes a string
        self.assertIn("useState<number>(0)", app)
        self.assertIn('useState<string>("")', app)

    def test_app_renders_tree(self):
        app = self.files["src/App.tsx"]
        self.assertIn('text="Hello"', app)
        self.assertIn("GeButton", app)
        self.assertIn('label="Run"', app)

    def test_app_title_from_dsl(self):
        self.assertIn("Demo App", self.files["src/App.tsx"])

    def test_only_used_components_imported(self):
        app = self.files["src/App.tsx"]
        self.assertIn("GeTextField", app)
        # the sample has no Row, so it must not be imported
        self.assertNotIn('import { GeRow }', app)

    def test_vite_proxy_points_at_backend(self):
        cfg = self.files["vite.config.ts"]
        self.assertIn("/api", cfg)
        self.assertIn("8080", cfg)

    def test_ffi_functions_listed(self):
        from pyeffic.analyzer import FuncUnit
        u = FuncUnit(name="add", params=[("a", "int"), ("b", "int")],
                     ret_type="int", body=[], lineno=1, supported=True)
        files = generate_react_app(self.screen, "DemoApp", ffi_units=[u])
        types = files["src/api/types.ts"]
        self.assertIn('"add"', types)
        # with backend functions present the client is imported and used
        self.assertIn("callFunction", files["src/App.tsx"])


class TestWriteApp(unittest.TestCase):
    def test_write_and_no_clobber(self):
        screen = parse_ui_dsl(SAMPLE_UI)
        files = generate_react_app(screen, "DemoApp")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            written = write_react_app(files, root)
            self.assertTrue(written)
            self.assertTrue((root / "src" / "App.tsx").exists())

            # hand-edit then re-run without force: edit must survive
            (root / "src" / "App.tsx").write_text("// my edit\n", encoding="utf-8")
            written2 = write_react_app(files, root)
            self.assertNotIn("src/App.tsx", written2)
            self.assertEqual((root / "src" / "App.tsx").read_text(), "// my edit\n")

            # force overwrites
            written3 = write_react_app(files, root, force=True)
            self.assertIn("src/App.tsx", written3)

    def test_app_name_sanitised(self):
        screen = parse_ui_dsl(SAMPLE_UI)
        files = generate_react_app(screen, "My_Cool_App")
        pkg = json.loads(files["package.json"])
        self.assertEqual(pkg["name"], "my-cool-app")


class TestUiDslCompatibility(unittest.TestCase):
    def test_screen_form_still_parses(self):
        src = 'Screen "Old Style" {\n  Column {\n    children:\n      Text "hi"\n  }\n}\n'
        s = parse_ui_dsl(src)
        self.assertEqual(s.title, "Old Style")
        self.assertEqual(s.root.kind, "Column")

    def test_window_form_parses(self):
        s = parse_ui_dsl('Window {\n  title: "New Style"\n  Column {\n    children:\n      Text "hi"\n  }\n}\n')
        self.assertEqual(s.title, "New Style")

    def test_docstring_skipped(self):
        src = '"""docstring"""\nWindow {\n  title: "Doc"\n  Column {}\n}\n'
        s = parse_ui_dsl(src)
        self.assertEqual(s.title, "Doc")


if __name__ == "__main__":
    unittest.main()
