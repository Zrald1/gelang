"""Core function: fibonacci. Compiled to C++ for performance.

One function per file (C++ Core Guidelines SF.1-SF.5): each function is a
separate compilation unit with a clear dependency list.
"""
from __future__ import annotations
from pyeffic.backends import cpp


@cpp
def fibonacci(n: int) -> int:
    """Compute the nth Fibonacci number iteratively."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a: int = 0
    b: int = 1
    i: int = 2
    while i <= n:
        temp: int = a + b
        a = b
        b = temp
        i = i + 1
    return b
