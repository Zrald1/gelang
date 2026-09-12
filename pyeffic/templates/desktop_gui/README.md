# {app_name}

Native desktop application built with the GE programming language.

## Architecture

```
{app_name}/
  app/
    memory/     Rust — bounded state, buffers, limits
      limits.ge.py    input bounds + clamping
      buffer.ge.py    fixed-size buffer capacities
      state.ge.py     initial state + operation cycling
    core/       C++  — computation, one function per file
      add.ge.py  multiply.ge.py  factorial.ge.py
      fibonacci.ge.py  is_prime.ge.py  gcd.ge.py  power.ge.py
    ui/         C++  — design, one concern per file
      theme.ge.py     colors, font sizes, spacing
      layout.ge.py    geometry math
      widgets.ge.py   drawing primitives
      render.ge.py    frame orchestrator
    main.ge.py  aggregator (single import surface)
  desktop/
    main.ge.py  Rust shell — window, event loop, input
  tests/        unit tests for all three layers
```

### Layer responsibilities

| Layer | Language | Responsibility | Why |
|-------|----------|----------------|-----|
| Shell | Rust | window, message loop, input, state | memory safety — no leaks, no use-after-free |
| Core | C++ | computation (factorial, fibonacci, gcd, ...) | raw speed for hot math |
| UI | C++ | theme, layout, widgets, rendering | native GDI, no runtime, small binary |

The Rust shell holds **fixed-size scalar state only**. Nothing grows at
runtime, so memory use is constant no matter how long the app runs.

### Data flow

```
keyboard -> Rust wnd_proc -> mem_step_up / run_op
                              |            |
                              |            +-> C++ core  (factorial, ...)
                              +-> bounded state (G_INPUT, G_RESULT, G_OP)
                                        |
                              WM_PAINT  v
                        Rust calls ui_draw_frame(hdc, w, h, ...)
                                        |
                              C++ UI draws: bg -> grid -> sidebar -> card
```

## Build

```bash
ge build desktop/main.ge.py --run     # one command: C++ object + Rust exe
ge build desktop/main.ge.py -o out    # custom output dir
```

`ge build` detects that the program mixes backends and links them itself:
it emits the C++ functions in library mode (`extern "C"`), compiles them to
an object file, emits the Rust shell with matching `extern "C"` declarations,
and links one executable. No project build script is needed.

## Test

```bash
python -m unittest discover tests
```

## Controls

| Key | Action |
|-----|--------|
| Up / Down | change input (clamped by memory layer) |
| Enter | run the selected operation (C++ core) |
| F / P / G | fibonacci / is_prime / gcd |
| Esc | quit |

## Adding a core function

1. Create `app/core/my_func.ge.py`:

   ```python
   from pyeffic.backends import cpp

   @cpp
   def my_func(x: int) -> int:
       return x * 2
   ```

2. Re-export it in `app/main.ge.py`.
3. Declare it in the FFI block of `desktop/main.ge.py`:

   ```rust
   fn my_func(x: i64) -> i64;
   ```

4. Call it from the Rust shell and add a test.

## Adding a UI element

1. Add tokens to `app/ui/theme.ge.py` if you need new colors/sizes.
2. Add geometry to `app/ui/layout.ge.py`.
3. Add a drawing primitive to `app/ui/widgets.ge.py`.
4. Compose it in `app/ui/render.ge.py`.
