"""Core function: fibonacci. Compiled to Rust."""
from __future__ import annotations
from pyeffic.backends import rust


@rust
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
