"""Core function: factorial. Compiled to Rust."""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def factorial(n: int) -> int:
    """Compute factorial of n (n is clamped by the memory layer)."""
    if n <= 1:
        return 1
    result: int = 1
    i: int = 2
    while i <= n:
        result = result * i
        i = i + 1
    return result
