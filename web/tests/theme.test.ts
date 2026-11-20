// Filename: theme.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { THEME_KEY, loadTheme, saveTheme, toggleTheme } from "../src/theme.js";
import type { StorageLike } from "../src/theme.js";

function memory(initial: Record<string, string> = {}): StorageLike & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => {
      data[key] = value;
    },
  };
}

test("dark is the default", () => {
  assert.equal(loadTheme(memory()), "dark");
  assert.equal(loadTheme(null), "dark");
});

test("the saved choice is restored, and anything unknown falls back to dark", () => {
  assert.equal(loadTheme(memory({ [THEME_KEY]: "light" })), "light");
  assert.equal(loadTheme(memory({ [THEME_KEY]: "dark" })), "dark");
  assert.equal(loadTheme(memory({ [THEME_KEY]: "<script>" })), "dark");
  assert.equal(loadTheme(memory({ [THEME_KEY]: "" })), "dark");
});

test("saving writes the choice", () => {
  const storage = memory();
  saveTheme(storage, "light");
  assert.equal(storage.data[THEME_KEY], "light");
});

test("storage that throws (blocked site data) never breaks the page", () => {
  const blocked: StorageLike = {
    getItem: () => {
      throw new DOMException("denied", "SecurityError");
    },
    setItem: () => {
      throw new DOMException("denied", "SecurityError");
    },
  };
  assert.equal(loadTheme(blocked), "dark");
  saveTheme(blocked, "light");
  saveTheme(null, "light");
});

test("toggling flips the theme", () => {
  assert.equal(toggleTheme("dark"), "light");
  assert.equal(toggleTheme("light"), "dark");
});
