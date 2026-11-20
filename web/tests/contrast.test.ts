// Filename: contrast.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// WCAG 2.1 AA contrast of the design tokens, in both themes (NFR-12).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const CSS = readFileSync(new URL("../../static/styles.css", import.meta.url), "utf8");

function tokens(selector: string): Record<string, string> {
  const start = CSS.indexOf(selector);
  assert.ok(start >= 0, `missing ${selector}`);
  const body = CSS.slice(CSS.indexOf("{", start) + 1, CSS.indexOf("}", start));
  const found: Record<string, string> = {};
  for (const match of body.matchAll(/(--[a-z0-9-]+):\s*([^;]+)/g)) {
    found[match[1] as string] = (match[2] as string).trim();
  }
  return found;
}

/** "#fff" and "#ffffff" are the same colour. */
function expand(hex: string): string {
  return /^#[0-9a-f]{3}$/i.test(hex) ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}` : hex;
}

function luminance(color: string): number {
  const hex = expand(color);
  const channel = (i: number): number => {
    const value = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}

const THEMES: [string, Record<string, string>][] = [
  ["dark", { ...tokens(":root{") }],
  ["light", { ...tokens(':root[data-theme="light"]') }],
];

// [foreground, background, minimum ratio, what it is]
const PAIRS: [string, string, number, string][] = [
  ["--fg", "--bg", 4.5, "body text"],
  ["--fg", "--panel", 4.5, "text on cards"],
  ["--fg", "--panel-2", 4.5, "text on raised areas"],
  ["--muted", "--bg", 4.5, "secondary text"],
  ["--muted", "--panel", 4.5, "secondary text on cards"],
  ["--info", "--bg", 4.5, "links"],
  ["--info", "--panel", 4.5, "links on cards"],
  ["--accent", "--panel", 4.5, "accent text on cards"],
  ["--on-accent", "--accent", 4.5, "button text"],
  ["--success", "--panel", 4.5, "success text"],
  ["--danger", "--panel", 4.5, "error text"],
  ["--warn", "--panel", 4.5, "warning text"],
  ["--side-ink", "--side", 4.5, "sidebar text"],
  ["--success", "--panel-2", 4.5, "success pills"],
  ["--danger", "--panel-2", 4.5, "failure pills"],
  ["--warn", "--panel-2", 4.5, "warning pills"],
  ["--info", "--panel-2", 4.5, "info pills"],
  ["--muted", "--panel-2", 4.5, "muted text on raised areas"],
];

for (const [name, theme] of THEMES) {
  test(`${name} theme: every text pair has at least the contrast AA asks for`, () => {
    for (const [foreground, background, minimum, what] of PAIRS) {
      const fg = theme[foreground];
      const bg = theme[background];
      assert.ok(fg !== undefined && bg !== undefined, `${foreground}/${background} must be hex tokens`);
      assert.match(fg, /^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
      assert.match(bg, /^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
      const ratio = contrast(fg, bg);
      assert.ok(ratio >= minimum, `${name}: ${what} (${foreground} on ${background}) is ${ratio.toFixed(2)}, needs ${minimum}`);
    }
  });
}

test("short hex colours are expanded before the maths", () => {
  assert.ok(Math.abs(contrast("#fff", "#000") - 21) < 0.01);
});

test("the contrast function agrees with known values", () => {
  assert.ok(Math.abs(contrast("#000000", "#ffffff") - 21) < 0.01);
  assert.ok(Math.abs(contrast("#777777", "#ffffff") - 4.48) < 0.05);
});
