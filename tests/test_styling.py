"""Test the styling parser: CSS-like style strings → target-neutral dicts."""
import unittest
from pyeffic.styling import parse_style, style_to_flutter_text, style_to_flutter_padding


class TestStyling(unittest.TestCase):
    def test_parse_basic(self):
        sd = parse_style("fontSize:20; bold:true; color:#1565C0")
        self.assertEqual(sd.get("fontSize"), 20)
        self.assertEqual(sd.get("bold"), True)
        self.assertEqual(sd.get("color"), "#1565C0")

    def test_parse_named_color(self):
        sd = parse_style("color:blue")
        self.assertEqual(sd.get("color"), "blue")

    def test_parse_shade_color(self):
        sd = parse_style("color:grey600")
        self.assertEqual(sd.get("color"), "grey600")

    def test_parse_padding(self):
        sd = parse_style("padding:16")
        self.assertEqual(sd.get("padding"), 16)

    def test_parse_border(self):
        sd = parse_style("border:2,#A5D6A7")
        self.assertIn("border", sd)

    def test_parse_radius(self):
        sd = parse_style("radius:10")
        self.assertEqual(sd.get("radius"), 10)

    def test_named_style_headline(self):
        sd = parse_style("headline")
        self.assertIsNotNone(sd)

    def test_named_style_with_override(self):
        sd = parse_style("headline; color:red")
        self.assertIsNotNone(sd)
        self.assertEqual(sd.get("color"), "red")

    def test_flutter_text_style(self):
        sd = parse_style("fontSize:20; bold:true; color:#1565C0")
        result = style_to_flutter_text(sd)
        self.assertIn("fontSize: 20", result)
        self.assertIn("FontWeight.bold", result)

    def test_flutter_padding(self):
        sd = parse_style("padding:16")
        result = style_to_flutter_padding(sd)
        self.assertIn("16", result)


if __name__ == "__main__":
    unittest.main()
