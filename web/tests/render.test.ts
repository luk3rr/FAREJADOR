// Filename: render.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { SVG_NS, UnsafeNodeError, mount, render } from "../src/dom/render.js";
import type { Container, DomNodeLike } from "../src/dom/render.js";
import { findAll, h, textOf, withVars } from "../src/dom/vnode.js";
import { FakeElement, FakeText, allElements, allText, fakeFactory } from "./fake-dom.js";

const HOSTILE = [
  "<script>alert(1)</script>",
  '<img src=x onerror="alert(1)">',
  "</div><div onclick=alert(1)>",
  "javascript:alert(1)",
  '" onmouseover="alert(1)',
  "&lt;b&gt;&#60;i&#62;",
  "<svg onload=alert(1)>",
];

test("hostile text is rendered as one plain text node, never as markup", () => {
  for (const payload of HOSTILE) {
    const tree = h("div", {}, h("p", {}, payload), h("code", {}, payload));
    const dom = render(tree, fakeFactory) as FakeElement;
    const elements = allElements(dom);
    assert.deepEqual(
      elements.map((e) => e.tag),
      ["div", "p", "code"],
      `no element may appear out of: ${payload}`,
    );
    assert.equal(allText(dom), payload + payload);
    for (const element of elements) {
      assert.equal(element.attributes.size, 0);
    }
  }
});

test("children that are null, undefined or false are dropped and arrays are flattened", () => {
  const tree = h("ul", {}, [h("li", {}, "a"), null, h("li", {}, "b")], false, undefined, "c");
  assert.equal(textOf(tree), "abc");
  assert.equal(findAll(tree, (e) => e.tag === "li").length, 2);
});

test("attributes outside the allow-list throw, whatever their value", () => {
  for (const name of ["onclick", "onerror", "onload", "style", "srcdoc", "formaction", "innerHTML"]) {
    assert.throws(() => render(h("div", { [name]: "x" }), fakeFactory), UnsafeNodeError, name);
    assert.throws(() => render(h("div", { [name]: true }), fakeFactory), UnsafeNodeError, `${name} (true)`);
  }
  assert.throws(() => render(h("img", { src: "/assets/icon.png", onerror: "x" }), fakeFactory));
});

test("data and aria attributes are allowed with safe names only", () => {
  const dom = render(h("button", { "data-action": "retry", "aria-live": "polite" }), fakeFactory) as FakeElement;
  assert.equal(dom.attributes.get("data-action"), "retry");
  assert.equal(dom.attributes.get("aria-live"), "polite");
  assert.throws(() => render(h("div", { "data-x y": "1" }), fakeFactory), UnsafeNodeError);
  assert.throws(() => render(h("div", { "data-": "1" }), fakeFactory), UnsafeNodeError);
});

test("links only point inside the dashboard or to a GitHub pull request", () => {
  const ok = ["#/revisoes/42", "#/revisoes?repo=o%2Fr&pr=1", "https://github.com/luk3rr/FAREJADOR_PILOT/pull/1"];
  for (const href of ok) {
    const attrs = href.startsWith("https") ? { href, target: "_blank", rel: "noopener noreferrer" } : { href };
    assert.doesNotMatch(String((render(h("a", attrs), fakeFactory) as FakeElement).attributes.get("href")), /^javascript/);
  }
  const bad = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>1</script>",
    "//evil.example/x",
    "https://evil.example/pull/1",
    "https://github.com.evil.example/o/r/pull/1",
    "https://github.com/o/r/issues/1",
    "https://github.com/o/r/pull/1?x=1",
    "/revisoes/42",
    "",
  ];
  for (const href of bad) {
    assert.throws(() => render(h("a", { href }), fakeFactory), UnsafeNodeError, href);
  }
});

test("a link that opens a new tab needs noopener noreferrer", () => {
  const pr = "https://github.com/o/r/pull/1";
  assert.throws(() => render(h("a", { href: pr, target: "_blank" }), fakeFactory), UnsafeNodeError);
  assert.throws(() => render(h("a", { href: pr, target: "_top", rel: "noopener noreferrer" }), fakeFactory), UnsafeNodeError);
  assert.throws(() => render(h("a", { href: pr, target: "_blank", rel: "opener" }), fakeFactory), UnsafeNodeError);
  const dom = render(h("a", { href: pr, target: "_blank", rel: "noopener noreferrer" }, "PR"), fakeFactory) as FakeElement;
  assert.equal(dom.attributes.get("rel"), "noopener noreferrer");
});

test("images may only load files from /assets/", () => {
  assert.doesNotMatch(
    String((render(h("img", { src: "/assets/icon.png", alt: "" }), fakeFactory) as FakeElement).attributes.get("src")),
    /^http/,
  );
  for (const src of [
    "https://evil.example/x.png",
    "//evil.example/x.png",
    "data:image/png;base64,AAAA",
    "/other/x.png",
    "/assets/../x",
    "/assets/a/../../x",
  ]) {
    assert.throws(() => render(h("img", { src }), fakeFactory), UnsafeNodeError, src);
  }
});

test("dynamic values go through CSS custom properties with a strict format", () => {
  const dom = render(withVars(h("div", { class: "bar" }), { "--w": "40%", "--h": "12.5px", "--c": "var(--accent)" }), fakeFactory) as FakeElement;
  assert.equal(dom.variables.get("--w"), "40%");
  assert.equal(dom.variables.get("--c"), "var(--accent)");
  for (const [name, value] of [
    ["--w", "40%; background:url(//evil)"],
    ["--w", "url(//evil.example/x)"],
    ["--w", "expression(alert(1))"],
    ["--w", "1};x{"],
    ["width", "40%"],
    ["--W", "1"],
    ["--w", ""],
  ] as const) {
    assert.throws(() => render(withVars(h("div"), { [name]: value }), fakeFactory), UnsafeNodeError, `${name}: ${value}`);
  }
});

test("false boolean attributes are absent and true ones are empty", () => {
  const dom = render(h("button", { type: "button", disabled: true }), fakeFactory) as FakeElement;
  assert.equal(dom.attributes.get("disabled"), "");
  const off = render(h("button", { type: "button", disabled: false }), fakeFactory) as FakeElement;
  assert.equal(off.attributes.has("disabled"), false);
});

test("svg elements are created in the SVG namespace", () => {
  const tree = h("svg", { viewBox: "0 0 10 10" }, h("rect", { x: 1, y: 2, width: 3, height: 4 }), h("text", { x: 5, y: 6 }, "<b>x</b>"));
  const dom = render(tree, fakeFactory) as FakeElement;
  for (const element of allElements(dom)) {
    assert.equal(element.namespace, SVG_NS, element.tag);
  }
  assert.equal(allText(dom), "<b>x</b>");
});

test("mount replaces the content of the container with the rendered tree", () => {
  const received: DomNodeLike[][] = [];
  const container: Container = {
    replaceChildren: (...nodes) => {
      received.push(nodes);
    },
  };
  mount(container, h("p", {}, "olá"), fakeFactory);
  assert.equal(received.length, 1);
  assert.equal(received[0]?.length, 1);
  assert.equal(allText(received[0]?.[0] as FakeElement | FakeText), "olá");
  assert.ok(new FakeText("x") instanceof FakeText);
});
