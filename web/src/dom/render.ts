// Filename: render.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The only code that touches the DOM. It turns a virtual node into elements using createElement,
// createTextNode and setAttribute from allow-lists: text can never become markup, event handlers
// and inline styles cannot be set, and links only point to the dashboard itself or to a GitHub
// pull request. A violation throws, because it is a bug in our code, never in the data.

import type { AttrValue, Tag, VElement, VNode } from "./vnode.js";

export const SVG_NS = "http://www.w3.org/2000/svg";
const SVG_TAGS: ReadonlySet<Tag> = new Set<Tag>(["svg", "g", "rect", "line", "text", "title"]);

const GLOBAL_ATTRS = new Set(["class", "id", "role", "title", "tabindex", "lang", "hidden"]);
const ATTRS_BY_TAG: Readonly<Partial<Record<Tag, readonly string[]>>> = {
  a: ["href", "target", "rel"],
  img: ["src", "alt", "width", "height"],
  button: ["type", "disabled"],
  input: ["type", "value", "placeholder", "name", "disabled", "min", "max"],
  select: ["name", "disabled"],
  option: ["value", "selected"],
  label: ["for"],
  details: ["open"],
  td: ["colspan"],
  th: ["colspan", "scope"],
  time: ["datetime"],
  svg: ["viewBox", "width", "height", "preserveAspectRatio"],
  rect: ["x", "y", "width", "height", "rx", "fill"],
  line: ["x1", "y1", "x2", "y2", "stroke"],
  text: ["x", "y", "text-anchor", "font-size", "fill"],
};
const DATA_OR_ARIA = /^(data|aria)-[a-z0-9-]+$/;
const INTERNAL_HREF = /^#\/[A-Za-z0-9/_?=&.%:-]*$/;
const GITHUB_PR_HREF = /^https:\/\/github\.com\/[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}\/pull\/[0-9]{1,9}$/;
const ASSET_SRC = /^\/assets\/(?!.*\.\.)[A-Za-z0-9_./-]+$/;
const CSS_VAR_NAME = /^--[a-z0-9-]+$/;
const CSS_VAR_VALUE = /^(?:[0-9]{1,6}(?:\.[0-9]{1,4})?(?:%|px)?|var\(--[a-z0-9-]{1,40}\))$/;

export class UnsafeNodeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnsafeNodeError";
  }
}

/** What the renderer needs from `document`; tests pass a fake. */
export interface DomNodeLike {
  appendChild(child: DomNodeLike): unknown;
}
export interface DomElementLike extends DomNodeLike {
  setAttribute(name: string, value: string): void;
  readonly style: { setProperty(name: string, value: string): void };
}
export interface DomFactory {
  createElement(tag: string): DomElementLike;
  createElementNS(namespace: string, tag: string): DomElementLike;
  createTextNode(text: string): DomNodeLike;
}
export interface Container {
  replaceChildren(...nodes: DomNodeLike[]): void;
}

function checkAttribute(tag: Tag, name: string, value: AttrValue): string {
  const allowed =
    GLOBAL_ATTRS.has(name) || DATA_OR_ARIA.test(name) || (ATTRS_BY_TAG[tag] ?? []).includes(name);
  if (!allowed) {
    throw new UnsafeNodeError(`attribute "${name}" is not allowed on <${tag}>`);
  }
  const text = value === true ? "" : String(value);
  if (name === "href" && !(INTERNAL_HREF.test(text) || GITHUB_PR_HREF.test(text))) {
    throw new UnsafeNodeError("href must be a dashboard address or a GitHub pull request");
  }
  if (name === "src" && !ASSET_SRC.test(text)) {
    throw new UnsafeNodeError("src must be a file under /assets/");
  }
  if (name === "target" && text !== "_blank") {
    throw new UnsafeNodeError('target must be "_blank"');
  }
  if (name === "rel" && text !== "noopener noreferrer") {
    throw new UnsafeNodeError('rel must be "noopener noreferrer"');
  }
  return text;
}

export function render(node: VNode, factory: DomFactory): DomNodeLike {
  if (typeof node === "string") {
    return factory.createTextNode(node);
  }
  return renderElement(node, factory);
}

function renderElement(node: VElement, factory: DomFactory): DomElementLike {
  const element = SVG_TAGS.has(node.tag)
    ? factory.createElementNS(SVG_NS, node.tag)
    : factory.createElement(node.tag);
  for (const [name, value] of Object.entries(node.attrs)) {
    if (value === false) {
      continue; // a false boolean attribute is simply absent
    }
    element.setAttribute(name, checkAttribute(node.tag, name, value));
  }
  for (const [name, value] of Object.entries(node.vars)) {
    if (!CSS_VAR_NAME.test(name) || !CSS_VAR_VALUE.test(value)) {
      throw new UnsafeNodeError(`invalid CSS variable "${name}"`);
    }
    element.style.setProperty(name, value);
  }
  if (node.tag === "a" && node.attrs["target"] === "_blank" && node.attrs["rel"] !== "noopener noreferrer") {
    throw new UnsafeNodeError("links that open a new tab need rel=noopener noreferrer");
  }
  for (const child of node.children) {
    element.appendChild(render(child, factory));
  }
  return element;
}

/** Replace the content of a container with the rendered tree. */
export function mount(container: Container, node: VNode, factory: DomFactory): void {
  container.replaceChildren(render(node, factory));
}
