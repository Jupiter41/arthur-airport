"use strict";

const { readdirSync } = require("node:fs");
const { join, resolve } = require("node:path");
const { spawnSync } = require("node:child_process");

function testFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory()
      ? testFiles(path)
      : entry.name.endsWith(".test.ts") ? [path] : [];
  });
}

const root = resolve(__dirname, "..");
const files = testFiles(join(root, "src")).sort();
if (files.length === 0) {
  throw new Error("No gateway test files found");
}
const result = spawnSync(
  process.execPath,
  ["--require", "ts-node/register", "--test", ...files],
  { cwd: root, stdio: "inherit" },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
