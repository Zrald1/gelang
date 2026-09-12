# GE Production Plan

A staged plan to take GE from a strong prototype to something other
programmers can install, trust, and depend on.

Written against the current tree (1147 tests passing) and grounded in how
comparable projects actually ship: mypyc, py2many, reflaxe.go, Solidity,
scriptc, Go, and the Rust release-engineering playbook.

---

## 1. Where we actually are

### What works today

| Capability | Evidence |
|---|---|
| One `.ge` file, mixed Python + TypeScript, named blocks | `tests/test_hybrid_frontend.py`, `tests/test_named_blocks.py` |
| Six native backends (Rust, C++, C#, Zig, Go, Kotlin) | `tests/test_conceptual_100.py` — 600 compile-and-run cases |
| Mixed-backend link into one binary | `tests/test_mixed_build.py` — Rust shell + C++ object, one exe |
| Two UI ecosystems from one DSL | `ge flutter` (Dart), `ge react` (React 19 + TS + Vite) |
| Organized build output | `tests/test_build_layout.py` — `build/{desktop,web,mobile}/` |
| Target-keyword safety | `tests/test_keyword_escaping.py` — `base`, `double`, `match` |
| 1147 tests, compile-and-run included | `python -m unittest discover tests` |

### What is not yet true

- No differential testing. Nothing asserts Rust and C++ agree on the same input.
- Type checking is heuristic inference, not a sound type system.
- Silent CPython fallbacks: unsupported functions still "build".
- No concurrency, no async, thin standard library.
- No editor integration (no LSP, no tree-sitter grammar).
- No package manager, no dependency resolution.
- No reproducible builds, no SBOM, no signed artifacts.
- Windows-first templates; macOS/Linux paths untested.
- No published per-backend maturity statement.

### Where we sit versus comparable projects

| Project | Self-described status |
|---|---|
| mypyc | "alpha software… only recommended for production use cases with careful testing" |
| py2many | C++ "Production Ready"; Rust primary focus; Kotlin/Go/Dart "Beta"; Zig "Experimental" |
| reflaxe.go | Has a *release-readiness checklist* with a production-caveat scoreboard |

We are roughly at mypyc's tier today, with a broader backend spread but
fewer safeguards. Both of those projects publish an explicit maturity
statement. **We should too, and that is step one.**

---

## 2. The strategic problem to solve first

Research on new-language adoption identified a barrier that did not exist
five years ago, and it is worth naming because it changes the whole plan:

> "Models need training data. Training data comes from usage. Usage requires
> good AI support. Good AI support requires training data."
> — *New Programming Languages Have an AI Problem*

New languages now compete on AI support, and that is circular. Most
languages cannot break the loop.

**GE has an unusual structural answer to this, and the plan should lean on
it hard:** GE's input syntax *is* Python and TypeScript. Models already
know those syntaxes cold. An assistant writing a `.ge` file is not guessing
at an unknown grammar — it is writing Python or TypeScript with type
annotations, which is squarely in-distribution. The named-block form gives
it a bounded unit with an explicit call contract, and the compiler is the
verifier that catches a hallucinated signature at build time.

This is GE's single strongest differentiator. Everything below is arranged
so that claim becomes *provable* rather than aspirational.

The second research finding to internalise:

> Institutional friction — perceived stability and governance — is the
> **strongest** predictor of tool abandonment, ahead of learning effort.
> — *The Invisible Adoption Tax*

So governance and stability signals are not paperwork. They are the
highest-leverage adoption work after correctness.

---

## 3. Phase 0 — Honesty and guardrails

**Goal:** a user can tell exactly what they are getting.
**Duration:** 1–2 weeks. **This gates everything else.**

| # | Deliverable | Why | Exit criteria |
|---|---|---|---|
| 0.1 | `docs/BACKEND_STATUS.md` — per-backend maturity matrix | py2many's `LANGUAGES.md` is why people trust its status claims | Every backend labelled Production / Beta / Experimental with the test evidence that justifies it |
| 0.2 | `docs/KNOWN_GAPS.md` — production caveat scoreboard | reflaxe.go treats this as a release gate | Each row has **owner, decision, evidence link, reopen trigger** |
| 0.3 | Fail-closed fallbacks | A silently-falling-back function is a correctness hazard | `--allow-fallback` opt-in; default build *fails* on unsupported units |
| 0.4 | `GE011`/fallback warnings surfaced in the build summary | Today they scroll past | Build ends with an explicit "N functions used CPython fallback" line |
| 0.5 | Security policy + `SECURITY.md` | Prerequisite for anyone shipping this | Published disclosure path |

**Do not skip 0.3.** It converts "it built" from a claim into a guarantee,
and it is what makes the differential harness in Phase 1 meaningful.

---

## 4. Phase 1 — Verification

**Goal:** prove the compiler is correct, not just that it runs.
**Duration:** 6 weeks. **This is the highest-value phase.**

### 4.1 Differential test harness (the centrepiece) — **landed**

The technique is settled practice. `scriptc` uses Node.js as a
byte-for-byte oracle across stdout, stderr, and exit code, with separate
lanes for backend parity, cross-platform parity, and sanitizers. Rustlantis
found 22 previously-unknown Rust compiler bugs purely by comparing backends
against each other.

GE is unusually well placed: **we already emit N backends from one IR, so
cross-backend comparison is nearly free.** This is the capability almost
nobody else has, and it is currently unused.

Build three lanes:

| Lane | Oracle | What it catches |
|---|---|---|
| **Reference** | CPython executes the same `.ge` | Emitter semantic drift from Python semantics |
| **Parity** | Every available backend vs every other | Backend-specific codegen bugs |
| **Sanitizer** | C++/Rust under ASan/UBSan | Memory errors in emitted code |

Delivered:

- `pyeffic/difftest.py` — reference lane (CPython) + parity lane (every backend)
- `ge diff <file-or-dir>` / `python -m pyeffic.difftest`
- `tests/differential/` corpus with `@expect` / `@skip` / `@only` / `@exit` directives
- `tests/test_difftest.py` — 22 tests, including a deliberate-mismatch case
- First run: **30/30 comparisons agree** across all six backends

Already paid for itself — it found that the Go backend wrote its binary next
to the source instead of into `build/<target>/bin/`.

Still to do:

- Grow the corpus from 5 cases to ≥500 (seed from `test_conceptual_100`)
- CI lane per backend; a backend that is not installed is skipped, not failed
- Sanitizer lane (ASan/UBSan) for the C++ and Rust outputs

**Exit criteria:** ≥500 programs, all backends agree, running in CI on every push.

### 4.2 Snapshot baselines

reflaxe.go runs `run-snapshots.py` and `run-semantic-diff.py` as release
gates. Emitted code should be stable: a diff means something changed on
purpose.

- `tests/snapshots/` — emitted Rust/C++/C#/Zig/Go/Kotlin for a fixed corpus
- `python -m pyeffic.snapshot --check` fails on unexplained drift
- Reviewed and regenerated deliberately, never automatically

### 4.3 Determinism check

Go's reproducible-toolchain work is the model: same inputs, same bytes.

- `python -m pyeffic.determinism` — emit twice, compare hashes
- Catches dict-ordering leaks and timestamp injection in emitters

### 4.4 Property and fuzz testing

- Hypothesis-style generation of `.ge` programs from a grammar
- Round-trip property: `ge → IR → emit → compile → run` must not crash the compiler
- Rustlantis-style randomised differential testing once 4.1 exists

**Exit criteria for Phase 1:** a public, re-runnable command that proves
backend agreement, plus snapshots and determinism gating CI.

---

## 5. Phase 2 — Developer experience

**Goal:** pleasant to use in an editor. **Duration:** 6 weeks.

The LSP research is unambiguous: you write **one** language server, and
VS Code, Neovim, Helix, Emacs, Sublime, Zed, and JetBrains all plug in.
That is `M` languages × `N` editors solved with `M` servers.

| # | Deliverable | Notes |
|---|---|---|
| 2.1 | `ge check` — static analysis, no emission | Fast feedback; also the LSP backend |
| 2.2 | `ge lsp` — language server over stdio | Diagnostics, hover, go-to-definition, completion |
| 2.3 | `tree-sitter-ge` grammar | Syntax highlighting everywhere, independent of the LSP |
| 2.4 | VS Code extension | Thin client around `ge lsp` |
| 2.5 | Error message quality pass | Every diagnostic: what, where, why, and a suggested fix |
| 2.6 | `ge fmt` | Deterministic formatter; removes style arguments from review |
| 2.7 | `ge analyze --json` | Machine-readable diagnostics for AI agents and CI |

**Exit criteria:** a `.ge` file in VS Code shows errors on save, hover
types, and jump to definition; `ge check` runs in under a second on a
10k-line project.

---

## 6. Phase 3 — Distribution and ecosystem

**Goal:** someone else can install it and use someone else's code.
**Duration:** 8 weeks.

### 6.1 Package manager — Git first, registry never (initially)

The Zig experience is instructive: a registry drags in manifest parsers,
PURL types, advisory databases, and 3 AM pager duty. The pragmatic path,
argued well in *Designing a Package Manager When You Don't Have One*, is
Git as the transport:

- `ge.toml` declares dependencies as `{ git = "...", tag = "v1.2.3" }`
- `ge.lock` pins exact revisions and content hashes
- Local `path` dependencies for development
- No registry, no semver resolution, no CDN to expire

Deliverables: `ge add`, `ge install`, `ge update`, lockfile format spec,
and a documented PURL type proposal so SBOM tooling can reference GE packages.

### 6.2 Reproducible, signed releases

The Rust 2026 playbook is the checklist:

1. Pin toolchains (`rust-toolchain.toml` equivalent for each target)
2. Lock dependencies; build with `--locked`
3. Deterministic builds (Phase 4.3 gives the guardrail)
4. Generate a CycloneDX SBOM
5. Generate SLSA-style provenance
6. Sign artifacts (keyless cosign)
7. **Publish the verification commands in the release notes**

That last step is what turns a signature into trust.

### 6.3 Release process

Model on the Solidity and reflaxe.go checklists:

- `docs/RELEASE_CHECKLIST.md`, normative, run in order
- A release issue per cut; unticked box = no tag
- Generated changelog from conventional commits
- Semver policy: what counts as breaking for a *language*

**Exit criteria:** `pip install ge-lang`, `ge new`, `ge add`, `ge build`
works on a clean machine, and every release artifact is signed with
published verification steps.

---

## 7. Phase 4 — Documentation and governance

**Goal:** remove the institutional friction that research says kills
adoption. **Duration:** 4 weeks, overlapping Phase 3.

| # | Document | Purpose |
|---|---|---|
| 4.1 | Language reference | Normative spec of the supported subset, per flavour |
| 4.2 | Cookbook | Task-oriented: "call C++ from Rust", "add a backend", "migrate a Python module" |
| 4.3 | Migration guides | Python → GE, TypeScript → GE, GE → each target |
| 4.4 | Backend authoring guide | How to add a 7th backend — the N×M promise, made concrete |
| 4.5 | `GOVERNANCE.md` | Who decides, how, and how to change it |
| 4.6 | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` | Standard open-source hygiene |
| 4.7 | Stability tiers | "Stable / Preview / Experimental" applied to syntax, CLI, and each backend |
| 4.8 | Website with a 5-minute quickstart | Time-to-first-binary is the adoption metric that matters |

---

## 8. Phase 5 — Hardening (continuous)

| # | Item | Notes |
|---|---|---|
| 5.1 | Performance budgets in CI | reflaxe.go runs perf gates as a release contract; drift is a signal, not always a blocker |
| 5.2 | Long-running fuzzing | Nightly, corpus-growing |
| 5.3 | Cross-platform CI | Linux + macOS + Windows lanes; today is Windows-first |
| 5.4 | Concurrency and async | The largest missing language feature; needs a design doc before code |
| 5.5 | Standard library growth | Drive from real programs, not from a wishlist |
| 5.6 | Error-recovery hardening | A bad `.ge` file must produce a diagnostic, never a traceback |
| 5.7 | `.ge` package format versioning | Freeze it before third parties depend on it |

---

## 9. Sequenced summary

| Phase | Weeks | Theme | Gate |
|---|---|---|---|
| 0 | 1–2 | Honesty | Maturity matrix + fail-closed fallbacks published |
| 1 | 3–8 | **Verification** | Differential harness green across all backends, in CI |
| 2 | 9–14 | Developer experience | LSP + tree-sitter + `ge check` shipped |
| 3 | 15–22 | Distribution | `pip install` → `ge build` on a clean machine; signed releases |
| 4 | 19–26 | Docs & governance | Reference, cookbook, governance published |
| 5 | ongoing | Hardening | Budgets, fuzzing, cross-platform, async |

Phases 1 and 2 are the ones that change what GE *is*. Phase 0 is what
makes them honest. Phase 3 is what makes it installable.

---

## 10. What would make me say "ship it"

A concrete, falsifiable bar:

1. `pip install ge-lang` works on a clean Linux, macOS, and Windows box.
2. `ge new` → `ge build` → a running binary in under five minutes, no toolchain surprises.
3. The differential harness runs ≥500 programs across ≥4 backends with byte-identical output, in CI, on every push.
4. Every backend carries a published maturity label backed by that harness.
5. Unsupported constructs **fail the build** by default.
6. A `.ge` file in VS Code shows diagnostics, hover, and go-to-definition.
7. Every release artifact is signed, with verification commands in the release notes.
8. `KNOWN_GAPS.md` lists every remaining limitation with an owner and a reopen trigger.

Items 3 and 5 are the load-bearing ones. Everything else is packaging.

---

## 11. Honest risks

| Risk | Mitigation |
|---|---|
| Differential harness surfaces many real bugs | That is the point. Budget for it; it is cheaper now than after users hit them. |
| Six backends × full parity is a lot of surface | Publish maturity tiers; let weaker backends be honestly "Experimental" |
| Fail-closed fallbacks break existing examples | Land with `--allow-fallback`, migrate examples, then flip the default |
| Windows-first testing hides macOS/Linux bugs | Cross-platform CI is Phase 5 but should start earlier if contributors appear |
| Bus factor of one | Governance and contributor docs are Phase 4 precisely to address this |
| AI support circularity | Lean into the Python/TypeScript-syntax advantage; ship `ge analyze --json` early for agents |

---

## 12. First three things to do

If only three things get done next:

1. **`docs/BACKEND_STATUS.md`** — one afternoon, and it makes every other
   claim in the project honest.
2. **`--allow-fallback` + fail-closed default** — one week, and it turns
   "it compiled" into a real guarantee.
3. **Differential harness seeded from `test_conceptual_100`** — the corpus
   already exists; only the comparison runner is missing. This is the
   highest-leverage work available and it is uniquely enabled by the
   architecture already built.
