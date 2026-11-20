// Filename: build.mjs
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Compiles the dashboard and copies the static files next to it.
//
// The destination is src/farejador/web/static (ignored by git) unless WEB_OUT says otherwise;
// the Docker build uses WEB_OUT=/out. Layout: <out>/index.html and <out>/assets/*.

import { cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { tsc } from "./tsc.mjs";

const here = (path) => fileURLToPath(new URL(path, import.meta.url));
const out = process.env.WEB_OUT ?? here("../../src/farejador/web/static");

rmSync(out, { recursive: true, force: true });
mkdirSync(`${out}/assets`, { recursive: true });

tsc(["-p", "tsconfig.json", "--outDir", `${out}/assets`]);

cpSync(here("../static/index.html"), `${out}/index.html`);
cpSync(here("../static/styles.css"), `${out}/assets/styles.css`);
cpSync(here("../static/icon.png"), `${out}/assets/icon.png`);
console.log(`dashboard built into ${out}`);
