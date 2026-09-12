"""pyeffic - Python to C++/Rust efficiency-driven transpiler.

Write Python. pyeffic analyzes each function, researches whether C++ or Rust
is the better backend for that workload, emits native code, compiles it, and
runs it. Unsupported Python constructs fall back to embedded CPython so the
full language is always covered (just not always accelerated).
"""

__version__ = "0.1.0"
