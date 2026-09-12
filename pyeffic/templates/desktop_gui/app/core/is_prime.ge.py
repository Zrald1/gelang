"""Core function: is_prime. Compiled to C++ for performance.

One function per file (C++ Core Guidelines SF.1-SF.5): each function is a
separate compilation unit with a clear dependency list.
"""
from __future__ import annotations
from pyeffic.backends import cpp


@cpp
def is_prime(n: int) -> int:
    """Return 1 if n is prime, 0 otherwise."""
    if n < 2:
        return 0
    if n == 2:
        return 1
    if n % 2 == 0:
        return 0
    i: int = 3
    while i * i <= n:
        if n % i == 0:
            return 0
        i = i + 2
    return 1
