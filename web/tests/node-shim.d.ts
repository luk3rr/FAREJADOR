// Filename: node-shim.d.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The few Node modules the tests use, described by hand so the only development dependency stays
// `typescript` (no @types/node).

declare module "node:test" {
  export function test(name: string, fn: () => void | Promise<void>): void;
  export function describe(name: string, fn: () => void): void;
}

declare module "node:assert/strict" {
  interface Assert {
    equal(actual: unknown, expected: unknown, message?: string): void;
    notEqual(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
    match(value: string, pattern: RegExp, message?: string): void;
    doesNotMatch(value: string, pattern: RegExp, message?: string): void;
    throws(fn: () => unknown, expected?: unknown, message?: string): void;
    doesNotThrow(fn: () => unknown, message?: string): void;
    rejects(fn: () => Promise<unknown>, expected?: unknown, message?: string): Promise<void>;
  }
  const assert: Assert;
  export default assert;
}

declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf8"): string;
}
