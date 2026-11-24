// Filename: playwright.config.ts
// Created on: November 24, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// End-to-end tests: a real browser against the real API and the built dashboard, over a seeded
// throwaway trace (see e2e/server.py).

import { defineConfig } from "@playwright/test";

const PORT = 8765;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  retries: process.env["CI"] ? 1 : 0,
  reporter: process.env["CI"] ? [["github"], ["list"]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, locale: "pt-BR" },
  webServer: {
    command: `uv run --project .. python e2e/server.py ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/status`,
    reuseExistingServer: !process.env["CI"],
    timeout: 60_000,
  },
});
