// Filename: vnode.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Virtual nodes: what every screen returns. Plain data, so a screen is a pure function that tests
// can compare without a browser. Text is always a plain string; there is no way to build markup
// from a string.

export type Tag =
  | "a" | "b" | "button" | "code" | "details" | "div" | "h1" | "h2" | "h3" | "i" | "img"
  | "input" | "label" | "li" | "main" | "nav" | "option" | "p" | "pre" | "section" | "select"
  | "span" | "summary" | "table" | "tbody" | "td" | "th" | "thead" | "time" | "tr" | "ul"
  | "svg" | "g" | "rect" | "line" | "text" | "title";

export type AttrValue = string | number | boolean;
export type Attrs = Readonly<Record<string, AttrValue>>;

export interface VElement {
  readonly tag: Tag;
  readonly attrs: Attrs;
  /** CSS custom properties for dynamic values (bar widths); applied with style.setProperty. */
  readonly vars: Readonly<Record<string, string>>;
  readonly children: readonly VNode[];
}

export type VNode = string | VElement;
export type Child = VNode | null | undefined | false | readonly Child[];

function flatten(children: readonly Child[], into: VNode[]): VNode[] {
  for (const child of children) {
    if (child === null || child === undefined || child === false) {
      continue;
    }
    if (typeof child === "string") {
      into.push(child);
    } else if (Array.isArray(child)) {
      flatten(child as readonly Child[], into);
    } else {
      into.push(child as VElement);
    }
  }
  return into;
}

/** Build an element. Children that are null, undefined or false are dropped; arrays are flattened. */
export function h(tag: Tag, attrs: Attrs = {}, ...children: Child[]): VElement {
  return { tag, attrs, vars: {}, children: flatten(children, []) };
}

/** The same element with CSS custom properties (for example `{ "--w": "40%" }`). */
export function withVars(element: VElement, vars: Readonly<Record<string, string>>): VElement {
  return { ...element, vars };
}

/** All the text of a tree, in order (used by tests and by accessibility labels). */
export function textOf(node: VNode): string {
  return typeof node === "string" ? node : node.children.map(textOf).join("");
}

/** Every element of a tree that satisfies the predicate, in document order. */
export function findAll(node: VNode, predicate: (element: VElement) => boolean): VElement[] {
  if (typeof node === "string") {
    return [];
  }
  const found = predicate(node) ? [node] : [];
  return found.concat(...node.children.map((child) => findAll(child, predicate)));
}
