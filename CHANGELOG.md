# Changelog

All notable changes to GE. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
