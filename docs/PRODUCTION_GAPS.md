# GE Production Gap Analysis

Every known gap between the current tree and something other programmers can
install, trust, and depend on.

Severity: **S1** blocks adoption · **S2** blocks production use ·
**S3** limits growth.

Each row names the evidence for the claim and the smallest thing that
closes it. Companion documents: `PRODUCTION_PLAN.md` (the staged plan) and
`STABILITY.md` (the don't-break-users architecture).

---

## 1. Compiler correctness

| # | Gap | Sev | Evidence | Smallest fix |
|---|---|---|---|---|
| C1 | ~~No cross-backend verification~~ | — | **Landed**: `ge diff`, 30/30 comparisons agree | Grow corpus 5 → 500 |
| C2 | No emitted-code stability check | **S1** | Any emitter refactor silently churns generated code | `tests/golden/` + `pyeffic.golden --check` |
| C3 | No determinism check | **S1** | Dict ordering or a timestamp in an emitter would go unnoticed | `pyeffic.determinism` — emit twice, compare hashes |
| C4 | Silent CPython fallbacks | **S1** | `main.ge` build reported fallbacks but still succeeded | `--allow-fallback` opt-in; fail closed by default |
| C5 | Heuristic type inference, no sound checker | **S1** | `GE002` is a warning, not a proof | `ge check` with a real type pass |
| C6 | No fuzzing | **S2** | Malformed input → traceback rather than a diagnostic | Grammar-driven generator + nightly run |
| C7 | No memory-safety lane | **S2** | Emitted C++/Rust never run under ASan/UBSan | Sanitizer lane in `ge diff` |
| C8 | String semantics incomplete | **S2** | String indexing infers `int`, several ops are Python-only | Decide and document string semantics per backend |
| C9 | No concurrency or async | **S1** | Largest missing language feature | Design doc first, then feature gate |
| C10 | No differential *performance* tracking | **S3** | Claimed parity is unmeasured in CI | Perf budgets (Phase 5.1) |

**C4 is the highest-value single fix.** It converts "it built" from a claim
into a guarantee and makes C1's harness meaningful.

---

## 2. Language surface

| # | Gap | Sev | Notes |
|---|---|---|---|
| L1 | No stability promise | **S1** | See `STABILITY.md` — `docs/COMPATIBILITY.md` is step one |
| L2 | No editions | **S1** | Any breaking change today breaks everyone |
| L3 | No deprecation policy | **S1** | Nothing can be removed safely |
| L4 | No unstable-feature gate | **S2** | Incomplete features can be depended on, then must be preserved |
| L5 | No provisional carve-out | **S2** | PEP 411 equivalent; needed so the promise can be honest |
| L6 | No language reference | **S1** | "What is supported" lives only in code and tests |
| L7 | No grammar summary | **S2** | Needed for editor tooling and for `api/lang.api` |
| L8 | Generics/traits/structs | **S3** | Classes exist; the type-system surface is thin |

---

## 3. Tooling

| # | Gap | Sev | Notes |
|---|---|---|---|
| T1 | No `ge check` | **S1** | Fast static analysis; also the LSP backend |
| T2 | No LSP server | **S1** | One server covers VS Code, Neovim, Helix, Emacs, Zed, JetBrains |
| T3 | No tree-sitter grammar | **S2** | Syntax highlighting everywhere, independent of LSP |
| T4 | No formatter | **S3** | Removes style arguments from review |
| T5 | Error messages lack fixes | **S1** | Machine-applicable suggestions are what `ge fix` needs |
| T6 | No `ge analyze --json` | **S2** | Blocks CI integration and AI-agent loops |
| T7 | No debug info mapping | **S2** | Generated code has no line mapping back to `.ge` |
| T8 | No incremental build | **S3** | Full rebuild every time |

The LSP research is unambiguous on ROI: "we say 'write a language server'
and the editors plug in by themselves." `M` servers solve `M × N`.

---

## 4. Ecosystem

| # | Gap | Sev | Notes |
|---|---|---|---|
| E1 | No package manager | **S1** | Copy-paste is the current dependency manager |
| E2 | No manifest/lockfile | **S1** | `ge.toml` exists but has no dependencies section |
| E3 | No registry | **S3** | Deliberately last — Git-as-transport first (Zig's lesson) |
| E4 | No PURL type | **S3** | Without it, GE packages can't appear in SBOMs or advisories |
| E5 | Thin standard library | **S1** | Drive from real programs, not a wishlist |
| E6 | No interop story for existing libs | **S2** | `ge_inline`/FFI exist but aren't documented as a pattern |
| E7 | No package format versioning | **S2** | Freeze `.ge` format before third parties depend on it |

Zig's experience is the cautionary tale: a registry drags in manifest
parsers for other ecosystems, a PURL type proposal (pending since 2023), and
advisory-database integration. Git-as-transport sidesteps all of it.

---

## 5. Release engineering

| # | Gap | Sev | Notes |
|---|---|---|---|
| R1 | No CI | **S1** | Nothing runs on push; a green local suite proves nothing |
| R2 | No reproducible builds | **S1** | Go's argument: reproducible builds are how you verify binaries |
| R3 | No pinned toolchains | **S1** | Detection is version-adaptive by design; releases must pin |
| R4 | No SBOM | **S2** | CycloneDX; expected by any security review |
| R5 | No signed artifacts | **S2** | Keyless cosign; publish verification commands in release notes |
| R6 | No release checklist | **S1** | Solidity/reflaxe.go both gate tags on a normative checklist |
| R7 | No changelog generation | **S2** | Conventional commits → changelog |
| R8 | No version in generated code | **S3** | Hard to tell which GE built a binary |
| R9 | No semver policy for a language | **S1** | What is major when the product is a compiler? |
| R10 | No install story | **S1** | `pip install ge-lang` must work on a clean machine |

---

## 6. Documentation & governance

| # | Gap | Sev | Notes |
|---|---|---|---|
| D1 | No language reference | **S1** | Duplicate of L6; listed here for the doc workstream |
| D2 | No cookbook | **S2** | Task-oriented: "call C++ from Rust", "add a backend" |
| D3 | No migration guides | **S2** | Python → GE, TypeScript → GE, GE → each target |
| D4 | No backend authoring guide | **S2** | The N×M promise made concrete |
| D5 | No governance doc | **S1** | Research: institutional friction is the **strongest** predictor of abandonment |
| D6 | No CONTRIBUTING / CoC | **S2** | Standard open-source hygiene |
| D7 | No security policy | **S1** | Prerequisite for anyone shipping this |
| D8 | No stability tiers | **S1** | Stable / Preview / Experimental per syntax, CLI, and backend |
| D9 | No website / quickstart | **S2** | Time-to-first-binary is the adoption metric |
| D10 | No per-backend maturity matrix | **S1** | py2many's `LANGUAGES.md` is why its status claims are trusted |

---

## 7. Platform coverage

| # | Gap | Sev | Notes |
|---|---|---|---|
| P1 | Windows-first templates | **S1** | macOS/Linux paths untested |
| P2 | No cross-platform CI | **S1** | Bugs hide on untested platforms |
| P3 | No ARM coverage | **S2** | Apple silicon and ARM servers |
| P4 | No mobile packaging | **S2** | Flutter project generated, never built into an APK/IPA |
| P5 | No cross-compilation | **S3** | Target triples for the native backends |

---

## 8. Operations

| # | Gap | Sev | Notes |
|---|---|---|---|
| O1 | No observability in generated programs | **S3** | Logging/metrics are the user's problem today |
| O2 | No load testing | **S2** | The `web-react` template ships an unbenchmarked server |
| O3 | No error reporting | **S3** | Compiler panics are not collected |
| O4 | No performance budgets | **S3** | reflaxe.go runs perf gates as a release contract |
| O5 | No security review of `ge_inline`/`ge_raw` | **S2** | Arbitrary code injection is a feature *and* a hazard |

O5 deserves attention: `ge_inline`/`ge_raw`/`ge_preamble` are deliberate
escape hatches, but there is no documented policy on when they are
acceptable, no lint that flags them, and no way to forbid them in a build.
For a language aimed at AI-assisted development, that is a supply-chain
surface.

---

## 9. The five that actually gate adoption

If everything else waited, these five would still decide whether GE gets
used:

| Rank | Gap | Why it gates |
|---|---|---|
| 1 | **C4** — fail-closed fallbacks | Without it, a green build means nothing |
| 2 | **L1/L2** — stability promise + editions | Without it, no one can safely upgrade |
| 3 | **T1/T2** — `ge check` + LSP | Without it, the editor experience is worse than plain Python |
| 4 | **R1** — CI | Without it, every release is a guess |
| 5 | **D10** — per-backend maturity matrix | Without it, users cannot tell what is safe |

Everything else in this document is downstream of those five.

---

## 10. What "production" would actually mean

A concrete bar, not a feeling:

1. `pip install ge-lang` works on clean Linux, macOS, and Windows.
2. `ge new` → `ge build` → running binary in under five minutes.
3. `ge diff` covers ≥500 programs across ≥4 backends, byte-identical, in CI on every push.
4. `ge golden --check` and `ge api-check` gate every release.
5. Every backend carries a published maturity label backed by that harness.
6. Unsupported constructs fail the build by default.
7. A `.ge` file in VS Code shows diagnostics, hover, and go-to-definition.
8. Releases are reproducible and signed, with verification commands published.
9. `docs/COMPATIBILITY.md` exists and is enforced by an edition corpus.
10. `KNOWN_GAPS.md` lists every remaining limitation with an owner and a reopen trigger.

Items 3, 4, 6, and 9 are the load-bearing ones.
