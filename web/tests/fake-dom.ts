// Filename: fake-dom.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// A minimal DOM for the renderer tests: records what was created, set and appended.

import type { DomElementLike, DomFactory, DomNodeLike } from "../src/dom/render.js";

export class FakeText implements DomNodeLike {
  constructor(readonly text: string) {}
  appendChild(): never {
    throw new Error("text nodes have no children");
  }
}

export class FakeElement implements DomElementLike {
  readonly attributes = new Map<string, string>();
  readonly variables = new Map<string, string>();
  readonly children: (FakeElement | FakeText)[] = [];
  readonly style = {
    setProperty: (name: string, value: string): void => {
      this.variables.set(name, value);
    },
  };

  constructor(
    readonly tag: string,
    readonly namespace: string | null,
  ) {}

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  appendChild(child: DomNodeLike): void {
    this.children.push(child as FakeElement | FakeText);
  }
}

export const fakeFactory: DomFactory = {
  createElement: (tag) => new FakeElement(tag, null),
  createElementNS: (namespace, tag) => new FakeElement(tag, namespace),
  createTextNode: (text) => new FakeText(text),
};

/** Every piece of text of a fake tree, concatenated. */
export function allText(node: FakeElement | FakeText): string {
  return node instanceof FakeText ? node.text : node.children.map(allText).join("");
}

/** Every element of a fake tree. */
export function allElements(node: FakeElement | FakeText): FakeElement[] {
  if (node instanceof FakeText) {
    return [];
  }
  return [node, ...node.children.flatMap(allElements)];
}
