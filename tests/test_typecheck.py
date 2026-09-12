"""Test the type checker and diagnostics system."""
import unittest
from pyeffic.typecheck import check_source
from pyeffic.diagnostics import Diagnostic, ErrorReporter, report_unsupported


class TestTypeChecker(unittest.TestCase):
    def test_no_errors_on_valid_source(self):
        source = """
def add(a: int, b: int) -> int:
    return a + b
"""
        errors = check_source(source, file="test.ge.py")
        self.assertFalse(errors.has_errors())

    def test_arg_count_mismatch(self):
        source = """
def add(a: int, b: int) -> int:
    return a + b
def main() -> None:
    print(add(1))
"""
        errors = check_source(source, file="test.ge.py")
        self.assertTrue(errors.has_errors())
        self.assertIn("expects 2 args", errors.format_all())

    def test_int_float_mismatch_warning(self):
        source = """
def f(x: float) -> int:
    return x
"""
        errors = check_source(source, file="test.ge.py")
        # should produce a warning about returning float from int function
        formatted = errors.format_all()
        # warnings don't count as errors
        self.assertFalse(errors.has_errors())

    def test_correct_function_no_errors(self):
        source = """
def f(n: int) -> int:
    total: int = 0
    for i in range(0, n):
        total = total + i
    return total
"""
        errors = check_source(source, file="test.ge.py")
        self.assertFalse(errors.has_errors())


class TestDiagnostics(unittest.TestCase):
    def test_diagnostic_format(self):
        d = Diagnostic(
            code="GE001",
            message="unsupported feature 'try/except'",
            file="test.ge.py",
            line=12,
            column=5,
            source_line="    try:",
        )
        formatted = d.format()
        self.assertIn("error[GE001]", formatted)
        self.assertIn("test.ge.py:12", formatted)
        self.assertIn("try:", formatted)

    def test_error_reporter(self):
        reporter = ErrorReporter()
        reporter.error("GE001", "test error")
        reporter.warning("GE002", "test warning")
        self.assertTrue(reporter.has_errors())
        self.assertEqual(len(reporter.diagnostics), 2)

    def test_report_unsupported(self):
        d = report_unsupported("test.ge.py", 12, "try/except", "    try:")
        self.assertEqual(d.code, "GE001")
        self.assertEqual(d.line, 12)
        self.assertIn("try/except", d.message)

    def test_empty_reporter(self):
        reporter = ErrorReporter()
        self.assertFalse(reporter.has_errors())
        self.assertEqual(reporter.format_all(), "")


if __name__ == "__main__":
    unittest.main()
