# GE Compatibility Promise

**Status:** draft, normative once released as 1.0.

This document defines what will never break, what may break, and what notice
you get. It exists so you can upgrade GE without re-reading a changelog
looking for landmines.

The short version: **a `.ge` program that builds today keeps building and
keeps producing the same output, for every future release, within its
edition.**

---

## 1. What the promise covers

### Covered — will not break without an edition

| Surface | Examples |
|---|---|
| **Syntax** | Every construct in the language reference for your edition |
| **Semantics** | What a program computes — the same input yields the same output |
| **CLI** | Every command, flag, and argument in `ge --help` |
| **`ge.toml`** | Every key and value documented for your edition |
| **Diagnostic codes** | `GE001`–`GE011` keep their meaning; codes are never reused |
| **Generated ABI** | `extern "C"` symbol names and signatures for cross-backend calls |
| **Build layout** | `build/<target>/{backend,obj,bin}` paths |
| **Scaffolds** | `ge create` templates keep working; existing projects keep building |

### Not covered

| Surface | Why |
|---|---|
| **Emitted code text** | Backends may improve output. Use `ge golden` if you diff it — that is what it is for. |
| **Diagnostic wording** | Messages improve. Codes and locations are stable. |
| **Provisional APIs** | Listed in `PROVISIONAL.md`; these are explicitly excluded (PEP 411 model). |
| **Unstable features** | Behind `[unstable] features = [...]`; no promise until stabilized. |
| **Performance** | May improve or regress between releases; tracked against budgets, not promised. |
| **Compiler internals** | `pyeffic.*` Python modules are not an API. |
| **Behavior that was a bug** | See §5 — bugs get fixed, with an opt-out when the fix is observable. |

---

## 2. Editions

Breaking changes are never made in place. They go into a new **edition**,
and editions are opt-in.

```toml
# ge.toml
[project]
name = "myapp"
edition = "2026"      # absent means the original edition
```

Rules:

1. **Opt-in.** A project keeps its edition until you change it. Nothing
   changes under you on upgrade.
2. **Editions interoperate.** A module on edition 2026 must be importable
   from a project on edition 2024, and vice versa, with neither edited.
3. **Editions are skin deep.** All editions lower to the same IR and produce
   the same native code for equivalent programs. An edition is a
   parse-and-analyse switch, not a second compiler.
4. **New projects get the newest edition.** `ge create` selects the current
   stable edition.
5. **Editions are rare.** At most one every 18 months, and only when there
   is a change worth making. Most releases add features and change no
   editions at all.

### Why opt-in matters

The alternative — changing behavior in a minor release — forces every user
to migrate on the vendor's schedule. Opt-in editions let a project migrate
when it has time, while its dependencies migrate on theirs.

---

## 3. Deprecation

When something should stop being used:

1. It is marked deprecated with a **`since`** version and a **`remove`**
   version.
2. Building emits a warning naming the replacement.
3. The deprecation lasts **at least two minor releases**.
4. Removal only happens at the `remove` version, and only in a release whose
   notes call it out.

```python
# GE warns:
#   GE020: `old_api` is deprecated since 0.8.0 and will be removed in 0.10.0.
#          Use `new_api` instead.
```

Set `GE_DEPRECATED_AS_ERROR=1` to make deprecation warnings fatal in CI, so
a project can prove it has no deprecated usage before the removal lands.

Deprecations are tracked in `DEPRECATIONS.md` with their `since`/`remove`
bounds. CI fails if a `remove` version has passed and the form still exists.

---

## 4. Adding features (the safe direction)

Additions are allowed in any release, subject to two rules:

1. **No shadowing.** A new keyword, builtin, or `ge.toml` key must not change
   the meaning of an existing program. If it would, it belongs in an edition.
2. **No new required anything.** New flags default to the old behavior. New
   `ge.toml` keys are optional. New syntax does not invalidate old syntax.

The classic failure this prevents is a new keyword: adding `async` as a
keyword would break `let async = 1;`. That is precisely the change Rust
deferred to an edition, and the reason rule 1 exists.

---

## 5. Fixing bugs (the unavoidable direction)

Some fixes change observable behavior. These are handled in three tiers:

| Tier | Example | Handling |
|---|---|---|
| **Invisible** | A crash on invalid input becomes a diagnostic | No process needed |
| **Observable, uncontroversial** | Wrong arithmetic result | Fix it, note it in the changelog under "Fixed" |
| **Observable, defensible either way** | Rounding, ordering, tie-breaking | Fix it **and** ship a named opt-out |

For tier 3 the opt-out is named after the release that introduced the change:

```bash
GE_COMPAT_2026_ROUNDING=legacy ge build main.ge
```

The setting is documented in `COMPAT.md` with the reasoning, and is kept for
at least two editions. Go's decade of `GODEBUG` experience is the model —
including its lesson that settings were removed too eagerly, so ours are
kept longer than feels necessary.

---

## 6. Semver for a compiler

| Change | Version bump |
|---|---|
| Bug fix, no observable change | patch |
| New feature, no breakage | minor |
| New deprecation warning | minor |
| **Removal at a published `remove` version** | minor, called out in notes |
| Anything that breaks a covered surface without an edition | **never** |
| New edition | major |

A major version does **not** mean "everything breaks". It means an edition
exists. Projects on older editions are unaffected.

---

## 7. How this is enforced

The promise is only as good as the tests behind it. Every release runs:

| Check | Command | Catches |
|---|---|---|
| Cross-backend agreement | `ge diff tests/differential` | Semantic drift from Python |
| Emitted-code stability | `ge golden --check` | Silent emitter churn |
| Edition freeze | `ge golden --check --edition` | Old editions compiling differently |
| CLI surface | `ge api-check` | Renamed or removed flags |
| Full suite | `python -m unittest discover tests` | Everything else |

A release is **blocked** if any of these fail. `docs/RELEASE_CHECKLIST.md`
is the normative gate.

---

## 8. Escape hatches that keep this honest

The promise is absolute only within its scope. Two documents define the
edges, and both are required reading before you depend on something:

- **`PROVISIONAL.md`** — APIs excluded from the promise. Everything here may
  change in any release.
- **`KNOWN_GAPS.md`** — behaviors known to be incomplete or inconsistent,
  each with an owner and a reopen trigger.

If something is not in those two documents and is a covered surface, it is
promised. If it is in them, it is not.

---

## 9. What you can rely on today

GE is pre-1.0. Until 1.0 ships, this document describes the *intent* and the
mechanisms being built, not a guarantee already in force. The mechanisms
land in this order:

1. `ge golden --check` — **landed**
2. `ge diff` — **landed**
3. `ge api-check` — in progress
4. Edition field in `ge.toml` — planned
5. Deprecation registry — planned
6. `ge fix --edition` — planned

Track progress in `docs/PRODUCTION_PLAN.md` §Phase 1 and
`docs/STABILITY.md` §3.
