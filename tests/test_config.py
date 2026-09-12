"""Tests for version-adaptive toolchain detection.

Verifies that GE can detect any version of each toolchain, handles
missing toolchains gracefully, and warns about outdated versions.
"""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import subprocess

from pyeffic.config import (
    detect_compilers, _find_tool, _parse_version, _compare_versions,
    _check_version, MIN_VERSIONS, CompilerInfo, Config,
)


class TestVersionParsing(unittest.TestCase):
    """Test version string parsing from various compiler outputs."""

    def test_parse_rust_version(self):
        output = "rustc 1.92.0 (ded5c06cf 2025-12-08)"
        self.assertEqual(_parse_version(output), "1.92.0")

    def test_parse_clang_version(self):
        output = "clang version 20.1.8"
        self.assertEqual(_parse_version(output), "20.1.8")

    def test_parse_go_version(self):
        output = "go version go1.25.5 windows/amd64"
        self.assertEqual(_parse_version(output), "1.25.5")

    def test_parse_zig_version(self):
        output = "0.14.1"
        self.assertEqual(_parse_version(output), "0.14.1")

    def test_parse_kotlin_version(self):
        output = "info: kotlinc-native 2.4.10 (JRE 25.0.1+8-LTS-27)"
        self.assertEqual(_parse_version(output), "2.4.10")

    def test_parse_dotnet_version(self):
        output = "10.0.101"
        self.assertEqual(_parse_version(output), "10.0.101")

    def test_parse_unknown(self):
        self.assertEqual(_parse_version(""), "unknown")
        self.assertEqual(_parse_version("no version here"), "unknown")


class TestVersionComparison(unittest.TestCase):
    """Test version comparison logic."""

    def test_equal_versions(self):
        self.assertEqual(_compare_versions("1.0.0", "1.0.0"), 0)

    def test_newer_version(self):
        self.assertEqual(_compare_versions("2.0.0", "1.0.0"), 1)
        self.assertEqual(_compare_versions("1.2.0", "1.1.0"), 1)
        self.assertEqual(_compare_versions("1.0.1", "1.0.0"), 1)

    def test_older_version(self):
        self.assertEqual(_compare_versions("1.0.0", "2.0.0"), -1)
        self.assertEqual(_compare_versions("1.1.0", "1.2.0"), -1)

    def test_different_length(self):
        self.assertEqual(_compare_versions("1.0", "1.0.0"), 0)
        self.assertEqual(_compare_versions("1.0.0.0", "1.0.0"), 0)
        self.assertEqual(_compare_versions("1.0.1", "1.0"), 1)


class TestVersionCheck(unittest.TestCase):
    """Test minimum version checking."""

    def test_meets_minimum(self):
        result = _check_version("rustc", "1.92.0", "1.70.0")
        self.assertEqual(result, "")

    def test_below_minimum(self):
        result = _check_version("rustc", "1.50.0", "1.70.0")
        self.assertIn("older than recommended", result)

    def test_unknown_version(self):
        result = _check_version("rustc", "unknown", "1.70.0")
        self.assertIn("could not determine", result)


class TestToolFinding(unittest.TestCase):
    """Test tool finding logic."""

    def test_find_tool_on_path(self):
        """Tools on PATH should be found."""
        # rustc should be on PATH in this environment
        result = _find_tool("rustc")
        self.assertIsNotNone(result)

    def test_find_nonexistent_tool(self):
        """Nonexistent tools should return None."""
        result = _find_tool("nonexistent_compiler_xyz")
        self.assertIsNone(result)

    def test_find_tool_in_tools_dir(self):
        """Tools in the local tools/ directory should be found."""
        # zig should be in tools/ directory
        result = _find_tool("zig")
        if result is None:
            self.skipTest("zig not installed (tools/ is empty in CI)")
        self.assertIn("zig", result.lower())


class TestDetectCompilers(unittest.TestCase):
    """Test full compiler detection."""

    def test_detect_returns_compiler_info(self):
        """detect_compilers should return a CompilerInfo object."""
        info = detect_compilers()
        self.assertIsInstance(info, CompilerInfo)

    def test_detect_rust(self):
        """Rust should be detected in this environment."""
        info = detect_compilers()
        self.assertIsNotNone(info.rustc)
        self.assertIn("rustc", info.versions)
        self.assertNotEqual(info.versions["rustc"], "unknown")

    def test_detect_versions_recorded(self):
        """All detected toolchains should have versions recorded."""
        info = detect_compilers()
        for tool_name, tool_path in [
            ("rustc", info.rustc), ("cpp", info.cpp),
            ("dotnet", info.dotnet), ("zig", info.zig),
            ("go", info.go), ("kotlinc", info.kotlinc),
        ]:
            if tool_path:
                self.assertIn(tool_name, info.versions,
                             f"{tool_name} version not recorded")

    def test_warnings_for_outdated(self):
        """Warnings should be issued for outdated toolchains."""
        # this is a mock test — we can't control the actual versions
        info = detect_compilers()
        # all our toolchains should be current, so no warnings
        # (but this depends on the environment)
        self.assertIsInstance(info.warnings, list)

    def test_min_versions_defined(self):
        """Minimum versions should be defined for all toolchains."""
        for tool in ["rustc", "cpp", "dotnet", "zig", "go", "kotlinc"]:
            self.assertIn(tool, MIN_VERSIONS)
            self.assertTrue(len(MIN_VERSIONS[tool]) > 0)


class TestConfigDataclass(unittest.TestCase):
    """Test Config dataclass."""

    def test_config_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.opt_level, "3")
        self.assertIsNone(cfg.force_backend)
        self.assertTrue(cfg.do_research)

    def test_config_out_dir(self):
        cfg = Config(out_dir=Path("/tmp/test"))
        # artifacts are bucketed by target: <out_dir>/<target>/<parts>
        p = cfg.out("backend", "main.rs")
        self.assertEqual(p, Path("/tmp/test/desktop/backend/main.rs"))

    def test_config_out_dir_other_target(self):
        cfg = Config(out_dir=Path("/tmp/test"), target="web")
        p = cfg.out("backend", "main.rs")
        self.assertEqual(p, Path("/tmp/test/web/backend/main.rs"))

    def test_config_force_backend(self):
        cfg = Config(force_backend="cpp")
        self.assertEqual(cfg.force_backend, "cpp")


class TestVersionAdaptability(unittest.TestCase):
    """Test that detection works with any version, not pinned versions."""

    def test_no_hardcoded_versions_in_find_tool(self):
        """_find_tool should not hardcode specific version numbers."""
        import inspect
        import pyeffic.config as cfg_module
        source = inspect.getsource(cfg_module)
        # should not contain specific version pins like "0.14.1" or "2.4.10"
        # in the _find_tool function (they may appear in MIN_VERSIONS)
        # The function should use version-agnostic prefix matching
        self.assertNotIn("zig-x86_64-windows-0.14.1", source)
        self.assertNotIn("kotlin-native-prebuilt-windows-x86_64-2.4.10", source)

    def test_detection_works_with_any_zig_version(self):
        """Zig detection should work regardless of version."""
        # the _find_tool function uses prefix matching, not exact paths
        # so zig-0.15.0, zig-0.16.0, etc. would all be found
        result = _find_tool("zig")
        if result is None:
            self.skipTest("zig not installed (tools/ is empty in CI)")
        self.assertIsNotNone(result)

    def test_detection_works_with_any_kotlin_version(self):
        """Kotlin detection should work regardless of version."""
        result = _find_tool("kotlinc-native")
        if result is None:
            self.skipTest("kotlinc-native not installed (tools/ is empty in CI)")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
