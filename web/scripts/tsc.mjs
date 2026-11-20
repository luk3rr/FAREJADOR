// Filename: tsc.mjs
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Runs the TypeScript compiler installed in node_modules, without going through npx.

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const tscBin = fileURLToPath(new URL("../node_modules/typescript/bin/tsc", import.meta.url));
const webRoot = fileURLToPath(new URL("..", import.meta.url));

export function tsc(args) {
  const result = spawnSync(process.execPath, [tscBin, ...args], {
    cwd: webRoot,
    stdio: "inherit",
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
