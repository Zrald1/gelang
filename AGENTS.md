# AGENTS.md — GE Programming Language

GE is a unified, typed source language that compiles to native code through
multiple backends (Rust, C++, C#, Zig, Go, Kotlin) and generates both
Flutter/Dart and React/TypeScript UIs. This file gives AI coding agents the
context needed to work on the GE codebase effectively.

## Project overview

GE follows an **N-frontends x M-backends** architecture: every source flavour
lowers to one shared typed IR (`FuncUnit` + Python AST), and every backend
consumes that IR. Adding a source language means adding a frontend; every
existing backend then works with it unchanged.

Source flavours (frontends):

| File | Frontend | Notes |
|------|----------|-------|
| `foo.ge` | hybrid | **canonical** — flavour detected per chunk |
| `foo.ge.py` | python | whole file is Python-flavoured |
| `foo.ge.ts` | typescript | whole file is TypeScript-flavoured |

`.ge` is the canonical extension and the recommended one. A single `.ge`
file may mix Python-flavoured and TypeScript-flavoured definitions; the
hybrid frontend classifies each top-level chunk from its syntax, lowers the
TypeScript chunks, and concatenates one Python source for the shared IR.
A project can also mix extensions freely.

Target languages (backends): Rust, C++, C#, Zig, Go, Kotlin.
UI targets: Flutter/Dart (`.ge.ui` -> `dartgen`), React/TypeScript
(`.ge.ui` -> `reactgen`).

The compiler:

- Parses source with type annotations (Python or TypeScript flavour).
- Auto-selects the best backend per function based on workload characteristics.
- Emits native code for the selected backend.
- Compiles to a native binary or shared library via the detected toolchain.
- Generates UI code from a separate `.ge.ui` DSL.
- Produces `.ge` packages for distribution.

The two project templates (`desktop-gui`, `web-react`) are the canonical
starting points.

## Setup commands

```bash
# Install GE from source (development mode)
pip install -e .

# Or run directly without install
python -m pyeffic.ge_cli compilers    # show detected toolchains

# Run tests
python -m unittest discover tests
python -m unittest tests.test_simulation_full -v   # backend simulation
python -m unittest tests.test_runtime -v           # runtime output
python -m unittest tests.test_autoselect -v        # auto-selection
python -m unittest tests.test_typescript_frontend  # TS frontend
python -m unittest tests.test_reactgen             # React UI generator
python -m unittest tests.test_hybrid_frontend      # mixed .ge files
python -m unittest tests.test_named_blocks         # <block> tags + @calls
python -m unittest tests.test_mixed_build          # Rust+C++ one exe
python -m unittest tests.test_keyword_escaping     # target keyword escaping
python -m unittest tests.test_difftest             # differential harness
python -m unittest tests.test_build_layout         # build/<target>/ layout
python -m unittest tests.test_stability            # golden + API surface guards

# Build a project
python -m pyeffic.ge_cli create myapp --template desktop-gui -y
python -m pyeffic.ge_cli build myapp/desktop/main.ge.py --run

# Prove every backend agrees with CPython on the same program
python -m pyeffic.ge_cli diff tests/differential
python -m pyeffic.ge_cli diff tests/differential --backends rust,cpp

# Stability guards (see docs/COMPATIBILITY.md)
python -m pyeffic.ge_cli golden --check        # emitted code must not drift
python -m pyeffic.ge_cli api-check             # CLI surface must not change
python -m pyeffic.ge_cli golden --update       # regenerate (review the diff!)

# Scaffold a project
python -m pyeffic.ge_cli create myapp --template desktop-gui -y
python -m pyeffic.ge_cli create myapp --template web-react -y

# Show toolchain status
python -m pyeffic.ge_cli compilers
```

## Architecture

```
pyeffic/
  __init__.py          # package exports
  __main__.py          # python -m pyeffic entry
  ge_cli.py            # CLI: build / flutter / react / pack / install / bench / create
  analyzer.py          # parse source -> FuncUnit; collect_constants/collect_preamble
  frontends/
    __init__.py        # frontend_for(path): "python" | "typescript"
    typescript.py      # TS subset -> Python source -> shared IR
  modules.py           # resolve_imports: transitive module resolution + preamble merge
  autoselect.py        # rule engine: score backends per function, pick best
  researcher.py        # aggregate per-function decisions into program-level backend
  pipeline.py          # build() and build_flutter(): orchestrate full compilation
  compiler.py          # compile_rust/cpp/csharp/zig/go/kotlin: invoke toolchains
  config.py            # detect_compilers(), Config, version-adaptive toolchain finding
  backends.py          # @rust @cpp @csharp @zig @go @kotlin @dart decorators
  diagnostics.py       # error/warning collection
  reactgen.py          # .ge.ui Screen tree -> React 19 + TS + Vite project
  scaffold.py          # ge create: template-based project scaffolding
  templates/
    desktop_gui/       # Rust shell + C++ core + C++ UI template files
    web_react/         # React + TS SPA + Rust backend template files
```

### Named blocks (`<name> ... </name>`)

A block gives a chunk a name and makes it callable from anywhere else in the
file, regardless of which flavour either side is written in:

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
- Backend decorators (`@cpp`, `@rust`, ...) are never rewritten — the rule is
  `@ident(` is a call, bare `@ident` is a decorator.
- `@name(` inside a string literal is left alone.
- Flavour is also detected inside a function body, so a Python-style
  signature with a braced body works:

  ```python
  def clamp(v: int) -> int:
      if (v > LIMIT) {
          return LIMIT;
      }
      return v;
  ```

- Any chunk can be pinned when detection is ambiguous:

  ```python
  # ge:typescript
  const SCALE: number = 2;
  ```

### Intrinsics

| Python flavour | TypeScript flavour | Scope | Purpose |
|----------------|--------------------|-------|---------|
| `ge_inline(backend, code)` | `geInline(...)` | function body | target-specific inline expression |
| `ge_raw(code)` | `geRaw(...)` | function body | unconditional raw code |
| `ge_preamble(backend, code)` | `gePreamble(...)` | module level | file-scope code injection (FFI, Win32 SDK, statics) |

TypeScript flavour also maps `console.log` to `print`, `Math.floor`/`Math.abs`/
`Math.pow`/`Math.max`/`Math.min` to their GE equivalents, `Math.idiv(a, b)` to
integer division, `arr.length` to `len(arr)`, `arr.push(x)` to `arr.append(x)`,
and template literals to f-strings. `@rust` / `@cpp` decorators work in both
flavours.

### Stability guards

Two mechanisms keep the compatibility promise checkable. See
`docs/COMPATIBILITY.md` for the promise and `docs/STABILITY.md` for the
architecture.

- **`ge golden --check`** — every case under `tests/golden/<case>/` has a
  committed `main.ge`, one `<backend>.golden` per backend, and an
  `expected.out`. The check asserts (a) emitted code equals the golden byte
  for byte and (b) compiling and running still prints `expected.out`.
  Regenerate with `--update`, then review the diff and commit it.
- **`ge api-check`** — `api/{cli,diagnostics,intrinsics}.api` are committed
  dumps of the surfaces users depend on. Any drift fails the check.
  Regenerate with `--update`, then review and commit.

A change to either file is a change users can see. Treat it as breaking
unless it is purely additive.

### Build output layout

Artifacts are bucketed by platform so a multi-target project stays readable:

```
build/
  desktop/          native desktop build (ge build, --target desktop)
    backend/          generated native sources
    obj/              object files
    bin/              executables
  web/              web build (--target web)
    backend/  obj/  bin/
  mobile/           Flutter project (ge flutter / ge pack)
    <app>/backend/    native FFI library
    <app>/ui/         generated Dart UI
    <app>/lib/        Dart bindings
```

`Config.target` selects the bucket; `Config.target_dir`, `bin_dir()`,
`obj_dir()` and `backend_dir()` are the accessors. The root defaults to
`build/` and is settable with `-o/--out-dir`.

### Mixed-backend native builds

`ge build` links multiple native backends into one executable. When the
resolved program contains functions from more than one native backend it:

1. emits each non-entry backend in library mode with `extern "C"` exports and
   compiles it to an object file,
2. emits the entry backend (Rust by default) with matching `extern "C"`
   declarations for the functions it calls across the boundary,
3. links the objects into one executable, adding the Win32 libs
   (`user32`, `gdi32`, `winmm`, `winhttp`) on Windows.

So a desktop app can keep its window/event loop in Rust and its hot code and
rendering in C++ with a single command:

```bash
ge build desktop/main.ge.py --run
```

No project build script and no hand-written FFI declarations are needed —
cross-backend declarations are generated from the call graph.

`ge_preamble` is collected by `analyzer.collect_preamble`, merged across
imported modules by `modules.resolve_imports` (import order, dependencies
first), and injected by each emitter after the prelude and forward
declarations but before function definitions.

### Compiler modules

`from pyeffic.backends import rust` selects a decorator; it is not a user
import. `modules._is_compiler_module` skips `pyeffic.*` and `__future__` so
the compiler's own sources are never pulled into a program.
  ffi.py               # tag functions for C ABI FFI exports
  dartgen.py           # Dart/Flutter code generation
  ui_dsl.py            # .ge.ui parser -> Flutter widget tree
  packer.py            # .ge package format (pack/unpack)
  bench.py             # GE vs hand-written C++ benchmarks
  cli.py               # legacy CLI (pyeffic command)
  emitters/
    base.py            # Emitter base class + Spec dataclass
    rust.py             # Rust emitter
    cpp.py             # C++ emitter
    csharp.py          # C# emitter (NativeAOT)
    zig.py             # Zig emitter
    go.py              # Go emitter
    kotlin.py          # Kotlin emitter
    dart.py            # Dart emitter
tests/
  test_simulation.py        # original simulation tests
  test_autoselect.py        # auto-selection + Kotlin tests
  test_simulation_full.py   # comprehensive backend simulation (simple/medium/complex)
  test_runtime.py           # compile + run + verify output
```

## Code style

- Python 3.10+ (uses `match` statements, union types `X | None`).
- No external dependencies beyond the Python standard library.
- Type annotations on all public functions.
- 4-space indentation, no tabs.
- Compact code: collapse duplicate branches, share abstractions.
- Do NOT add or remove comments unless asked.
- Follow existing patterns in neighboring files.

## Key concepts

### FuncUnit

`analyzer.py` parses `.ge.py` source into a list of `FuncUnit` objects.
Each `FuncUnit` has:
- `name`: function name
- `params`: list of (name, type) tuples
- `ret_type`: return type string
- `body`: list of AST statements
- `forced_backend`: set by `@rust`/`@cpp`/etc decorators, or `None` for auto
- `supported`: whether the function can be compiled (no unsupported constructs)

### Auto-selection

`autoselect.py` scores each backend for each function based on:
- Function features (arithmetic, concurrency, I/O, etc.)
- Function name patterns (compute -> C++, fetch -> Go, build -> Dart, etc.)
- Body patterns (network calls, async calls, etc.)

Priority: explicit decorator > forced config > auto-selection > Rust default.

### Emitter Spec

Each backend has a `Spec` dataclass in `pyeffic/emitters/` that defines:
- Type mappings (int -> i64, float -> f64, etc.)
- Loop, print, cast, division syntax templates
- Function and variable declaration templates
- FFI export prefix (`extern "C"`, `export fn`, `//export`, `@CName`, etc.)

### Pipeline

`pipeline.py` orchestrates:
1. Parse source -> FuncUnits
2. Auto-select or use forced backend
3. Emit source code for each backend
4. Compile via detected toolchain
5. Generate FFI bindings for cross-backend calls
6. Produce BuildReport with all results

## Testing

- `python -m unittest discover tests` — runs all 1147 tests
- Tests skip gracefully when a toolchain is not installed
- Runtime tests compile and run binaries, verifying actual output
- Simulation tests cover simple/medium/complex code for all 6 backends
- Pairwise combination tests verify all 15 backend pairs coexist

## Toolchain adaptability

GE is version-adaptive: it detects any version of each toolchain on PATH or
in the local `tools/` directory. Minimum supported versions are defined in
`config.py:MIN_VERSIONS`. Updated toolchains are detected automatically —
no code changes needed when Rust/Go/Zig/etc release new versions.

To add a new toolchain version, just install it. GE will find it.

## Boundaries

### Always
- Follow existing code patterns and style.
- Run tests before and after changes.
- Keep backends separated: each emitter in its own file.
- Preserve explicit backend selection (decorators override auto-selection).
- Keep build artifacts under `build/<target>/`, bucketed by platform:
  `desktop`, `web`, `mobile` (see "Build output layout").

### Ask first
- Adding a new backend (requires emitter + compiler + config + tests).
- Changing the `.ge` package format.
- Modifying the auto-selection scoring weights.
- Changing the FuncUnit dataclass shape.

### Never
- Remove an existing backend.
- Hardcode specific toolchain versions in detection logic.
- Claim generated code outperforms equally optimized hand-written native code.
- Break the `.ge.ui` DSL parser.
- Add external Python dependencies (keep stdlib-only).
- Modify repository security policies or CI configuration.

## Adding a new frontend (source language)

1. Create `pyeffic/frontends/<name>.py` exposing:
   - `<name>_to_python(source) -> str` (or build the IR directly)
   - `parse_<name>_source_full(source) -> (units, classes)`
   - `collect_<name>_constants(source)` and `collect_<name>_preamble(source)`
2. Register its file suffixes in `pyeffic/frontends/__init__.py`
   (`TYPESCRIPT_SUFFIXES` style tuple + `frontend_for`).
3. Wire the flavour into `pyeffic/modules.py` (`_parse_source`,
   `_collect_constants`, `_collect_preamble`, `_find_module` leaf names).
4. Wire it into `pyeffic/pipeline.build()` so the source is lowered before
   type checking and diagnostics.
5. Add tests under `tests/test_<name>_frontend.py`.

The simplest lowering strategy (used by the TypeScript frontend) is to emit
Python source and reuse `ast.parse`, so both frontends share one IR and one
set of emitters.

## Adding a new UI target

1. Create `pyeffic/<target>gen.py` with `generate_<target>_app(screen, ...)`
   returning a `{relative_path: content}` dict, plus `write_<target>_app`.
2. Add a `ge <target>` subcommand in `pyeffic/ge_cli.py`.
3. Add a template under `pyeffic/templates/<name>/` and register it in
   `scaffold.TEMPLATE_DIRS`.
4. Add tests under `tests/test_<target>gen.py`.

## Adding a new backend

1. Create `pyeffic/emitters/<name>.py` with a `Spec` and `emit_<name>()` function.
2. Add the `@<name>` decorator to `pyeffic/backends.py`.
3. Add `@<name>` recognition to `pyeffic/analyzer.py`.
4. Add compiler detection to `pyeffic/config.py` (`_find_tool()` + `detect_compilers()`).
5. Add `compile_<name>()` to `pyeffic/compiler.py`.
6. Add fields and compilation reporting to `pyeffic/pipeline.py`.
7. Export the emitter from `pyeffic/emitters/__init__.py`.
8. Add auto-selection rules to `pyeffic/autoselect.py`.
9. Add tests to `tests/test_simulation_full.py` and `tests/test_runtime.py`.

## Common tasks

### Fix a backend compilation error
1. Run the failing test to see the compiler error.
2. Check the emitted source code (print it or look at `ge_build/backend/`).
3. Fix the emitter in `pyeffic/emitters/<name>.py`.
4. Re-run the test.

### Add a new auto-selection rule
1. Add the rule to `pyeffic/autoselect.py` in the scoring function.
2. Add a test to `tests/test_autoselect.py`.
3. Run `python -m unittest tests.test_autoselect`.

### Update a toolchain version
1. Install the new version on PATH or in `tools/`.
2. Run `python -m pyeffic.ge_cli compilers` to verify detection.
3. Run tests to verify compatibility.
4. Update `MIN_VERSIONS` in `config.py` if the minimum changes.
