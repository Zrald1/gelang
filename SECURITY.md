# Security Policy

## Reporting a vulnerability

Do not open a public issue for security problems.

Use GitHub's private reporting:
https://github.com/Zrald1/gelang/security/advisories/new

Include: what you found, how to reproduce it, and the impact you believe it
has. You will get a response within 7 days.

## Scope

GE is a compiler. The security-relevant surfaces are:

| Surface | Concern |
|---|---|
| `ge_inline` / `ge_raw` / `ge_preamble` | Deliberate arbitrary-code-injection points in the *target* language |
| Dependency resolution | Not yet implemented — no supply-chain surface today |
| Generated code | Inherits the target language's safety properties, not Python's |
| The npm wrapper | Spawns Python with a bundled `PYTHONPATH` |

## Known considerations

**Escape hatches are arbitrary code execution by design.** `ge_inline`,
`ge_raw`, and `ge_preamble` insert raw target-language code into the output.
Anything reaching them from an untrusted source is a code-execution risk.
There is no lint or policy gate on them yet — see
`docs/PRODUCTION_GAPS.md` §O5.

**GE is not a sandbox.** It compiles and runs programs. Do not feed it
untrusted source and expect containment.

**No dependency ecosystem yet.** When a package manager lands, it will be
Git-based with pinned revisions and content hashes; a registry is
deliberately deferred.
