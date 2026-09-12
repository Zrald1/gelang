"""Core function: gcd. Compiled to C++ for performance.

One function per file (C++ Core Guidelines SF.1-SF.5): each function is a
separate compilation unit with a clear dependency list.
"""
from __future__ import annotations
from pyeffic.backends import cpp


@cpp
def gcd(a: int, b: int) -> int:
    """Greatest common divisor (Euclidean algorithm)."""
    while b != 0:
        temp: int = b
        b = a % b
        a = temp
    if a < 0:
        a = -a
    return a
