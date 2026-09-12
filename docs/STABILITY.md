# GE Stability & Backward Compatibility

How to keep existing programs compiling when the language, the CLI, and the
emitters keep changing.

This is the hardest requirement in the project. Shipping features is easy;
shipping features *without breaking anyone* is what separates a language
people adopt from one they abandon.

Grounded in how Rust, Go, Python, Kotlin, and bento actually solve it.

---

## 1. The core problem

Every change to GE lands in one of five places, and each can break a
different thing:

| What changes | Who breaks | How it breaks |
|---|---|---|
| Language syntax | `.ge` authors | Source no longer parses |
| Language semantics | `.ge` authors | Source parses, behaves differently |
| CLI surface | build scripts, CI | Flags renamed or removed |
| Emitter output | anything diffing generated code | Silent text churn |
| Generated ABI | mixed Rust+C++ programs | Link failure |
| Scaffold/templates | new projects | Old projects diverge |

The dangerous ones are **semantics** and **ABI**: they break silently or at
link time, not at the keyboard.

### What must never break

1. A `.ge` file that compiled on version N must compile on N+1.
2. It must produce the **same output** on N+1, unless the change is
   announced as a behavior change with an opt-out.
3. A `ge.toml` project must keep building without edits.
4. Generated code must stay diff-stable so review diffs mean something.

### What may break (with process)

- Experimental features
- Documented *Provisional* APIs (PEP 411 carve-out)
- Behavior that was a bug
- Anything behind an unreleased edition

---

## 2. The mechanisms, and which to adopt

### 2.1 Editions — adopt (Rust's model)

The single most important mechanism. Rust's rule:

> Once a feature is released through stable, contributors will continue to
> support that feature for all future releases. When there are
> backwards-incompatible changes, they are pushed into the next edition.
> Since editions are opt-in, existing crates won't use the changes unless
> they explicitly migrate.

Three properties make it work, and all three are load-bearing:

1. **Opt-in per project** — `ge.toml` gets `edition = "2026"`. No edition
   key means the original edition.
2. **Cross-edition interop is mandatory** — "crates in one edition must
   seamlessly interoperate with those compiled with other editions". A
   project on edition 2026 must be importable by one on 2024.
3. **Editions are skin deep** — "All Rust code, regardless of edition, will
   ultimately compile down to the same internal representation." That is
   exactly GE's situation: every flavour already lowers to one IR. Editions
   become a parse-time and analysis-time switch, not a second compiler.

**Why this fits GE specifically:** the hybrid frontend already dispatches
per chunk. An edition is one more dispatch dimension, and the shared IR
means the backends never need to know about editions at all.

### 2.2 A compatibility promise — adopt (Go's model)

Go published a short document and then treated it as binding for a decade:

> It is intended that programs written to the Go 1 specification will
> continue to compile and run correctly, unchanged, over the lifetime of
> that specification.

The lesson from Go's retrospective is that **boring is the feature**:

> We released Go 1 and its compatibility promise to remove the excitement,
> so that new releases of Go would be boring.

GE needs the same document, scoped to its own surface: the `.ge` syntax, the
CLI, and the generated ABI.

### 2.3 Golden lowering corpus — adopt (bento's model)

bento commits three files per case and holds all three against each other:

- `.ts` — the source
- `.golden` — the generated code, committed so a compiler change is a
  reviewable diff
- `.out` — what the program prints

Two tests: the lowering must reproduce `.golden` byte-for-byte, and
`.golden` must still print `.out`. The comment in their harness states the
value precisely:

> The lowering test proves bento produces the code we reviewed, and the run
> test proves that code still behaves, so a runtime regression that keeps
> compiling is caught by the bytes it prints.

This is the highest-value artifact for the "don't break old code" goal, and
GE is one step from having it: `ge diff` already covers the `.out` half.

### 2.4 API surface check — adopt (Kotlin / Go apidiff model)

Kotlin's `binary-compatibility-validator` dumps the public API to a
committed file and fails the build when it changes:

- `apiDump` writes `api/*.api`
- `apiCheck` fails if the dump differs
- Changing the API is a *deliberate* act: run `apiDump`, review the diff,
  commit it

Go's `apidiff` classifies changes as compatible (minor bump) or incompatible
(major bump). GE needs both halves:

- **CLI surface**: every flag and command, dumped and checked
- **Language surface**: the accepted syntax, dumped as a grammar summary

