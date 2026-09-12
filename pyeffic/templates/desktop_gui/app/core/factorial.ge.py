"""Core function: factorial. Compiled to C++ for performance.

One function per file (C++ Core Guidelines SF.1-SF.5): each function is a
separate compilation unit with a clear dependency list.
"""
from __future__ import annotations
from pyeffic.backends import cpp


@cpp
def factorial(n: int) -> int:
    """Compute factorial of n."""
    if n <= 1:
        return 1
    result: int = 1
    i: int = 2
    while i <= n:
        result = result * i
        i = i + 1
    return result
