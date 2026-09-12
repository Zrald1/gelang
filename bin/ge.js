#!/usr/bin/env node
/**
 * GE launcher — finds a Python 3.10+ interpreter and runs the GE compiler.
 *
 * The npm package bundles the compiler source, so no `pip install` is
 * needed. This shim exists only to locate Python and set PYTHONPATH.
 *
 *   npx gelang build main.ge --run
 *   npx gelang doctor
 *   npx gelang create myapp --template desktop-gui -y
 */
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const PKG_ROOT = path.resolve(__dirname, "..");
const PY_SRC = path.join(PKG_ROOT, "python");

// ---------------------------------------------------------------------------
// Python discovery
// ---------------------------------------------------------------------------

const MIN_MAJOR = 3;
const MIN_MINOR = 10;

function pythonCandidates() {
  const out = [];
  if (process.env.GE_PYTHON) out.push([process.env.GE_PYTHON, []]);
  if (process.platform === "win32") {
    out.push(["py", ["-3"]]);
    out.push(["python3", []]);
    out.push(["python", []]);
  } else {
    out.push(["python3", []]);
    out.push(["python", []]);
  }
  return out;
}

function probe(cmd, preArgs) {
  const r = spawnSync(cmd, [...preArgs, "-c",
    "import sys;print('%d.%d'%sys.version_info[:2])"],
    { encoding: "utf8" });
  if (r.status !== 0 || !r.stdout) return null;
  const m = r.stdout.trim().match(/^(\d+)\.(\d+)$/);
  if (!m) return null;
  return { cmd, preArgs, major: +m[1], minor: +m[2] };
}

function findPython() {
  for (const [cmd, preArgs] of pythonCandidates()) {
    const info = probe(cmd, preArgs);
    if (!info) continue;
    const ok = info.major > MIN_MAJOR ||
      (info.major === MIN_MAJOR && info.minor >= MIN_MINOR);
    if (ok) return info;
    // remember the first too-old interpreter so the error can be specific
    if (!findPython._tooOld) findPython._tooOld = info;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  if (!fs.existsSync(path.join(PY_SRC, "pyeffic"))) {
    console.error(
      "GE: bundled compiler source is missing from this install.\n" +
      "    Expected: " + path.join(PY_SRC, "pyeffic") + "\n" +
      "    Reinstall the package, or run `npm rebuild gelang`."
    );
    return 1;
  }

  const py = findPython();
  if (!py) {
    const old = findPython._tooOld;
    console.error(
      "\nGE needs Python " + MIN_MAJOR + "." + MIN_MINOR + " or newer.\n" +
      (old
        ? "  Found: " + old.cmd + " (" + old.major + "." + old.minor + ")\n"
        : "  Found: nothing on PATH\n") +
      "\nInstall Python:\n" +
      "  Windows   https://www.python.org/downloads/   (or: winget install Python.Python.3.12)\n" +
      "  macOS     brew install python@3.12\n" +
      "  Debian    sudo apt install python3\n" +
      "\nThen run: npx gelang doctor\n"
    );
    return 1;
  }

  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH
    ? PY_SRC + path.delimiter + env.PYTHONPATH
    : PY_SRC;
  // keep the user's own bytecode cache out of the package directory
  env.PYTHONDONTWRITEBYTECODE = env.PYTHONDONTWRITEBYTECODE || "1";

  const args = [...py.preArgs, "-m", "pyeffic.ge_cli", ...process.argv.slice(2)];
  const r = spawnSync(py.cmd, args, { stdio: "inherit", env });
  if (r.error) {
    console.error("GE: failed to start Python: " + r.error.message);
    return 1;
  }
  return r.status === null ? 1 : r.status;
}

process.exit(main());