### 2.5 Deprecation with deadlines — adopt

The `deprecate` crate's model is the right one: every deprecation carries a
`since` version and a `remove` version, validated so `remove > since`, and CI
checks the lifecycle policy:

> An API is active while `since <= current < remove` and is overdue once
> `current >= remove`.

Python's PEP 387 supplies the policy floor:

> Unless it is going through the deprecation process, the behavior of an API
> must not change in an incompatible fashion between any two consecutive
> releases.

and the release-cadence rule: a deprecation must span at least two years of
releases. GE should state the same floor in release terms: **a deprecation
must span at least two minor releases**, and a `GE_DEPRECATED_AS_ERROR=1`
env var should make warnings fatal in CI.

### 2.6 Automated migration — adopt (cargo fix's model)

`cargo fix --edition` works by running the compiler with special lints
enabled that detect code which would not compile in the next edition. The
lints carry machine-applicable suggestions. Cargo applies them, re-checks,
and **backs out if the fixes fail**.

The detail that makes it usable: the fixes produce code valid in *both* the
current and the next edition, so migration can be done incrementally while
still on the old edition.

GE needs `ge fix --edition` with the same contract: apply, verify, back out
on failure, and leave the source valid in both editions.

### 2.7 Behavior opt-outs — adopt narrowly (Go's GODEBUG)

Some fixes *cannot* preserve behavior — a bug fix changes an answer, a
sort becomes stable, a rounding rule is corrected. Go's answer is a
`GODEBUG` setting that keeps old programs running the old way:

> There are times when we cannot maintain strict compatibility, such as when
> changing sort algorithms or fixing clear bugs, when existing code depends
> on the old algorithm or the buggy behavior.

The lesson Go draws from a decade of this: settings work, but they were
**too aggressive about removing them**. So GE should use this sparingly,
name the setting after the release that introduced the change, and keep
settings for longer than feels comfortable.

### 2.8 Feature gates — adopt

Rust keeps unstable features behind `#![feature(...)]` so incomplete work
cannot be depended on:

> Features that are still under development are usable only on the nightly
> channel, preventing de facto lock-in and thus leaving us free to iterate
> in ways that involve code breakage before stabilizing the feature.

GE equivalent: `ge.toml` gets `[unstable] features = ["async"]`, and using
an unstable feature without opting in is an error. This is what buys the
freedom to break things before they are stable.

---

## 3. What GE needs to build

Ordered by leverage. Each item is small and independently useful.

### Tier 1 — the non-negotiables

| # | Artifact | What it does |
|---|---|---|
| S1 | `docs/COMPATIBILITY.md` | The promise. What will never break, what may, with what notice. |
| S2 | `ge.toml` `edition = "2026"` field | Opt-in breaking changes, defaulted to the original edition |
| S3 | `tests/golden/` corpus | `.ge` + `.golden` (emitted per backend) + `.out`, all three held against each other |
| S4 | `ge api-dump` / `ge api-check` | Golden CLI + language surface; CI fails on unexplained change |
| S5 | `ge fix --edition` | Apply migration lints, verify, back out on failure |
| S6 | Deprecation registry | `since` / `remove` bounds per deprecated form; CI checks overdue entries |
| S7 | `docs/DEPRECATION.md` | The policy: two minor releases minimum, `GE_DEPRECATED_AS_ERROR=1` |

### Tier 2 — makes it operable

| # | Artifact | What it does |
|---|---|---|
| S8 | `ge check --edition next` | Warns about code that will break in the next edition, while still on the current one |
| S9 | Compatibility CI job | Runs the *previous release* over the golden corpus and asserts it still passes |
| S10 | `GE_COMPAT=` behavior switches | Narrow, named-after-release opt-outs for unavoidable behavior changes |
| S11 | `[unstable] features` gate | Explicit opt-in for incomplete features |
| S12 | Provisional markers | `docs/PROVISIONAL.md` listing APIs excluded from the promise (PEP 411) |

### Tier 3 — maturity signals

| # | Artifact | What it does |
|---|---|---|
| S13 | Semver policy for a *language* | What counts as major / minor / patch when the product is a compiler |
| S14 | Migration guide per edition | `docs/editions/2026.md` — what changed and how to move |
| S15 | Machine-readable diagnostics | `ge analyze --json` with fix suggestions, so editors and agents can auto-apply |

---

## 4. The test that proves it

A compatibility claim is worthless without a test that can fail. Three
layers, each catching a different class of break:

