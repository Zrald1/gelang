# Release Runbook

Exact steps to publish GE. Nothing here has been done for you — publishing
needs your credentials, and a release should be a deliberate act.

---

## One-time setup

```bash
# npm account (create at https://www.npmjs.com/signup if needed)
npm login

# confirm you are logged in as the right user
npm whoami

# git identity (skip if already set)
git config user.name  "Zrald"
git config user.email "geraldbustilla@gmail.com"
```

The npm package name `gelang` must be available. Check:

```bash
npm view gelang
```

If it is taken, change `"name"` in `package.json` (for example to
`@zrald/gelang`, which needs `npm publish --access public`).

---

## Every release

### 1. Bump the version in both places

```bash
# package.json  "version": "0.1.0"  ->  "0.2.0"
# pyproject.toml version = "0.1.0"  ->  "0.2.0"
```

They must match. `scripts/release.js` fails if they do not.

### 2. Update the changelog

Move the `## [Unreleased]` section to `## [0.2.0]` in `CHANGELOG.md`, and
leave a fresh empty `## [Unreleased]` at the top.

### 3. Run the release

```bash
node scripts/release.js
```

This runs seven gates and stops at the first failure:

| # | Gate |
|---|---|
| 1 | `package.json` and `pyproject.toml` versions agree; changelog has an entry |
| 2 | Every required file exists |
| 3 | `ge api-check` and `ge golden --check` pass |
| 4 | At least rust is installed |
| 5 | The full test suite passes (~60 min; it compiles and runs native binaries) |
| 6 | The npm payload assembles, with templates present |
| 7 | `npm pack` produces a tarball |

If gate 3 fails, the surface genuinely changed. Regenerate deliberately:

```bash
ge api-check --update     # then review the diff and commit
ge golden --update        # then review the diff and commit
```

A change to `api/*.api` or `tests/golden/*.golden` is a change users can
see. Treat it as breaking unless it is purely additive — see
`docs/COMPATIBILITY.md`.

For a quick iteration loop, `--skip-tests` skips gate 5. It refuses to
publish.

### 4. Test the tarball before publishing

```bash
mkdir -p /tmp/consumer && cd /tmp/consumer
npm init -y
npm install /path/to/gelang-0.2.0.tgz
npx gelang doctor
```

### 5. Publish

```bash
node scripts/release.js --publish
# or, if you already ran the dry run and the tarball is current:
npm publish --access public
```

Verify:

```bash
npx gelang@0.2.0 doctor
```

### 6. Push and tag

```bash
git add -A
git commit -m "release: v0.2.0"
git push origin main
git tag -a v0.2.0 -m "v0.2.0"
git push origin main --tags
```

### 7. GitHub release

Create it at
<https://github.com/Zrald1/gelang/releases/new?tag=v0.2.0>

Paste the changelog section for this version as the description. Attach the
tarball if you want a non-npm download path.

---

## First publish (v0.1.0)

```bash
# 1. verify everything locally
node scripts/release.js

# 2. smoke-test the tarball
mkdir -p /tmp/consumer && cd /tmp/consumer && npm init -y
npm install "/path/to/gelang-0.1.0.tgz"
npx gelang doctor

# 3. publish
npm login
npm publish --access public

# 4. push the repository
cd "/path/to/programming lang GB"
git push -u origin main

# 5. tag
git tag -a v0.1.0 -m "v0.1.0"
git push origin main --tags

# 6. GitHub release
# https://github.com/Zrald1/gelang/releases/new?tag=v0.1.0
```

If `git push` asks for credentials, use a Personal Access Token as the
password: <https://github.com/settings/tokens> (scope `repo`).

---

## Checklist

- [ ] Versions match in `package.json` and `pyproject.toml`
- [ ] `CHANGELOG.md` has an entry for this version
- [ ] `node scripts/release.js` passes all seven gates
- [ ] Tarball installed into a clean directory and `npx gelang doctor` works
- [ ] A program builds through npx and produces the right output
- [ ] `npm publish --access public` succeeded
- [ ] `npx gelang@X.Y.Z doctor` works from a clean machine
- [ ] `git push origin main --tags` succeeded
- [ ] GitHub release created with the changelog

---

## Rollback

**npm** — a version cannot be republished once published. Unpublish within
72 hours if it is broken:

```bash
npm unpublish gelang@0.2.0
```

After that, publish a patch:

```bash
npm deprecate gelang@0.2.0 "broken, use 0.2.1"
```

**git** — revert rather than rewrite:

```bash
git revert <bad-commit>
git push origin main
```

Never force-push `main`. The tag stays; add a new tag for the fix.

---

## What is not automated yet

- No CI-based publish workflow (`.github/workflows/ci.yml` verifies only).
  Once you trust the pipeline, add a `workflow_dispatch` job that publishes
  on a tag with an `NPM_TOKEN` secret.
- No signed artifacts or SBOM. See `docs/PRODUCTION_GAPS.md` §R4–R5.
- No reproducible builds. See §R2.
