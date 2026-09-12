# Differential test corpus

Each file here is a small program that must produce the **same output under
CPython and under every native backend**. That makes cross-backend agreement
a checkable property instead of an assumption.

```bash
ge diff tests/differential                    # all installed backends
ge diff tests/differential --backends rust,cpp
ge diff tests/differential -v                 # per-case detail
```

## Writing a case

A case is a `.ge`, `.ge.py`, or `.ge.ts` file with a `main()` that prints.
Directives go in the first lines:

```python
# @expect: 42          expected stdout (skips the CPython run)
# @expect: 7           a second output line
# @skip: cpp           exclude a backend
# @only: rust,go       run only these backends
# @exit: 1             expected exit code
```

Without `@expect`, CPython is the oracle: the harness executes the lowered
program and every backend must match it byte-for-byte (trailing whitespace
ignored).

## Why this exists

The same IR feeds six emitters, so comparing them is nearly free — and it is
the only way to catch backend-specific codegen bugs. `scriptc` uses Node.js
the same way; Rustlantis found 22 previously-unknown Rust compiler bugs by
comparing backends against each other.

It has already paid for itself: the harness found that the Go backend wrote
its binary next to the source instead of into `build/<target>/bin/`.
