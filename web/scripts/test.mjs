// Filename: test.mjs
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Compiles the sources together with the tests and runs them with node:test (no dependencies).

import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { tsc } from "./tsc.mjs";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
rmSync(`${webRoot}.test-build`, { recursive: true, force: true });
tsc(["-p", "tsconfig.test.json"]);

const result = spawnSync(process.execPath, ["--test", ".test-build/tests/*.test.js"], {
  cwd: webRoot,
  stdio: "inherit",
});
process.exit(result.status ?? 1);
