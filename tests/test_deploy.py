"""Tests for GE deployment system — auto-detect, distribute, simulate."""
import unittest
import tempfile
import shutil
import json
from pathlib import Path
from pyeffic.deploy import (
    detect_manifest, distribute_components, simulate_deployment,
    generate_runtime_server, DeployManifest, deploy_package,
)


class TestDetectManifest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detect_backend_only(self):
        staging = self.tmpdir / "staging"
        (staging / "native" / "rust").mkdir(parents=True)
        (staging / "native" / "rust" / "libtest.dll").write_bytes(b"\x00\x01")

        class MockMeta:
            app_name = "test"
            version = "1.0"
            backend = "rust"
            ffi_exports = []

        manifest = detect_manifest(staging, MockMeta())
        self.assertTrue(manifest.has_backend)
        self.assertIn("backend", manifest.components)
        self.assertEqual(manifest.app_name, "test")

    def test_detect_mobile_component(self):
        staging = self.tmpdir / "staging"
        (staging / "dart").mkdir(parents=True)
        (staging / "dart" / "main.dart").write_text(
            "import 'package:flutter/material.dart';\nvoid main() => runApp(MyApp());",
            encoding="utf-8")

        class MockMeta:
            app_name = "test"
            version = "1.0"
            backend = "rust"
            ffi_exports = []

        manifest = detect_manifest(staging, MockMeta())
        self.assertTrue(manifest.has_mobile)
        self.assertIn("mobile", manifest.components)

    def test_detect_empty_package(self):
        staging = self.tmpdir / "staging"
        staging.mkdir()

        class MockMeta:
            app_name = "empty"
            version = "0.1"
            backend = "rust"
            ffi_exports = []

        manifest = detect_manifest(staging, MockMeta())
        self.assertFalse(manifest.has_backend)
        self.assertFalse(manifest.has_web)
        self.assertFalse(manifest.has_mobile)


class TestDistributeComponents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_distribute_creates_dirs(self):
        staging = self.tmpdir / "staging"
        deploy = self.tmpdir / "deploy"
        (staging / "native" / "rust").mkdir(parents=True)
        (staging / "native" / "rust" / "libtest.dll").write_bytes(b"\x00")
        (staging / "dart").mkdir(parents=True)
        (staging / "dart" / "main.dart").write_text("// dart", encoding="utf-8")

        manifest = DeployManifest(
            app_name="test", version="1.0", backend="rust",
            components=["backend", "mobile"],
            has_backend=True, has_mobile=True,
            native_libs={"rust": "libtest.dll"},
            dart_files=["main.dart"],
        )
        deployed = distribute_components(staging, deploy, manifest)
        self.assertTrue((deploy / "backend").exists())
        self.assertTrue((deploy / "mobile").exists())
        self.assertTrue((deploy / "manifest.json").exists())

    def test_manifest_json_written(self):
        staging = self.tmpdir / "staging"
        deploy = self.tmpdir / "deploy"
        staging.mkdir()

        manifest = DeployManifest(app_name="test", version="1.0", backend="rust")
        distribute_components(staging, deploy, manifest)
        manifest_path = deploy / "manifest.json"
        self.assertTrue(manifest_path.exists())
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["app_name"], "test")


class TestSimulateDeployment(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_simulation_passes_with_valid_package(self):
        staging = self.tmpdir / "staging"
        deploy = self.tmpdir / "deploy"
        (staging / "native" / "rust").mkdir(parents=True)
        (staging / "native" / "rust" / "libtest.dll").write_bytes(b"\x00\x01\x02")
        (staging / "dart").mkdir(parents=True)
        (staging / "dart" / "main.dart").write_text("void main() {}", encoding="utf-8")

        manifest = DeployManifest(
            app_name="test", version="1.0", backend="rust",
            components=["backend", "mobile"],
            has_backend=True, has_mobile=True,
            native_libs={"rust": "libtest.dll"},
            dart_files=["main.dart"],
            ffi_exports=["fn1"],
        )
        distribute_components(staging, deploy, manifest)
        ok, results = simulate_deployment(staging, deploy, manifest)
        self.assertTrue(ok)
        # All results should be PASS
        for r in results:
            self.assertIn("PASS", r)

    def test_simulation_fails_with_missing_backend(self):
        staging = self.tmpdir / "staging"
        deploy = self.tmpdir / "deploy"
        staging.mkdir()

        manifest = DeployManifest(
            app_name="test", version="1.0", backend="rust",
            has_backend=True,  # claims backend but none exists
        )
        deploy.mkdir()
        ok, results = simulate_deployment(staging, deploy, manifest)
        self.assertFalse(ok)

    def test_simulation_checks_ffi_exports(self):
        staging = self.tmpdir / "staging"
        deploy = self.tmpdir / "deploy"
        (staging / "native" / "rust").mkdir(parents=True)
        (staging / "native" / "rust" / "libtest.dll").write_bytes(b"\x00")

        manifest = DeployManifest(
            app_name="test", version="1.0", backend="rust",
            has_backend=True,
            native_libs={"rust": "libtest.dll"},
            ffi_exports=["compute_sum", "compute_product"],
        )
        distribute_components(staging, deploy, manifest)
        ok, results = simulate_deployment(staging, deploy, manifest)
        self.assertTrue(ok)
        ffi_results = [r for r in results if "FFI export '" in r]
        self.assertEqual(len(ffi_results), 2)


class TestRuntimeServer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_server_generated(self):
        manifest = DeployManifest(
            app_name="myapp", version="1.0", backend="rust",
            components=["backend", "web"],
            has_web=True, has_backend=True,
            native_libs={"rust": "libmyapp.dll"},
            ffi_exports=["compute"],
            port=9090,
        )
        server_path = generate_runtime_server(manifest, self.tmpdir)
        self.assertTrue(server_path.exists())
        content = server_path.read_text(encoding="utf-8")
        self.assertIn("myapp", content)
        self.assertIn("9090", content)
        self.assertIn("compute", content)
        self.assertIn("HTTPServer", content)

    def test_server_is_valid_python(self):
        manifest = DeployManifest(
            app_name="test", version="1.0", has_web=True, port=8080,
        )
        server_path = generate_runtime_server(manifest, self.tmpdir)
        # Verify it's valid Python by compiling it
        import py_compile
        py_compile.compile(str(server_path), doraise=True)


class TestDeployPackage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deploy_nonexistent_package(self):
        ok, msg = deploy_package(
            Path("nonexistent.ge"), self.tmpdir / "deploy",
            simulate_only=True)
        self.assertFalse(ok)
        self.assertIn("not found", msg)


class TestDeployCommand(unittest.TestCase):
    def test_deploy_help(self):
        import sys
        from io import StringIO
        from pyeffic.ge_cli import main

        old_argv = sys.argv
        captured = StringIO()
        sys.stdout = captured
        try:
            sys.argv = ["ge", "deploy", "--help"]
            with self.assertRaises(SystemExit):
                main()
        finally:
            sys.argv = old_argv
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("deploy", output)
        self.assertIn("--target", output)
        self.assertIn("simulate", output)


if __name__ == "__main__":
    unittest.main()
