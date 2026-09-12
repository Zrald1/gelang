"""Test the UI parser: widget DSL → tree dict."""
import unittest
from pyeffic.ui import parse_ui, collect_state


class TestUIParser(unittest.TestCase):
    def test_simple_column(self):
        tree = parse_ui("""
def build():
    return Column([
        Text("Hello"),
        Text("World"),
    ])
""")
        self.assertEqual(tree["kind"], "Column")
        self.assertEqual(len(tree["children"]), 2)
        self.assertEqual(tree["children"][0]["kind"], "Text")
        self.assertEqual(tree["children"][0]["text"], "Hello")

    def test_text_with_style(self):
        tree = parse_ui("""
def build():
    return Column([
        Text("Title", style="fontSize:20; bold:true"),
    ])
""")
        child = tree["children"][0]
        self.assertEqual(child["text"], "Title")
        self.assertIn("style_dict", child)

    def test_state_text(self):
        tree = parse_ui("""
def build():
    return Column([
        Text(state="counter"),
    ])
""")
        child = tree["children"][0]
        self.assertEqual(child.get("state"), "counter")

    def test_nested_containers(self):
        tree = parse_ui("""
def build():
    return Column([
        Container(
            Column([
                Text("Nested"),
            ]),
            style="padding:16",
        ),
    ])
""")
        child = tree["children"][0]
        self.assertEqual(child["kind"], "Container")
        self.assertEqual(child["child"]["kind"], "Column")

    def test_row_with_expanded(self):
        tree = parse_ui("""
def build():
    return Row([
        Expanded(child=Text("Left")),
        Expanded(child=Text("Right")),
    ])
""")
        self.assertEqual(tree["kind"], "Row")
        self.assertEqual(len(tree["children"]), 2)
        self.assertEqual(tree["children"][0]["kind"], "Expanded")

    def test_button_with_action(self):
        tree = parse_ui("""
def build():
    return Column([
        ElevatedButton("Click", on_click=Action(call="compute", args=[], update="result")),
    ])
""")
        child = tree["children"][0]
        self.assertEqual(child["kind"], "Button")
        self.assertEqual(child["label"], "Click")

    def test_collect_state(self):
        tree = parse_ui("""
def build():
    return Column([
        Text(state="total"),
        Text(state="paid"),
        Text("static"),
    ])
""")
        states = collect_state(tree)
        self.assertIn("total", states)
        self.assertIn("paid", states)
        self.assertNotIn("static", states)

    def test_sized_box(self):
        tree = parse_ui("""
def build():
    return Column([
        SizedBox(height=20),
        Text("After gap"),
    ])
""")
        child = tree["children"][0]
        self.assertEqual(child["kind"], "SizedBox")
        self.assertEqual(child.get("height"), 20)

    def test_divider(self):
        tree = parse_ui("""
def build():
    return Column([
        Text("Above"),
        Divider(),
        Text("Below"),
    ])
""")
        self.assertEqual(tree["children"][1]["kind"], "Divider")


if __name__ == "__main__":
    unittest.main()
