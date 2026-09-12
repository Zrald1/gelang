"""Tests for GE toolchain downloader, analyze, and unified build."""
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestDownloader(unittest.TestCase):
    def test_get_platform_key(self):
        from pyeffic.downloader import _get_platform_key
        key = _get_platform_key()
        self.assertIn("-", key)
        parts = key.split("-")
        self.assertGreaterEqual(len(parts), 2)

    def test_get_tools_dir(self):
        from pyeffic.downloader import get_tools_dir
        d = get_tools_dir()
        self.assertTrue(d.exists())
        self.assertIn(".ge", str(d))

    def test_is_toolchain_available_returns_bool(self):
        from pyeffic.downloader import is_toolchain_available
        result = is_toolchain_available("nonexistent_toolchain_xyz")
        self.assertFalse(result)

    def test_download_urls_exist(self):
        from pyeffic.downloader import DOWNLOAD_URLS
        self.assertIn("rust", DOWNLOAD_URLS)
        self.assertIn("go", DOWNLOAD_URLS)
        self.assertIn("zig", DOWNLOAD_URLS)
        for name, urls in DOWNLOAD_URLS.items():
            for plat, url in urls.items():
                self.assertTrue(url.startswith("https://"), f"{name} URL should be HTTPS")

    def test_get_tools_status(self):
        from pyeffic.downloader import get_tools_status
        status = get_tools_status()
        for name in ["rust", "cpp", "csharp", "zig", "go", "kotlin", "dart"]:
            self.assertIn(name, status)
            self.assertIn("available", status[name])
            self.assertIn("downloadable", status[name])


class TestAnalyzeCommand(unittest.TestCase):
    def test_analyze_clean_source(self):
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        source = '''
def greet(name: str) -> str:
    return "Hello"

def main() -> None:
    print(greet("World"))
'''
        tmpdir = Path(tempfile.mkdtemp())
        try:
            src = tmpdir / "test.ge.py"
            src.write_text(source, encoding="utf-8")
            old_argv = sys.argv
            captured = StringIO()
            sys.stdout = captured
            try:
                sys.argv = ["ge", "analyze", str(src)]
                rc = main()
            finally:
                sys.argv = old_argv
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("No issues found", output)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_analyze_type_error(self):
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        source = '''
def main() -> None:
    x: str = 5
'''
        tmpdir = Path(tempfile.mkdtemp())
        try:
            src = tmpdir / "test.ge.py"
            src.write_text(source, encoding="utf-8")
            old_argv = sys.argv
            captured = StringIO()
            sys.stdout = captured
            try:
                sys.argv = ["ge", "analyze", str(src)]
                rc = main()
            finally:
                sys.argv = old_argv
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertEqual(rc, 1)
            self.assertIn("ERROR", output)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_analyze_skips_build_function(self):
        """The build() function uses UI widgets and should not be type-checked."""
        from pyeffic.typecheck import check_source
        source = '''
def build():
    return Column([Text("Hello")])

def main() -> None:
    print("ok")
'''
        reporter = check_source(source, file="test.ge.py", entry="main")
        errors = [d for d in reporter.diagnostics if d.severity == "error"]
        # Should not have errors about undefined Column/Text
        ui_errors = [e for e in errors if "Column" in e.message or "Text" in e.message]
        self.assertEqual(len(ui_errors), 0)


class TestBuildTarget(unittest.TestCase):
    def test_build_desktop_target(self):
        """Test that --target desktop routes to native build."""
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        source = '''
def main() -> None:
    print(42)
'''
        tmpdir = Path(tempfile.mkdtemp())
        try:
            src = tmpdir / "test.ge.py"
            src.write_text(source, encoding="utf-8")
            old_argv = sys.argv
            captured = StringIO()
            sys.stdout = captured
            try:
                sys.argv = ["ge", "build", str(src), "--target", "desktop",
                           "-o", str(tmpdir / "out"), "--no-research"]
                rc = main()
            finally:
                sys.argv = old_argv
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("GE build", output)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestToolsCommand(unittest.TestCase):
    def test_tools_list(self):
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        old_argv = sys.argv
        captured = StringIO()
        sys.stdout = captured
        try:
            sys.argv = ["ge", "tools", "list"]
            rc = main()
        finally:
            sys.argv = old_argv
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Toolchain", output)
        self.assertIn("rust", output)
        self.assertIn("zig", output)
        self.assertIn("go", output)

    def test_tools_check(self):
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        old_argv = sys.argv
        captured = StringIO()
        sys.stdout = captured
        try:
            sys.argv = ["ge", "tools", "check"]
            rc = main()
        finally:
            sys.argv = old_argv
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        # rc is 0 if all OK, 1 if some missing
        self.assertIn(rc, (0, 1))
        self.assertIn("rust", output)


if __name__ == "__main__":
    unittest.main()
