"""Tests for the stability guards: golden lowering + API surface.

These two mechanisms are what make the compatibility promise checkable:

  ge golden --check   emitted code must not drift, and must still behave
  ge api-check        the CLI / diagnostics / intrinsics surface must not move
"""
import tempfile
import unittest
from pathlib import Path

from pyeffic.apisurface import (
    all_dumps,
    check as api_check,
    dump_diagnostics,
    dump_intrinsics,
    update as api_update,
)
from pyeffic.golden import (
    BACKENDS,
    check_case,
    emit_unit,
    find_cases,
    golden_root,
    update_case,
)

GOLDEN = golden_root()


class TestGoldenCorpus(unittest.TestCase):
    def test_corpus_exists(self):
        cases = find_cases(GOLDEN)
        self.assertGreaterEqual(len(cases), 3)
        names = {c.name for c in cases}
        self.assertIn("arithmetic", names)
        self.assertIn("mixed_flavour", names)

    def test_every_case_has_expected_output(self):
        for case in find_cases(GOLDEN):
            self.assertTrue((case / "expected.out").exists(),
                            f"{case.name} needs expected.out")

    def test_every_case_has_all_goldens(self):
        for case in find_cases(GOLDEN):
            for backend in BACKENDS:
                self.assertTrue((case / f"{backend}.golden").exists(),
                                f"{case.name} needs {backend}.golden")

    def test_corpus_matches(self):
        """The committed goldens must equal what the emitters produce now."""
        problems = []
        for case in find_cases(GOLDEN):
            for p in check_case(case, BACKENDS, run=False):
                problems.append(f"{p.case} [{p.kind}]: {p.detail}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_emission_is_deterministic(self):
        """Emitting twice must produce identical bytes."""
        for case in find_cases(GOLDEN):
            src = case / "main.ge"
            if not src.exists():
                continue
            for backend in BACKENDS:
                a = emit_unit(src, backend)
                b = emit_unit(src, backend)
                self.assertEqual(a, b, f"{case.name}/{backend} is not deterministic")


class TestGoldenDriftDetection(unittest.TestCase):
    def test_drift_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "case"
            case.mkdir()
            (case / "main.ge").write_text(
                "def main() -> None:\n    print(1)\n", encoding="utf-8")
            (case / "expected.out").write_text("1\n", encoding="utf-8")
            for backend in BACKENDS:
                (case / f"{backend}.golden").write_text("stale\n", encoding="utf-8")

            problems = check_case(case, BACKENDS, run=False)
            self.assertTrue(problems)
            self.assertTrue(all(p.kind == "lowering" for p in problems))

    def test_missing_golden_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "case"
            case.mkdir()
            (case / "main.ge").write_text(
                "def main() -> None:\n    print(1)\n", encoding="utf-8")
            problems = check_case(case, ("rust",), run=False)
            self.assertEqual(len(problems), 1)
            self.assertEqual(problems[0].kind, "missing")

    def test_update_then_check_passes(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "case"
            case.mkdir()
            (case / "main.ge").write_text(
                "def main() -> None:\n    print(1)\n", encoding="utf-8")
            update_case(case, ("rust",))
            self.assertEqual(check_case(case, ("rust",), run=False), [])

    def test_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "case"
            case.mkdir()
            (case / "main.ge").write_text(
                "def main() -> None:\n    print(2)\n", encoding="utf-8")
            first = update_case(case, ("rust",))
            self.assertTrue(first)
            second = update_case(case, ("rust",))
            self.assertEqual(second, [], "a second update should write nothing")


class TestGoldenCoversRealConstructs(unittest.TestCase):
    """The corpus must exercise the features most likely to drift."""

    def test_arithmetic_case_has_division(self):
        src = (GOLDEN / "arithmetic" / "main.ge").read_text(encoding="utf-8")
        self.assertIn("//", src)
        self.assertIn("%", src)

    def test_control_flow_case_has_loop_and_branch(self):
        src = (GOLDEN / "control_flow" / "main.ge").read_text(encoding="utf-8")
        self.assertIn("while", src)
        self.assertIn("if", src)

    def test_mixed_case_has_typescript_and_block(self):
        src = (GOLDEN / "mixed_flavour" / "main.ge").read_text(encoding="utf-8")
        self.assertIn("export function", src)
        self.assertIn("<factorial", src)
        self.assertIn("@triple", src)


class TestApiSurfaceDumps(unittest.TestCase):
    def test_dumps_are_non_empty(self):
        dumps = all_dumps()
        self.assertEqual(set(dumps), {"cli.api", "diagnostics.api", "intrinsics.api"})
        for name, content in dumps.items():
            self.assertTrue(content.strip(), f"{name} is empty")

    def test_cli_dump_names_commands(self):
        cli = all_dumps()["cli.api"]
        for cmd in ("build", "diff", "golden", "api-check", "react", "flutter"):
            self.assertIn(f"{cmd} <command>", cli, cmd)

    def test_cli_dump_is_sorted(self):
        lines = all_dumps()["cli.api"].splitlines()
        self.assertEqual(lines, sorted(lines))

    def test_diagnostics_are_documented(self):
        diag = dump_diagnostics()
        for code in ("GE001", "GE002", "GE005", "GE007", "GE008", "GE010", "GE011"):
            self.assertIn(code, diag, code)

    def test_intrinsics_listed(self):
        intr = dump_intrinsics()
        for name in ("ge_preamble", "ge_inline", "ge_raw",
                     "gePreamble", "geInline", "geRaw"):
            self.assertIn(name, intr, name)

    def test_extensions_listed(self):
        intr = dump_intrinsics()
        for ext in (".ge", ".ge.py", ".ge.ts", ".ge.ui"):
            self.assertIn(f"extension {ext} ->", intr, ext)

    def test_dumps_are_deterministic(self):
        self.assertEqual(all_dumps(), all_dumps())


class TestApiSurfaceCheck(unittest.TestCase):
    def test_committed_dumps_match(self):
        changed, missing = api_check()
        self.assertEqual(missing, [], f"missing dumps: {missing}")
        self.assertEqual(changed, [], f"surface changed: {changed}")

    def test_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_update(root)
            self.assertEqual(api_check(root), ([], []))

            # simulate someone changing a flag without regenerating
            p = root / "cli.api"
            p.write_text(p.read_text(encoding="utf-8") + "build option --brand-new\n",
                         encoding="utf-8")
            changed, missing = api_check(root)
            self.assertEqual(missing, [])
            self.assertIn("cli.api", changed)

    def test_missing_dump_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            changed, missing = api_check(Path(td))
            self.assertEqual(changed, [])
            self.assertEqual(len(missing), 3)

    def test_update_writes_everything(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            written = api_update(root)
            self.assertEqual(len(written), 3)
            for name in written:
                self.assertTrue((root / name).exists())

    def test_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_update(root)
            self.assertEqual(api_update(root), [])


if __name__ == "__main__":
    unittest.main()
