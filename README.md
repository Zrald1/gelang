# GE

**A typed, multi-target systems language. Write Python-like or TypeScript-like source, compile to native Rust, C++, C#, Zig, Go, or Kotlin — with the backend chosen per function.**

[![npm](https://img.shields.io/npm/v/gelang.svg)](https://www.npmjs.com/package/gelang)
[![CI](https://github.com/Zrald1/gelang/actions/workflows/ci.yml/badge.svg)](https://github.com/Zrald1/gelang/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

GE is a compiler. You write `.ge` files in Python-flavoured or
TypeScript-flavoured syntax — or both in the same file — and GE emits native
code for the backend that suits each function, then links everything into a
single executable.

```bash
npx gelang doctor                          # check what you have
npx gelang build main.ge --run             # compile and run
```

```python
"""main.ge — Python flavour and TypeScript flavour in one file."""

<factorial:typescript>
export function factorial(n: number): number {
    if (n <= 1) {
        return 1;
    }
    let result: number = 1;
    let i: number = 2;
    while (i <= n) {
        result = result * i;
        i = i + 1;
    }
    return result;
}
</factorial>

<greet>
def greet(n: int) -> int:
    return n * 7
</greet>


def main() -> None:
    print(@factorial(5))     # 120
    print(@greet(6))         # 42
```

```
$ ge build main.ge --run
120
42
```

---

## Contents

- [Why GE](#why-ge)
- [Install](#install)
- [Quick start](#quick-start)
- [The language](#the-language)
- [Named blocks](#named-blocks)
- [Backends](#backends)
- [UI targets](#ui-targets)
- [CLI reference](#cli-reference)
- [Project layout](#project-layout)
- [Verification](#verification)
- [Compatibility](#compatibility)
- [Requirements](#requirements)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Why GE

**Compiled, not interpreted.** Other polyglot tools dispatch to language
runtimes. GE lowers every flavour to one typed IR and emits native code from
it, so the result is a single binary with no interpreter in the loop.

**The backend is chosen per function, not per project.** A hot arithmetic
loop and a UI renderer have different needs. GE scores each function and
picks, or you pin one explicitly with `@rust`, `@cpp`, `@csharp`, `@zig`,
`@go`, or `@kotlin`.

**Mixed backends link into one binary.** A Rust shell over a C++ renderer
compiles to a single executable — no shared library, no IPC, no runtime FFI
marshalling. `ge build` derives the `extern "C"` declarations on both sides
from the call graph.

**Small binaries.** A desktop application with a native window, audio
capture, and HTTPS is roughly 15 MB. The same application on Electron is
120–200 MB.

**Two UI ecosystems from one DSL.** `.ge.ui` generates either Flutter/Dart
or React 19 + TypeScript + Vite. Generated files are yours to edit;
regeneration never overwrites them unless you pass `--force`.

**Verifiable by design.** `ge diff` runs a program through CPython and every
installed backend, comparing output byte for byte. `ge golden` pins emitted
code so it cannot drift. `ge api-check` guards the CLI surface. All three run
in CI.

**Suited to AI-assisted development.** GE's input syntax is Python and
TypeScript, so existing model knowledge transfers directly. Named blocks give
an assistant a bounded unit with an explicit call contract, and the compiler
rejects an invalid signature at build time rather than at runtime.

---

## Install

### npm (recommended)

```bash
npx gelang doctor            # one-off, no install
npm install -g gelang        # or install globally
```

The npm package bundles the compiler source and runs it with your system
Python. No `pip install`, no network access at install time.

### pip

```bash
pip install gelang
ge doctor
```

### From source

```bash
git clone https://github.com/Zrald1/gelang.git
cd gelang
pip install -e .
ge doctor
```

### Requirements

GE itself needs **Python 3.10+**. To compile, you need at least **one**
native toolchain. Each one you add widens the set of targets.

| Backend | Toolchain | Install |
|---|---|---|
| Rust | `rustc` ≥ 1.70 | `winget install Rustlang.Rustup` · `brew install rustup-init` · [rustup.rs](https://rustup.rs) |
| C++ | `clang++` or `g++` ≥ 10 | `winget install LLVM.LLVM` · `brew install llvm` · `apt install clang` |
| C# | .NET SDK ≥ 8 | `winget install Microsoft.DotNet.SDK.8` · `brew install --cask dotnet-sdk` |
| Zig | `zig` ≥ 0.13 | [ziglang.org/download](https://ziglang.org/download/) · `brew install zig` |
| Go | `go` ≥ 1.21 | `winget install GoLang.Go` · `brew install go` · `apt install golang` |
| Kotlin | `kotlinc-native` ≥ 2.0 | [Kotlin releases](https://github.com/JetBrains/kotlin/releases) |

Optional, for UI targets:

| Target | Toolchain | Command |
|---|---|---|
| Flutter / Dart | Flutter SDK | `ge flutter` |
| React + TypeScript | Node.js + npm | `ge react` |

Run `ge doctor` any time to see what is detected and what is missing.

---

## Quick start

```bash
# 1. check your environment
npx gelang doctor

# 2. scaffold a project
npx gelang create myapp --template desktop-gui -y
cd myapp

# 3. build and run
npx gelang build desktop/main.ge --run
```

Two templates ship today:

| Template | What you get |
|---|---|
| `desktop-gui` | Rust shell + C++ core + C++ UI (native Win32 window) |
| `web-react` | React 19 + TypeScript SPA + Rust backend |

```bash
ge create myapp --template desktop-gui -y
ge create myapp --template web-react -y
```

---

## The language

### Flavours

| File | Frontend | Notes |
|---|---|---|
| `foo.ge` | **hybrid** | Canonical. Flavour detected per chunk. |
| `foo.ge.py` | python | Whole file is Python-flavoured |
| `foo.ge.ts` | typescript | Whole file is TypeScript-flavoured |

A single `.ge` file may mix both. The compiler classifies each top-level
chunk from its syntax and lowers it.

### Python flavour

```python
from pyeffic.backends import cpp, rust


@rust
def checksum(data: list) -> int:
    total: int = 0
    for x in data:
        total = total + x
    return total


@cpp
def render(value: int) -> int:
    return value * 2
```

### TypeScript flavour

```typescript
export function factorial(n: number): number {
    if (n <= 1) {
        return 1;
    }
    let result: number = 1;
    let i: number = 2;
    while (i <= n) {
        result = result * i;
        i = i + 1;
    }
    return result;
}
```

Types map as `number → int`, `string → str`, `boolean → bool`,
`T[] → list`, `void → None`. `console.log` becomes `print`, `Math.floor`
becomes `int`, `arr.length` becomes `len(arr)`.

### A Python signature with a braced body

Both spellings are accepted:

```python
def clamp(v: int) -> int:
    if (v > LIMIT) {
        return LIMIT;
    }
    return v;
```

### Escape hatches

When you need to drop to the target language:

| Python flavour | TypeScript flavour | Scope | Purpose |
|---|---|---|---|
| `ge_preamble(backend, code)` | `gePreamble(...)` | module level | File-scope injection (includes, FFI, statics) |
| `ge_inline(backend, code)` | `geInline(...)` | function body | Target-specific inline expression |
| `ge_raw(code)` | `geRaw(...)` | function body | Unconditional raw code |

---

## Named blocks

A block gives a chunk a name and makes it callable from anywhere in the file,
regardless of which flavour either side uses.

```python
<add>
def add(a: int, b: int) -> int:
    return a + b
</add>

<render:typescript>
export function render(x: number): number {
    return @add(x, 1);      // @block(...) calls the block
}
</render>
```

Rules:

- `<name>` opens, `</name>` closes. Tags must match.
- Language is detected from the content, or pinned with
  `<name:python>` / `<name:typescript>` (aliases `:py` / `:ts`).
- `@name(...)` calls the block. It resolves to the function inside the block
  named `name`, or to the block's only function if the names differ.
- A call site may appear before the block it names.
- Backend decorators (`@cpp`, `@rust`, …) are never rewritten — `@ident(` is
  a call, bare `@ident` is a decorator.
- `@name(` inside a string literal is left alone.
- Pin an ambiguous chunk with a marker comment:

  ```python
  # ge:typescript
  const SCALE: number = 2;
  ```

---

## Backends

| Backend | Decorator | Emits | Runs as |
|---|---|---|---|
| Rust | `@rust` | `build/<target>/backend/*.rs` | native exe / cdylib |
| C++ | `@cpp` | `*.cpp` | native exe / object / dll |
| C# | `@csharp` | `*.cs` | NativeAOT exe / dll |
| Zig | `@zig` | `*.zig` | native exe / shared lib |
| Go | `@go` | `*.go` | native exe / c-shared lib |
| Kotlin | `@kotlin` | `*.kt` | Kotlin/Native exe / lib |

Without a decorator, GE scores each function and picks. Explicit decorators
always win.

### Mixed-backend linking

When a program spans more than one native backend, `ge build` does the whole
job itself:

1. Emits each non-entry backend in library mode with `extern "C"` exports and
   compiles it to an object file.
2. Emits the entry backend (Rust by default) with matching `extern "C"`
   declarations derived from the call graph.
3. Links the objects into one executable.

```bash
ge build desktop/main.ge --run      # Rust shell + C++ core → one .exe
```

No build script and no hand-written FFI declarations are needed.

---

## UI targets

### Flutter / Dart

```bash
ge flutter app/main.ge --app-name myapp
cd build/mobile/myapp && flutter pub get && flutter run
```

### React + TypeScript

```bash
ge react ui/main.ge.ui --app-name myapp
cd build/web/frontend && npm install && npm run dev
```

`ge react` reads a `.ge.ui` DSL file and generates a Vite project with one
component per file. Existing files are kept unless you pass `--force`.

```python
Window {
  title: "My App"
  Column {
    padding: 24
    children:
      Text "Hello" style="headline"
      TextField state="query" hint="type here"
      ElevatedButton "Run" on_click=Action(call="compute")
      Text state="result" style="value"
  }
}
```

---

## CLI reference

```
ge doctor                     Check runtime + toolchains, with install hints
ge compilers                  Show detected toolchains
ge create [NAME]              Scaffold a project (--template, --platforms, --backends)
ge build <file>               Compile (--backend, --target, --run, -o)
ge analyze <file>             Type check and report diagnostics
ge diff <file-or-dir>         Prove every backend matches CPython byte-for-byte
ge golden --check             Prove emitted code has not drifted
ge api-check                  Prove the CLI surface has not changed
ge react <ui.ge.ui>           Generate a React + TypeScript UI
ge flutter <file>             Build a Flutter app (native FFI lib + Dart UI)
ge pack <file>                Bundle into a single .ge package
ge install <package>          Unpack and build for a target
ge deploy <package>           Distribute and run
ge tools list|install|check   Manage toolchains
ge bench                      Benchmark against hand-written C++
```

### Common flags

| Flag | Meaning |
|---|---|
| `--backend rust\|cpp\|csharp\|zig\|go\|kotlin\|auto` | Force a backend (default `auto`) |
| `--target desktop\|web\|mobile\|crossplatform` | Platform bucket |
| `--entry NAME` | Entry point function (default `main`) |
| `-o, --out-dir DIR` | Output root (default `build`) |
| `--run` | Run after a successful build |

---

## Project layout

### Build output

```
build/
  desktop/          native build
    backend/          generated sources
    obj/              object files
    bin/              executables
  web/              web build
    backend/  obj/  bin/
  mobile/           Flutter project
    <app>/backend/    native FFI library
    <app>/ui/         generated Dart UI
    <app>/lib/        Dart bindings
```

### A scaffolded project

```
myapp/
  app/
    memory/       bounded state (limits, buffers, slots)
    core/         computation, one function per file
    ui/           theme, layout, widgets, render
    main.ge       aggregator
  desktop/
    main.ge       entry point
  tests/
  ge.toml
```

---

## Verification

GE ships the machinery to prove it is correct, not just that it runs.

```bash
# every backend must produce the same output as CPython
ge diff tests/differential

# emitted code must not drift, and must still behave
ge golden --check

# the CLI / diagnostics / intrinsics surface must not move
ge api-check

# the full suite
python -m unittest discover tests
```

| Guard | What it catches |
|---|---|
| `ge diff` | Backend-specific codegen bugs, semantic drift from Python |
| `ge golden` | Silent emitter churn — code that still compiles but changed |
| `ge api-check` | Renamed flags, removed commands, reused diagnostic codes |
| Test suite | Everything else, including 600 compile-and-run cases |

---

## Compatibility

GE is pre-1.0. The promise and the mechanisms behind it are documented in
[`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md):

- A released `.ge` program keeps compiling and keeps producing the same
  output, within its edition.
- Breaking changes go into a new **edition** — never a patch or minor release.
- Editions interoperate: a module on a newer edition is importable from an
  older one.
- Deprecations last at least two minor releases with a published removal
  version.
- Unstable features require explicit opt-in.

See also [`docs/STABILITY.md`](docs/STABILITY.md) (how it works) and
[`docs/PRODUCTION_GAPS.md`](docs/PRODUCTION_GAPS.md) (what is not done yet).

---

## Requirements

| Component | Minimum |
|---|---|
| Python | 3.10 |
| Node.js (npm install only) | 16 |
| rustc | 1.70 |
| clang++ / g++ | 10 |
| .NET SDK | 8 |
| zig | 0.13 |
| go | 1.21 |
| kotlinc-native | 2.0 |

GE detects whatever versions you have — no pinned toolchains, no version
switching.

---

## Troubleshooting

**`GE needs Python 3.10 or newer`**
Install Python, or point GE at one with `GE_PYTHON=/path/to/python`.

**`0 of 6 native backends available`**
You need at least one compiler. `ge doctor` prints the install command for
your platform.

**A build succeeds but nothing runs**
Some constructs fall back to CPython instead of native code. The build
summary lists them under `fallback:`. See
[`docs/PRODUCTION_GAPS.md`](docs/PRODUCTION_GAPS.md) §C4.

**`ge build` says "renamed 'x' -> 'x_'"**
`x` is a reserved word in a target language (e.g. `double` is a C++ type).
GE renames the symbol consistently on both sides of the ABI.

**Generated React files were overwritten**
They are not, unless you pass `--force`. `ge react` only writes files that do
not exist.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Two guides for extending GE:

- **Add a backend** — `pyeffic/emitters/<name>.py` + a `Spec` + a compiler entry
- **Add a frontend** — `pyeffic/frontends/<name>.py` + suffix registration

`AGENTS.md` documents the architecture in detail for AI coding agents.

---

## License

MIT. See [`LICENSE`](LICENSE).
