"""Core function: power. Compiled to C++ for performance.

One function per file (C++ Core Guidelines SF.1-SF.5): each function is a
separate compilation unit with a clear dependency list.
"""
from __future__ import annotations
from pyeffic.backends import cpp


@cpp
def power(base: int, exp: int) -> int:
    """Fast exponentiation: base raised to exp."""
    if exp == 0:
        return 1
    if exp < 0:
        return 0
    result: int = 1
    b: int = base
    e: int = exp
    while e > 0:
        if e % 2 == 1:
            result = result * b
        b = b * b
        e = e // 2
    return result
