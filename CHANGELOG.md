# Changelog

All notable changes to GE. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] — 2026-09-13

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

## [Unreleased]

### Added

- **Hybrid `.ge` frontend** — one file may mix Python-flavoured and
  TypeScript-flavoured definitions. Flavour is detected per chunk.
- **Named blocks** — `<name> ... </name>` gives a chunk a name; `@name(...)`
  calls it from anywhere in the file, in either flavour, forward or backward.
- **Mixed-backend native linking** — `ge build` emits each non-entry backend
  in library mode with `extern "C"` exports, compiles it to an object, and
  links one executable. No build script, no hand-written FFI.
- **`ge diff`** — differential testing. Runs the same program through CPython
  and every installed backend, comparing output byte-for-byte.
- **`ge golden`** — golden lowering corpus. Emitted code must match the
  committed golden, and compiling it must still print the expected output.
- **`ge api-check`** — committed dumps of the CLI, diagnostics, and intrinsic
  surfaces. Drift fails the check.
- **`ge doctor`** — runtime and toolchain check with per-platform install
  hints. `--json` for CI.
- **`ge react`** — generates a React 19 + TypeScript + Vite project from a
  `.ge.ui` file, one component per file.
- **Organized build output** — `build/{desktop,web,mobile}/{backend,obj,bin}`.
- **npm distribution** — `npx gelang` runs the compiler with bundled source,
  no `pip install` required.
- **`--target` buckets** — `desktop`, `web`, `mobile`.
- **Target-keyword safety** — identifiers that collide with a target
  language's reserved words are escaped (`@base` in C#, `r#match` in Rust)
  or renamed consistently across the ABI (`double` → `double_`).

### Fixed

- C# reserved words in parameter positions emitted invalid code (`base`).
- Function names colliding with target keywords broke compilation
  (`double` in C++, `match` in Rust).
- `from pyeffic.backends import rust` was resolved as user code, pulling the
  compiler's own sources into the program.
- `ge_build`/`build_flutter` used an undefined `preamble` variable.
- Go backend wrote binaries next to the source instead of `build/<target>/bin`.
- Module resolver matched a sibling file for dotted imports
  (`app.main` resolved to `desktop/main.ge`).
- `.ge.ui` parser rejected files with a leading docstring.
- `.ge.ui` parser only accepted `Screen "title" {}`, not `Window { title: }`.

### Changed

- Canonical extension is `.ge`. `.ge.py` and `.ge.ts` remain supported for
  single-flavour files; `.ts.ge.py` is accepted as a legacy alias.
- Build root defaults to `build/` (was `ge_build/`).
- Package name on npm is `gelang`.

## [0.1.0] — 2026-09-12

Initial version.

- Python-like source language compiling to Rust, C++, C#, Zig, Go, Kotlin.
- Auto-selection of backend per function.
- Flutter/Dart UI generation from a `.ge.ui` DSL.
- `.ge` package format, `ge pack` / `ge install` / `ge deploy`.
- `ge bench` for parity benchmarking against hand-written C++.
