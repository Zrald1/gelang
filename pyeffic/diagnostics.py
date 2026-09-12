"""Structured compiler diagnostics for GE.

Instead of raw Python tracebacks, the compiler produces user-friendly errors:

  error[GE001]: unsupported feature 'try/except' at line 12
    --> myrent.ge.py:12:5
     |
  12 |     try:
     |     ^^^ GE does not support exception handling yet.

Error codes:
  GE001  unsupported feature
  GE002  type mismatch
  GE003  untyped parameter
  GE004  parse error
  GE005  compilation error (rustc/clang++)
  GE006  FFI type error
  GE007  missing function
  GE008  missing entry point
  GE009  TypeScript transpilation error
  GE010  package error
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Diagnostic:
    code: str
    message: str
    file: str = ""
    line: int = 0
    column: int = 0
    source_line: str = ""
    severity: str = "error"  # error, warning, info

    def format(self) -> str:
        """Format the diagnostic as a user-friendly error message."""
        parts = []

        # header: error[GE001]: message
        header = f"{self.severity}[{self.code}]: {self.message}"
        parts.append(header)

        # location: --> file:line:column
        if self.file and self.line > 0:
            loc = f"  --> {self.file}:{self.line}"
            if self.column > 0:
                loc += f":{self.column}"
            parts.append(loc)

            # source context with caret
            if self.source_line:
                line_num = str(self.line)
                pad = " " * len(line_num)
                parts.append(f"  {pad} |")
                parts.append(f"  {line_num} | {self.source_line}")
                if self.column > 0:
                    caret_pad = " " * (self.column - 1)
                    caret_len = max(1, len(self.message.split()[0]) if self.message else 1)
                    parts.append(f"  {pad} | {caret_pad}{'^' * caret_len}")
                parts.append(f"  {pad} |")

        return "\n".join(parts)


class ErrorReporter:
    """Collects and reports compiler diagnostics."""

    def __init__(self):
        self.diagnostics: list[Diagnostic] = []

    def error(self, code: str, message: str, file: str = "", line: int = 0,
              column: int = 0, source_line: str = "") -> None:
        self.diagnostics.append(Diagnostic(code, message, file, line, column,
                                           source_line, "error"))

    def warning(self, code: str, message: str, file: str = "", line: int = 0,
                column: int = 0, source_line: str = "") -> None:
        self.diagnostics.append(Diagnostic(code, message, file, line, column,
                                           source_line, "warning"))

    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)

    def format_all(self) -> str:
        if not self.diagnostics:
            return ""
        parts = [d.format() for d in self.diagnostics]
        error_count = sum(1 for d in self.diagnostics if d.severity == "error")
        warning_count = sum(1 for d in self.diagnostics if d.severity == "warning")
        summary = f"\n{error_count} error(s), {warning_count} warning(s)"
        return "\n\n".join(parts) + summary

    def print(self) -> None:
        formatted = self.format_all()
        if formatted:
            print(formatted)


def report_unsupported(file: str, line: int, feature: str, source_line: str = "") -> Diagnostic:
    """Create a GE001 unsupported feature diagnostic."""
    return Diagnostic(
        code="GE001",
        message=f"unsupported feature '{feature}' — GE does not support this yet",
        file=file,
        line=line,
        source_line=source_line,
    )


def report_type_mismatch(file: str, line: int, expected: str, got: str,
                         source_line: str = "") -> Diagnostic:
    """Create a GE002 type mismatch diagnostic."""
    return Diagnostic(
        code="GE002",
        message=f"type mismatch: expected '{expected}', got '{got}'",
        file=file,
        line=line,
        source_line=source_line,
    )


def report_untyped_param(file: str, line: int, param_name: str,
                         source_line: str = "") -> Diagnostic:
    """Create a GE003 untyped parameter diagnostic."""
    return Diagnostic(
        code="GE003",
        message=f"parameter '{param_name}' has no type annotation — GE requires typed parameters",
        file=file,
        line=line,
        source_line=source_line,
    )


def report_parse_error(file: str, line: int, message: str,
                       source_line: str = "") -> Diagnostic:
    """Create a GE004 parse error diagnostic."""
    return Diagnostic(
        code="GE004",
        message=message,
        file=file,
        line=line,
        source_line=source_line,
    )


def report_compile_error(backend: str, log: str) -> Diagnostic:
    """Create a GE005 compilation error diagnostic from compiler output."""
    # try to extract the first error line from the log
    first_error = ""
    error_line = 0
    for line in log.splitlines():
        if "error" in line.lower():
            first_error = line.strip()
            # try to extract line number from compiler output
            # patterns: file:line:col, file(line,col), file:line, etc.
            import re
            m = re.search(r':(\d+)(?::\d+)?(?:\s*:|\s*\))', line)
            if m:
                try:
                    error_line = int(m.group(1))
                except ValueError:
                    pass
            break
    msg = f"{backend} compilation failed"
    if first_error:
        msg += f": {first_error[:200]}"
    return Diagnostic(
        code="GE005",
        message=msg,
        line=error_line,
    )


def report_missing_function(file: str, name: str) -> Diagnostic:
    """Create a GE007 missing function diagnostic."""
    return Diagnostic(
        code="GE007",
        message=f"function '{name}' is called but not defined or not exported",
        file=file,
    )


def report_missing_entry(file: str, entry: str) -> Diagnostic:
    """Create a GE008 missing entry point diagnostic."""
    return Diagnostic(
        code="GE008",
        message=f"entry point '{entry}' not found in source",
        file=file,
    )
