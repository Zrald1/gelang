# Contributing to GE

Thanks for helping. This document covers the setup, the layout, and the two
extension points.

## Setup

```bash
git clone https://github.com/Zrald1/gelang.git
cd gelang
pip install -e .
ge doctor                      # see which backends you can build
python -m unittest discover tests
```

You do not need every toolchain. Tests skip gracefully when a backend is
missing, so a Rust-only machine still runs most of the suite.

## What to run before opening a PR

```bash
python -m unittest discover tests   # full suite (~60 min; it compiles and runs)
ge golden --check                   # emitted code must not drift
ge api-check                        # CLI surface must not change
ge diff tests/differential          # backends must agree with CPython
```

If you deliberately changed emitted code or the CLI surface:

```bash
ge golden --update     # then review the diff and commit it
ge api-check --update  # then review the diff and commit it
```

A change to `tests/golden/*.golden` or `api/*.api` is a change users can
see. Treat it as breaking unless it is purely additive. See
[`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## Layout

```
pyeffic/
  ge_cli.py          CLI entry point
  analyzer.py        source -> FuncUnit IR
  frontends/         source flavours (python, typescript, hybrid)
  modules.py         import resolution
  pipeline.py        build orchestration
  emitters/          one file per backend
  compiler.py        toolchain invocation
  idents.py          target-keyword safety
  difftest.py        cross-backend verification
  golden.py          emitted-code stability
  apisurface.py      CLI/diagnostic surface guard
  scaffold.py        `ge create`
  templates/         project templates (real file trees)
  reactgen.py        .ge.ui -> React
  dartgen.py         .ge.ui -> Flutter
tests/               test suite + differential + golden corpora
scripts/             build, packaging, toolchain checks
docs/                plan, gaps, stability, compatibility
```

## Adding a backend

1. `pyeffic/emitters/<name>.py` — a `Spec` and an `emit_<name>()` function.
2. `pyeffic/backends.py` — the `@<name>` decorator.
3. `pyeffic/analyzer.py` — recognise the decorator.
4. `pyeffic/config.py` — toolchain detection.
5. `pyeffic/compiler.py` — `compile_<name>()`.
6. `pyeffic/pipeline.py` — reporting fields.
7. `pyeffic/emitters/__init__.py` — export it.
8. `pyeffic/idents.py` — reserved words + escape style.
9. Tests in `tests/test_simulation_full.py` and `tests/test_runtime.py`.
10. `ge golden --update` to add goldens.

## Adding a frontend

1. `pyeffic/frontends/<name>.py` exposing:
   - `<name>_to_python(source) -> str` (or build the IR directly)
   - `parse_<name>_source_full(source) -> (units, classes)`
   - `collect_<name>_constants(source)`, `collect_<name>_preamble(source)`
2. Register its suffixes in `pyeffic/frontends/__init__.py`.
3. Wire the flavour into `pyeffic/modules.py`.
4. Wire it into `pyeffic/pipeline.build()`.
5. Tests in `tests/test_<name>_frontend.py`.

The simplest strategy is what the TypeScript frontend does: emit Python
source and reuse `ast.parse`, so both frontends share one IR.

## Adding a UI target

1. `pyeffic/<target>gen.py` with `generate_<target>_app(screen, ...)`.
2. A `ge <target>` subcommand in `pyeffic/ge_cli.py`.
3. A template under `pyeffic/templates/<name>/` registered in
   `scaffold.TEMPLATE_DIRS`.
4. Tests in `tests/test_<target>gen.py`.

## Style

- Python 3.10+, standard library only — no new dependencies.
- Type annotations on public functions.
- 4-space indent, no tabs.
- Follow the patterns in neighbouring files.
- Do not add or remove comments unless asked.

## Commit messages

Conventional commits, focused on *why*:

```
feat(frontend): accept .ge.ts as a TypeScript-flavour extension
fix(emitter): escape C# reserved words in parameter positions
docs: add the compatibility promise
```

## Reporting bugs

Include `ge doctor` output, the `.ge` file that fails, and the exact command.
A minimal reproduction is worth more than a description.

## Security

See [`SECURITY.md`](SECURITY.md). Do not open public issues for
vulnerabilities.
