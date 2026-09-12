"""Core function: multiply. Compiled to C++ for performance.

One function per file (C++ Core Guidelines SF.1-SF.5): each function is a
separate compilation unit with a clear dependency list.
"""
from __future__ import annotations
from pyeffic.backends import cpp


@cpp
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b
