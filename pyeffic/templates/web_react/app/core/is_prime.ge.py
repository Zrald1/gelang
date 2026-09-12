"""Core function: is_prime. Compiled to Rust."""
from __future__ import annotations
from pyeffic.backends import rust


@rust
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
