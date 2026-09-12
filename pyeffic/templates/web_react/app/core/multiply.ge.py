"""Core function: multiply. Compiled to the selected native backend."""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b
