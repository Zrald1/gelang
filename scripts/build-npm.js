#!/usr/bin/env node
/**
 * Assemble the npm payload.
 *
 * The compiler is Python, so the npm package ships the Python source and the
 * `bin/ge.js` shim runs it. This script copies `pyeffic/` into `python/` at
 * pack time, so the published tarball is self-contained: no `pip install`,
 * no network access at install time.
 *
 * Runs automatically via `prepublishOnly`.
 *
 *   node scripts/build-npm.js            copy the compiler
 *   node scripts/build-npm.js --check    verify the payload without writing
 */
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "pyeffic");
const OUT = path.join(ROOT, "python");

const CHECK_ONLY = process.argv.includes("--check");

/** Directories that must never reach the published package. */
const SKIP_DIRS = new Set(["__pycache__", ".mypy_cache", ".pytest_cache", ".git"]);

/** Files that must never reach the published package. */
const SKIP_EXTS = new Set([".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".o"]);

function shouldSkip(name, isDir) {
  if (isDir) return SKIP_DIRS.has(name);
  if (name.endsWith(".pyc")) return true;
  return SKIP_EXTS.has(path.extname(name).toLowerCase());
}

function walk(dir, base, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (shouldSkip(entry.name, entry.isDirectory())) continue;
    const abs = path.join(dir, entry.name);
    // forward slashes so the checks below work on every platform
    const rel = (base ? base + "/" + entry.name : entry.name);
    if (entry.isDirectory()) {
      walk(abs, rel, out);
    } else {
      out.push(rel);
    }
  }
  return out;
}

function copyTree(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (shouldSkip(entry.name, entry.isDirectory())) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) copyTree(s, d);
    else fs.copyFileSync(s, d);
  }
}

function fail(msg) {
  console.error("build-npm: " + msg);
  process.exit(1);
}

function main() {
  if (!fs.existsSync(SRC)) {
    fail("compiler source not found at " + SRC);
  }

  const files = walk(SRC, "", []);
  const pyCount = files.filter((f) => f.endsWith(".py")).length;

  // sanity: the pieces the shim depends on must exist
  const required = [
    "ge_cli.py",
    "__init__.py",
    "__main__.py",
    "pipeline.py",
    "emitters/__init__.py",
    "frontends/__init__.py",
  ];
  const missing = required.filter((r) => !files.includes(r));
  if (missing.length) {
    fail("compiler is missing required files: " + missing.join(", "));
  }

  // sanity: templates ship with the compiler
  const templateCount = files.filter((f) => f.includes("templates/")).length;
  if (templateCount === 0) {
    fail("no templates found under pyeffic/templates — `ge create` would break");
  }

  const totalBytes = files.reduce(
    (n, f) => n + fs.statSync(path.join(SRC, f)).size, 0);

  console.log("build-npm: compiler payload");
  console.log("  files     : " + files.length);
  console.log("  python    : " + pyCount + " modules");
  console.log("  templates : " + templateCount + " files");
  console.log("  size      : " + (totalBytes / 1024).toFixed(0) + " KB");

  if (CHECK_ONLY) {
    console.log("  (check only — nothing written)");
    return;
  }

  if (fs.existsSync(OUT)) fs.rmSync(OUT, { recursive: true, force: true });
  copyTree(SRC, path.join(OUT, "pyeffic"));
  console.log("  written   : python/pyeffic/");
}

main();