### Layer 1 — Golden lowering (catches emitter churn)

```
tests/golden/<case>/
  main.ge            source
  rust.golden        expected emitted Rust
  cpp.golden         expected emitted C++
  csharp.golden      ...
  zig.golden
  go.golden
  kotlin.golden
  expected.out       what the program prints
```

`python -m pyeffic.golden --check` fails if emitted code differs from the
committed golden, and separately compiles + runs the golden to confirm it
still prints `expected.out`. Regeneration is `--update`, always reviewed,
never automatic.

**This catches:** an emitter change that alters generated code for existing
programs, even if it still compiles and still works. That is exactly the
"silent churn" class.

### Layer 2 — Edition freeze (catches syntax and semantics drift)

For each released edition, freeze a corpus:

```
tests/editions/2026/
  *.ge               programs written to that edition
  manifest.json      expected diagnostics + expected output per program
```

CI compiles every older edition's corpus with the current compiler and
asserts identical output. A new edition may not change how an old edition
compiles.

**This catches:** a new keyword that shadows an old identifier, a precedence
change, a semantics change — the Rust `async` problem, caught automatically.

### Layer 3 — API surface (catches CLI and language surface drift)

```
api/cli.api        every command, flag, argument
api/lang.api       accepted syntax surface summary
api/diagnostics.api  every GE*** code and its meaning
```

`ge api-check` fails on any diff. Adding a flag is a deliberate act:
`ge api-dump`, review the diff, commit.

**This catches:** a renamed flag breaking someone's CI, a removed command, a
reused diagnostic code changing meaning.

---

## 5. The policy, in plain terms

Once Tier 1 lands, these become the rules:

1. **A released `.ge` program keeps compiling and keeps printing the same
   thing**, for every future release, within its edition.
2. **Breaking changes go in a new edition.** Never in a patch or minor
   release of an existing edition.
3. **Editions interoperate.** A module on edition 2026 must be importable
   from one on 2024 without either changing.
4. **Deprecations last at least two minor releases**, carry a `remove`
   version, and warn with a suggested replacement.
5. **Unstable features require explicit opt-in** and carry no promise.
6. **Behavior changes that cannot preserve compatibility** get a named
   opt-out setting and a changelog entry explaining why the fix matters.
7. **Every release runs the full golden + edition + API check suite.** A
   failure blocks the tag.
8. **`KNOWN_GAPS.md` and `PROVISIONAL.md` are the only places a promise does
   not apply** — anything not listed there is covered.

Rule 3 is the one most likely to be violated by accident and the most
important to test: it is what lets one project migrate without forcing its
dependencies to.

---

## 6. Sequenced

| Step | Deliverable | Effort | Unblocks |
|---|---|---|---|
| 1 | `docs/COMPATIBILITY.md` — write the promise down | hours | Everything else; makes the claim checkable |
| 2 | `ge api-dump` / `ge api-check` + `api/*.api` | 2–3 days | CLI stability, immediately |
| 3 | `tests/golden/` + `pyeffic.golden` + CI job | 1 week | Emitter stability; reuses `ge diff`'s runner |
| 4 | `edition` field in `ge.toml` + edition-freeze corpus | 1 week | Syntax/semantics stability |
| 5 | Deprecation registry + policy + CI check | 3–4 days | Safe removal of old forms |
| 6 | `ge fix --edition` with apply/verify/back-out | 1–2 weeks | Making migration cheap |
| 7 | `GE_COMPAT=` switches, `[unstable]` gate | 1 week | Freedom to fix bugs |

Steps 1–3 are the load-bearing ones and take under three weeks combined.
They convert "we try not to break things" into "a test fails if we do".

---

## 7. How this connects to the rest of the plan

- **`ge diff`** (Phase 1, already landed) is the runtime half of the golden
  corpus. The golden work adds the *lowering* half.
- **Snapshot baselines** (Phase 1.2) and **golden lowering** are the same
  mechanism; build them once.
- **`ge check`** (Phase 2.1) is the engine `ge check --edition next` needs.
- **`ge fix --edition`** needs machine-applicable diagnostics, which is
  Phase 2.5's error-message work.
- **`KNOWN_GAPS.md`** (Phase 0.2) and **`PROVISIONAL.md`** (S12) are the two
  escape hatches that make the promise honest rather than absolute.

The ordering matters: the promise document comes first because it defines
what the tests must assert.
