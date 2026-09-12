"""Buffer capacities. Compiled to Rust.

The server formats responses into fixed-size buffers where possible and
exposes the capacities so every layer agrees on the same bounds.
"""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def mem_json_capacity() -> int:
    """Capacity of the response JSON buffer (bytes)."""
    return 512


@rust
def mem_path_capacity() -> int:
    """Maximum accepted request path length."""
    return 256


@rust
def mem_body_capacity() -> int:
    """Maximum accepted request body size (bytes)."""
    return 65536
