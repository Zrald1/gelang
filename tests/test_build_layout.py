"""Tests for the organized build output layout.

Artifacts are bucketed by platform so a multi-target project stays readable:

    build/
      desktop/  backend/  obj/  bin/
      web/      backend/  obj/  bin/
      mobile/   <app>/backend  ui  lib
"""
import tempfile
import unittest
from pathlib import Path

from pyeffic.config import Config


class TestConfigLayout(unittest.TestCase):
    def test_default_root_is_build(self):
        cfg = Config()
        self.assertEqual(str(cfg.out_dir), "build")

    def test_default_target_is_desktop(self):
        self.assertEqual(Config().target, "desktop")

    def test_target_dir(self):
        cfg = Config(target="web")
        self.assertTrue(str(cfg.target_dir).replace("\\", "/").endswith("build/web"))

    def test_out_places_files_under_target(self):
        cfg = Config()
        p = cfg.out("backend", "rust_main.rs")
        self.assertTrue(str(p).replace("\\", "/").endswith(
            "build/desktop/backend/rust_main.rs"))

    def test_bin_obj_backend_dirs(self):
        cfg = Config(target="mobile")
        for d, leaf in ((cfg.bin_dir(), "bin"),
                        (cfg.obj_dir(), "obj"),
                        (cfg.backend_dir(), "backend")):
            self.assertTrue(str(d).replace("\\", "/").endswith(f"build/mobile/{leaf}"))

    def test_out_creates_parents(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(out_dir=Path(td), target="web")
            p = cfg.out("backend", "x.rs")
            self.assertTrue(p.parent.is_dir())


class TestTargetBuckets(unittest.TestCase):
    def test_three_buckets_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dirs = {
                t: Config(out_dir=root, target=t).target_dir
                for t in ("desktop", "web", "mobile")
            }
            self.assertEqual(len(set(dirs.values())), 3)
            for name, d in dirs.items():
                self.assertTrue(str(d).replace("\\", "/").endswith(f"/{name}"))

    def test_cli_target_mapping(self):
        from pyeffic.ge_cli import _target_of

        class A:
            pass

        a = A()
        a.target = None
        self.assertEqual(_target_of(a), "desktop")
        a.target = "desktop"
        self.assertEqual(_target_of(a), "desktop")
        a.target = "web"
        self.assertEqual(_target_of(a), "web")
        a.target = "mobile"
        self.assertEqual(_target_of(a), "mobile")
        # crossplatform builds the native desktop artifact
        a.target = "crossplatform"
        self.assertEqual(_target_of(a), "desktop")


class TestBuildWritesToBucket(unittest.TestCase):
    """A real compile must place source, object and binary in the right bucket."""

    def test_desktop_build_layout(self):
        from pyeffic.config import detect_compilers
        from pyeffic.pipeline import build

        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc is required")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "m.ge.py"
            src.write_text(
                "def main() -> None:\n    print(7 * 6)\n", encoding="utf-8")
            cfg = Config(out_dir=root / "build", target="desktop",
                         do_research=False, force_backend="rust")
            report = build(src, cfg, entry="main")

            self.assertTrue(report.rust_compile and report.rust_compile.ok,
                            msg=(report.rust_compile.log[:800]
                                 if report.rust_compile else "no compile"))

            rel = str(report.rust_src.relative_to(root)).replace("\\", "/")
            self.assertEqual(rel, "build/desktop/backend/rust_main.rs")

            exe = report.rust_compile.exe
            rel_exe = str(exe.relative_to(root)).replace("\\", "/")
            self.assertEqual(rel_exe, "build/desktop/bin/rust_main.exe")

            import subprocess
            r = subprocess.run([str(exe)], capture_output=True, text=True,
                               timeout=60)
            self.assertIn("42", r.stdout)

    def test_web_bucket_is_separate(self):
        from pyeffic.config import detect_compilers
        from pyeffic.pipeline import build

        info = detect_compilers()
        if not info.rustc:
            self.skipTest("rustc is required")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "m.ge.py"
            src.write_text("def main() -> None:\n    print(1)\n", encoding="utf-8")
            cfg = Config(out_dir=root / "build", target="web",
                         do_research=False, force_backend="rust")
            report = build(src, cfg, entry="main")
            rel = str(report.rust_src.relative_to(root)).replace("\\", "/")
            self.assertEqual(rel, "build/web/backend/rust_main.rs")

    def test_mixed_build_layout(self):
        from pyeffic.config import detect_compilers
        from pyeffic.pipeline import build_native_mixed

        info = detect_compilers()
        if not (info.rustc and info.cpp):
            self.skipTest("rustc and a C++ compiler are required")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "app" / "core.ge").write_text(
                "@rust\n"
                "def twice(x: int) -> int:\n    return x * 2\n"
                "\n"
                "@cpp\n"
                "def plus_one(x: int) -> int:\n    return twice(x) + 1\n",
                encoding="utf-8")
            entry = root / "main.ge"
            entry.write_text(
                "from app.core import twice, plus_one\n"
                "\n"
                "def main() -> int:\n"
                "    print(plus_one(20))\n"
                "    return 0\n",
                encoding="utf-8")

            cfg = Config(out_dir=root / "build", target="desktop",
                         do_research=False)
            report = build_native_mixed(entry, cfg, entry="main")
            self.assertTrue(report.compile_ok, msg=report.compile_log[:800])

            for backend, p in report.srcs.items():
                rel = str(p.relative_to(root)).replace("\\", "/")
                self.assertTrue(rel.startswith("build/desktop/backend/"), rel)
            for backend, p in report.objects.items():
                rel = str(p.relative_to(root)).replace("\\", "/")
                self.assertTrue(rel.startswith("build/desktop/obj/"), rel)
            rel_exe = str(report.exe.relative_to(root)).replace("\\", "/")
            self.assertTrue(rel_exe.startswith("build/desktop/bin/"), rel_exe)


if __name__ == "__main__":
    unittest.main()
