"""Tests for the differential test harness.

The harness proves a checkable property: the same program produces the same
output under CPython and under every native backend. It found two real bugs
during development (the Go output path), which is the point.
"""
import tempfile
import unittest
from pathlib import Path

from pyeffic.difftest import (
    DiffReport,
    RunResult,
    _directives,
    available_backends,
    diff_corpus,
    diff_one,
    find_cases,
    run_backend,
    run_reference,
)

CORPUS = Path(__file__).parent / "differential"


class TestDirectives(unittest.TestCase):
    def test_single_expect(self):
        d = _directives("# @expect: 42\ndef main() -> None:\n    pass\n")
        self.assertEqual(d["expect"], "42")

    def test_multiple_expects_accumulate(self):
        d = _directives("# @expect: 1\n# @expect: 2\n# @expect: 3\n")
        self.assertEqual(d["expect"], "1\n2\n3")

    def test_skip_and_only(self):
        d = _directives("// @skip: cpp\n// @only: rust,go\n")
        self.assertEqual(d["skip"], "cpp")
        self.assertEqual(d["only"], "rust,go")

    def test_no_directives(self):
        self.assertEqual(_directives("def main() -> None:\n    pass\n"), {})


class TestReferenceLane(unittest.TestCase):
    def test_runs_plain_program(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.ge.py"
            p.write_text("def main() -> None:\n    print(7 * 6)\n",
                         encoding="utf-8")
            r = run_reference(p)
            self.assertTrue(r.ok, r.note)
            self.assertEqual(r.normalised, "42")

    def test_runs_hybrid_program(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.ge"
            p.write_text(
                "<double>\n"
                "def double(x: int) -> int:\n    return x * 2\n"
                "</double>\n"
                "\n"
                "def main() -> None:\n"
                "    print(@double(21))\n",
                encoding="utf-8")
            r = run_reference(p)
            self.assertTrue(r.ok, r.note)
            self.assertEqual(r.normalised, "42")

    def test_intrinsics_are_stubbed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.ge.py"
            p.write_text(
                "ge_preamble('cpp', '// raw')\n"
                "\n"
                "def main() -> None:\n"
                "    print(1)\n",
                encoding="utf-8")
            r = run_reference(p)
            self.assertTrue(r.ok, r.note)
            self.assertEqual(r.normalised, "1")

    def test_backend_decorators_are_stubbed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.ge.py"
            p.write_text(
                "from pyeffic.backends import cpp, rust\n"
                "\n"
                "@rust\n"
                "def helper(x: int) -> int:\n    return x + 1\n"
                "\n"
                "def main() -> None:\n"
                "    print(helper(41))\n",
                encoding="utf-8")
            r = run_reference(p)
            self.assertTrue(r.ok, r.note)
            self.assertEqual(r.normalised, "42")

    def test_runtime_error_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.ge.py"
            p.write_text("def main() -> None:\n    raise ValueError('x')\n",
                         encoding="utf-8")
            r = run_reference(p)
            self.assertFalse(r.ok)
            self.assertIn("runtime error", r.note)


class TestReportSemantics(unittest.TestCase):
    def _report(self, expected: str, actual: str) -> DiffReport:
        rep = DiffReport(source=Path("x.ge"))
        rep.reference = RunResult("python", True, stdout=expected)
        rep.results["rust"] = RunResult("rust", True, stdout=actual)
        return rep

    def test_agreement_passes(self):
        self.assertTrue(self._report("42", "42").passed)
        self.assertEqual(self._report("42", "42").mismatches, {})

    def test_disagreement_fails(self):
        rep = self._report("42", "43")
        self.assertFalse(rep.passed)
        self.assertIn("rust", rep.mismatches)
        self.assertIn("42", rep.mismatches["rust"])

    def test_trailing_whitespace_ignored(self):
        self.assertTrue(self._report("42", "42  \n").passed)

    def test_failed_backend_is_a_mismatch(self):
        rep = DiffReport(source=Path("x.ge"))
        rep.reference = RunResult("python", True, stdout="1")
        rep.results["go"] = RunResult("go", False, note="no executable produced")
        self.assertFalse(rep.passed)
        self.assertIn("no executable", rep.mismatches["go"])

    def test_compared_counts_agreements(self):
        rep = DiffReport(source=Path("x.ge"))
        rep.reference = RunResult("python", True, stdout="1")
        rep.results["rust"] = RunResult("rust", True, stdout="1")
        rep.results["go"] = RunResult("go", False, note="boom")
        self.assertEqual(rep.compared, 1)


class TestCorpusDiscovery(unittest.TestCase):
    def test_finds_ge_files(self):
        cases = find_cases(CORPUS)
        names = {c.name for c in cases}
        self.assertIn("arith.ge", names)
        self.assertIn("mixed_flavour.ge", names)

    def test_single_file(self):
        self.assertEqual(len(find_cases(CORPUS / "arith.ge")), 1)


class TestBackendAvailability(unittest.TestCase):
    def test_returns_installed_only(self):
        backends = available_backends()
        for b in backends:
            self.assertIn(b, ("rust", "cpp", "csharp", "zig", "go", "kotlin"))

    def test_requested_subset_is_respected(self):
        backends = available_backends(("rust",))
        self.assertTrue(set(backends) <= {"rust"})


class TestDifferentialCorpus(unittest.TestCase):
    """Every case in tests/differential must agree across all backends."""

    def test_corpus_agrees(self):
        backends = available_backends()
        if not backends:
            self.skipTest("no backend toolchain available")

        reports = diff_corpus(CORPUS, backends=backends, timeout=90)
        failures = []
        for r in reports:
            if r.error:
                failures.append(f"{r.source.name}: {r.error}")
            for backend, why in r.mismatches.items():
                failures.append(f"{r.source.name} [{backend}]: {why}")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_reports_cover_every_case(self):
        backends = available_backends()
        if not backends:
            self.skipTest("no backend toolchain available")
        reports = diff_corpus(CORPUS, backends=backends[:1], timeout=90)
        self.assertEqual(len(reports), len(find_cases(CORPUS)))

    def test_mismatch_is_detected(self):
        """A deliberately wrong expectation must be reported as a mismatch."""
        backends = available_backends(("rust",))
        if not backends:
            self.skipTest("rustc not available")

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "wrong.ge"
            p.write_text(
                "# @expect: 999\n"
                "def main() -> None:\n    print(42)\n",
                encoding="utf-8")
            rep = diff_one(p, backends=["rust"], timeout=90)
            self.assertFalse(rep.passed)
            self.assertIn("rust", rep.mismatches)


class TestGoOutputPath(unittest.TestCase):
    """Regression: the Go backend used to write its binary next to the source."""

    def test_binary_lands_in_bin_dir(self):
        if "go" not in available_backends():
            self.skipTest("go not available")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "m.ge.py"
            src.write_text("def main() -> None:\n    print(1)\n", encoding="utf-8")
            r = run_backend(src, "go", timeout=120, workdir=root / "build")
            self.assertTrue(r.ok, r.note)
            self.assertTrue((root / "build" / "desktop" / "bin"
                             / "go_main.exe").exists()
                            or (root / "build" / "desktop" / "bin"
                                / "go_main").exists())


if __name__ == "__main__":
    unittest.main()
