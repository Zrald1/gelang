from pathlib import Path
import json
import re

NEW = "0.1.2"

# package.json
p = Path("package.json")
d = json.loads(p.read_text(encoding="utf-8"))
old = d["version"]
d["version"] = NEW
p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
print(f"package.json: {old} -> {NEW}")

# pyproject.toml
p = Path("pyproject.toml")
t = p.read_text(encoding="utf-8")
t = re.sub(r'^version\s*=\s*"[^"]+"', f'version = "{NEW}"', t, count=1, flags=re.M)
p.write_text(t, encoding="utf-8")
print(f"pyproject.toml -> {NEW}")

# CHANGELOG: add a new section above [Unreleased]
p = Path("CHANGELOG.md")
t = p.read_text(encoding="utf-8")
entry = f"""## [{NEW}] — 2026-09-13

Found by `scripts/e2e.py`, a new harness that compiles and runs 118
programs on every installed backend and compares stdout with CPython.

### Fixed

- **Wrong output.** `print(True)` printed lowercase `true` on Rust, C++,
  Go, Zig and Kotlin; list printing used each target's native format
  (`[1 2 3]` in Go, `{ 1, 2, 3 }` in Zig). Both now match Python.
- **Dict iteration** walked `(key, value)` pairs instead of keys, so
  `for k in d: d[k]` failed to compile on every backend.
- **List slicing** was marked unsupported, which dropped the whole
  function and surfaced as the misleading `main function not found`.
  `xs[a:b]`, `xs[a:]`, `xs[:b]` and `xs[:]` are implemented everywhere.
- **`str.split` / `str.join`** had no implementation at all.
- **`str.replace`** had no implementation at all.
- **`min(a, b)` / `max(a, b)`** emitted a bare call no target provides.
- **`abs()`** on a literal was ambiguous in Rust, untyped in Zig, and
  absent for `int64` in Go.
- **Default arguments** were rejected outright. A call may now supply
  between `n_required` and `len(params)` arguments.
- **`set` annotations** became `f64`, because `set` was missing from the
  native type mapping. Added `set_type` per backend.
- **Lists of strings** could not be expressed: only Rust and C++ had a
  `{T}` placeholder in `list_type`.
- **C++ `std::sqrt`** appeared before `#include <cmath>`.
- **Kotlin** used `Math.pow` (no such class in Kotlin/Native) and a
  C-style ternary (Kotlin has no `?:`).
- **C++ `upper()` / `lower()`** emitted a bare comment, so the program
  compiled but did nothing.
- **Rust string concatenation** moved the left operand.
- **Emitter crashes**: when the entry function was rejected, zig, go,
  kotlin and csharp raised `IndexError` instead of reporting the reason.
- **`ge tools check`** disagreed with `ge doctor` because `CompilerInfo`
  field names (`dotnet`, `kotlinc`) differ from the public toolchain
  names.
- **Zig** emitted a raw newline inside a string literal, and
  `_mark_unsupported` produced a C-style comment, which Zig rejects.

### Added

- `scripts/e2e.py` — end-to-end tests against real toolchains.
- `ge doctor` — runtime and toolchain check with install hints.

### Known limitations

- Zig models lists as fixed slices, so `list.append` is rejected with a
  clear diagnostic rather than compiling. Switching the backend to
  `std.ArrayList` needs an allocator threaded through every signature.
- Tuples are supported at arity 2; other arities are rejected with a
  diagnostic instead of emitting broken code.

"""
anchor = "## [Unreleased]\n"
if f"## [{NEW}]" not in t:
    i = t.find(anchor)
    if i != -1:
        t = t[:i] + entry + t[i:]
        p.write_text(t, encoding="utf-8")
        print("CHANGELOG.md: added", NEW)
    else:
        print("!! CHANGELOG anchor missing")
else:
    print("-- CHANGELOG already has", NEW)
