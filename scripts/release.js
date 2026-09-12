#!/usr/bin/env node
/**
 * Release preparation.
 *
 * Runs every guard, assembles the npm payload, and prints the exact commands
 * to publish. It does not publish anything itself — that needs your
 * credentials, and a release should be a deliberate act.
 *
 *   node scripts/release.js            dry run: checks + pack, no publish
 *   node scripts/release.js --publish  publish to npm (needs `npm login`)
 */
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const DO_PUBLISH = process.argv.includes("--publish");
const SKIP_TESTS = process.argv.includes("--skip-tests");

/**
 * npm/git are .cmd shims on Windows, and Node 20.12+ refuses to spawn a
 * .cmd without a shell (CVE-2024-27980). Use a shell only for those, and
 * pass a single quoted command string so Node never has to concatenate an
 * argument array (which is what DEP0190 warns about).
 */
function needsShell(cmd) {
  return process.platform === "win32" &&
    (cmd === "npm" || cmd === "npx" || cmd === "git");
}

function quote(s) {
  const str = String(s);
  if (/^[A-Za-z0-9_@./:=+-]+$/.test(str)) return str;
  return '"' + str.replace(/(["\\])/g, "\\$1") + '"';
}

function run(cmd, args, opts = {}) {
  const useShell = needsShell(cmd);
  const exe = useShell ? cmd + ".cmd" : cmd;
  process.stdout.write("  $ " + [cmd, ...args].join(" ") + "\n");

  const r = useShell
    ? spawnSync([exe, ...args].map(quote).join(" "),
        { cwd: ROOT, stdio: "inherit", shell: true, ...opts })
    : spawnSync(exe, args, { cwd: ROOT, stdio: "inherit", shell: false, ...opts });

  if (r.error) {
    console.error("  ! " + r.error.message);
    return false;
  }
  return r.status === 0;
}

function step(n, total, title) {
  console.log("\n[" + n + "/" + total + "] " + title);
}

function fail(msg) {
  console.error("\nrelease: " + msg);
  process.exit(1);
}

const TOTAL = 7;

// ---------------------------------------------------------------------------
// 1. version consistency
// ---------------------------------------------------------------------------
step(1, TOTAL, "version consistency");

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
const version = pkg.version;

const pyproject = fs.readFileSync(path.join(ROOT, "pyproject.toml"), "utf8");
const pyVersion = (pyproject.match(/^version\s*=\s*"([^"]+)"/m) || [])[1];
if (!pyVersion) fail("could not read version from pyproject.toml");
if (pyVersion !== version) {
  fail("version mismatch: package.json=" + version + " pyproject.toml=" + pyVersion);
}
console.log("  version: " + version + " (package.json and pyproject.toml agree)");

const changelog = fs.readFileSync(path.join(ROOT, "CHANGELOG.md"), "utf8");
if (!changelog.includes("## [" + version + "]") &&
    !changelog.includes("## [Unreleased]")) {
  fail("CHANGELOG.md has no entry for " + version + " and no [Unreleased] section");
}
console.log("  changelog: entry present");

// ---------------------------------------------------------------------------
// 2. required files
// ---------------------------------------------------------------------------
step(2, TOTAL, "required files");

const REQUIRED = [
  "README.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
  "CODE_OF_CONDUCT.md", "package.json", "pyproject.toml",
  "bin/ge.js", "scripts/build-npm.js", "scripts/check-toolchains.py",
  ".gitignore", ".github/workflows/ci.yml",
  "docs/COMPATIBILITY.md", "docs/STABILITY.md", "docs/PRODUCTION_PLAN.md",
];
const missing = REQUIRED.filter((f) => !fs.existsSync(path.join(ROOT, f)));
if (missing.length) fail("missing required files: " + missing.join(", "));
console.log("  " + REQUIRED.length + " files present");

// ---------------------------------------------------------------------------
// 3. surface guards
// ---------------------------------------------------------------------------
step(3, TOTAL, "surface guards");

if (!run("python", ["-m", "pyeffic.ge_cli", "api-check"])) {
  fail("API surface drifted — run `ge api-check --update`, review, commit");
}
if (!run("python", ["-m", "pyeffic.ge_cli", "golden", "--check", "--no-behaviour"])) {
  fail("golden corpus drifted — run `ge golden --update`, review, commit");
}

// ---------------------------------------------------------------------------
// 4. toolchains
// ---------------------------------------------------------------------------
step(4, TOTAL, "toolchains");
run("python", ["scripts/check-toolchains.py", "--require", "rust"]);

// ---------------------------------------------------------------------------
// 5. test suite
// ---------------------------------------------------------------------------
step(5, TOTAL, "test suite");
if (SKIP_TESTS) {
  console.log("  (skipped — remove --skip-tests before publishing)");
} else {
  if (!run("python", ["-m", "unittest", "discover", "tests"])) {
    fail("test suite failed");
  }
}
if (DO_PUBLISH && SKIP_TESTS) {
  fail("refusing to publish with --skip-tests");
}

// ---------------------------------------------------------------------------
// 6. assemble the npm payload
// ---------------------------------------------------------------------------
step(6, TOTAL, "assemble the npm payload");
if (!run("node", ["scripts/build-npm.js"])) fail("payload assembly failed");

const pyOut = path.join(ROOT, "python", "pyeffic");
if (!fs.existsSync(path.join(pyOut, "ge_cli.py"))) {
  fail("payload is missing the CLI");
}
if (!fs.existsSync(path.join(pyOut, "templates"))) {
  fail("payload is missing the templates — `ge create` would break");
}
console.log("  python/pyeffic/ is complete");

// ---------------------------------------------------------------------------
// 7. pack
// ---------------------------------------------------------------------------
step(7, TOTAL, "pack");

for (const f of fs.readdirSync(ROOT)) {
  if (f.endsWith(".tgz")) fs.unlinkSync(path.join(ROOT, f));
}
if (!run("npm", ["pack"])) fail("npm pack failed");

const tarball = fs.readdirSync(ROOT).find((f) => f.endsWith(".tgz"));
const size = (fs.statSync(path.join(ROOT, tarball)).size / 1024).toFixed(0);
console.log("  " + tarball + " (" + size + " KB)");

// ---------------------------------------------------------------------------
// done
// ---------------------------------------------------------------------------
console.log("\n" + "=".repeat(62));
if (DO_PUBLISH) {
  console.log("Publishing to npm");
  console.log("=".repeat(62) + "\n");
  if (!run("npm", ["publish", "--access", "public"])) {
    fail("npm publish failed — are you logged in? (`npm login`)");
  }
  console.log("\npublished gelang@" + version);
  console.log("verify:  npx gelang@" + version + " doctor");
} else {
  console.log("Ready to publish");
  console.log("=".repeat(62));
  console.log(`
  npm login                              # once
  npm publish --access public

  then tag the release:

  git tag -a v${version} -m "v${version}"
  git push origin main --tags

  and create the GitHub release at
  https://github.com/Zrald1/gelang/releases/new?tag=v${version}
`);
}
