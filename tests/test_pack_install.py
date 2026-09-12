"""Test the .ge package pack/install round-trip."""
import unittest
import tempfile
import shutil
from pathlib import Path
from pyeffic.config import Config, detect_compilers
from pyeffic.pipeline import build_flutter
from pyeffic.packer import pack_ge, unpack_ge, PackageMeta


class TestPackInstall(unittest.TestCase):
    """Test .ge package creation and unpacking."""

    @classmethod
    def setUpClass(cls):
        cls.info = detect_compilers()
        cls.has_rust = cls.info.rustc is not None

    def _create_test_source(self) -> str:
        return """
from pyeffic.widgets import Text, Column, ElevatedButton, Action

def compute() -> int:
    return 42

def main() -> None:
    print(compute())

def build():
    return Column([
        Text("Test App"),
        ElevatedButton("Click", on_click=Action(call="compute", args=[], update="result")),
    ])
"""

    def test_pack_unpack_roundtrip(self):
        if not self.has_rust:
            self.skipTest("rustc not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "test.ge.py"
            src.write_text(self._create_test_source(), encoding="utf-8")

            # build flutter artifacts
            cfg = Config(out_dir=tmpdir / "build", do_research=False)
            report = build_flutter(src, cfg, app_name="test_app", lib_basename="ge_logic")

            if not report.lib_binary:
                self.skipTest("native lib compilation failed")

            # pack
            meta = PackageMeta(
                name="test_app",
                version="0.1.0",
                app_name="test_app",
                lib_name="ge_logic",
                backend=report.backend,
                ffi_exports=report.ffi_exports,
                targets=["windows"],
            )

            artifacts = {}
            if report.lib_src:
                artifacts["native/ge_logic.rs"] = report.lib_src
            if report.lib_binary:
                artifacts["native/ge_logic.dll"] = report.lib_binary
            if report.bindings_dart:
                artifacts["dart/bindings.dart"] = report.bindings_dart
            if report.main_dart:
                artifacts["dart/main.dart"] = report.main_dart
            if report.pubspec:
                artifacts["dart/pubspec.yaml"] = report.pubspec

            ge_file = tmpdir / "test_app.ge"
            pack_ge(src, meta, artifacts, ge_file, minify=False)

            # verify package exists
            self.assertTrue(ge_file.exists())
            self.assertGreater(ge_file.stat().st_size, 1000)

            # unpack
            staging = tmpdir / "unpacked"
            result_meta = unpack_ge(ge_file, staging)

            # verify files exist
            self.assertTrue((staging / "package.json").exists())
            self.assertTrue((staging / "native" / "ge_logic.rs").exists())
            self.assertTrue((staging / "dart" / "main.dart").exists())

    def test_package_metadata(self):
        meta = PackageMeta(
            name="test",
            version="1.0.0",
            app_name="test",
            lib_name="ge_logic",
            backend="rust",
            ffi_exports=["compute"],
            targets=["windows", "android"],
        )
        self.assertEqual(meta.name, "test")
        self.assertEqual(meta.version, "1.0.0")
        self.assertIn("windows", meta.targets)
        self.assertIn("android", meta.targets)


if __name__ == "__main__":
    unittest.main()
