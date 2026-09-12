# {app_name}

Full-stack web application built with the GE programming language.

## Architecture

```
{app_name}/
  app/
    memory/       Rust — request bounds, buffer capacities
      limits.ge.py
      buffer.ge.py
    core/         Rust — computation, one function per file
      add.ge.py  multiply.ge.py  factorial.ge.py
      fibonacci.ge.py  is_prime.ge.py
    main.ge.py    aggregator
  web/
    server.ge.py  Rust backend (HTTP API + static SPA)
    frontend/     React 19 + TypeScript + Vite (generated, then yours)
      src/App.tsx
      src/api/client.ts
      src/components/Ge*.tsx   one component per file
  ui/
    main.ge.ui    declarative UI — source of truth for the frontend
  tests/
```

### Layers

| Layer | Language | Responsibility |
|-------|----------|----------------|
| Frontend | React + TypeScript | UI, calls `/api/call` |
| Backend | Rust | HTTP, dispatch, bounds enforcement |
| Memory | Rust | clamp inputs, cap buffers |
| Core | Rust | pure computation |

### Data flow

```
browser -> POST /api/call {name, args}
             |
             v
       Rust backend -> mem_clamp_arg(args) -> core function
             |
             v
       JSON {ok, value} -> React state -> GeText/GeValue
```

## Build output layout

Everything lands under `build/`, bucketed by platform so a multi-target
project stays readable:

```
build/
  desktop/    native desktop build
    backend/    generated native sources
    obj/        object files
    bin/        executables
  web/        web build
    backend/    generated Rust backend
    bin/        server executable
  mobile/     Flutter project
    backend/  ui/  lib/
```

## Build

```bash
ge build web/server.ge.py --run      # compile the Rust backend
ge react ui/main.ge.ui --app-name {app_name}   # generate the React frontend
cd web/frontend && npm install && npm run build   # bundle the SPA
```

`ge build` compiles the backend straight from the GE sources. `ge react`
generates the frontend from the UI DSL, and only writes files that do not
already exist unless you pass `--force`.

## Frontend workflow

`ui/main.ge.ui` is the source of truth for the layout:

```bash
ge react ui/main.ge.ui --app-name {app_name}   # regenerate (keeps edits)
ge react ui/main.ge.ui --force                 # regenerate, overwrite
cd web/frontend && npm run dev                 # dev server, proxies /api
```

Files under `web/frontend/src` are ordinary React/TypeScript. Edit them
freely: regeneration only writes files that do not exist unless `--force`.

## TypeScript source support

Any module can be written in TypeScript flavour instead of Python flavour.
Both lower to the same IR, so both compile to the same native code:

```
app/core/add.ge.py        Python flavour
app/core/add.ts.ge.py     TypeScript flavour (same file name, .ts.ge)
app/core/add.ge.ts        TypeScript flavour (alternate extension)
```

TypeScript flavour example:

```typescript
export function add(a: number, b: number): number {
    return a + b;
}
```

## Test

```bash
python -m unittest discover tests
```
