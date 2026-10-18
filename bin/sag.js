#!/usr/bin/env node
/**
 * npx / npm launcher for sag.
 *
 * The pipeline itself is Python; this shim only forwards argv, stdio and the
 * exit code to `python3 sag.py` next to it. Set SAG_PYTHON to override the
 * interpreter (e.g. SAG_PYTHON=/usr/bin/python3.12).
 */
"use strict";

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const script = path.join(root, "sag.py");

if (!fs.existsSync(script)) {
  console.error("sag: sag.py not found next to bin/sag.js");
  process.exit(1);
}

const python = process.env.SAG_PYTHON || "python3";
const child = spawn(python, [script, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: process.env,
});

child.on("error", (err) => {
  if (err.code === "ENOENT") {
    console.error(
      `sag: ${python} not found. Install Python 3.10+ or set SAG_PYTHON to its path.`,
    );
  } else {
    console.error(`sag: ${err.message}`);
  }
  process.exit(127);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code === null ? 1 : code);
});
