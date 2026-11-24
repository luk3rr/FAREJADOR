// Filename: dashboard.spec.ts
// Created on: November 24, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import { expect, test } from "@playwright/test";

test("the list of reviews shows the public reviews and hides the private one", async ({ page }) => {
  await page.goto("/#/revisoes");
  await expect(page.getByRole("heading", { name: "Revisões" })).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(4);
  await expect(page.getByText("acme/billing").first()).toBeVisible();
  await expect(page.getByText("luk3rr/pilot")).toBeVisible();
  await expect(page.getByText("private-secret-repo")).toHaveCount(0);
});

test("the filters narrow the list and an empty result offers to clear them", async ({ page }) => {
  await page.goto("/#/revisoes");
  await page.getByRole("button", { name: "Falhou" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr")).toContainText("acme/web");

  await page.getByRole("button", { name: "Todos" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await page.getByLabel("Repositório", { exact: true }).fill("nao/existe");
  await page.getByRole("button", { name: "Filtrar" }).click();
  await expect(page.getByText("Nenhuma revisão com esses filtros.")).toBeVisible();
  await page.getByRole("button", { name: "Limpar filtros" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(4);
});

test("a review opens with its findings and the reasoning timeline", async ({ page }) => {
  await page.goto("/#/revisoes");
  await page.locator("tbody tr", { hasText: "acme/billing #12" }).click();
  await expect(page).toHaveURL(/#\/revisoes\/\d+$/);
  await expect(page.getByRole("heading", { name: /acme\/billing/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Achados do modelo (3)" })).toBeVisible();
  await expect(page.getByText("Senha escrita no código.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Linha do tempo do raciocínio" })).toBeVisible();
});

test("the theme can be switched between dark and light", async ({ page }) => {
  await page.goto("/#/visao-geral");
  const toggle = page.locator("[data-action='toggle-theme']");
  const before = await page.evaluate(() => document.documentElement.dataset["theme"] ?? "");
  await toggle.click();
  const after = await page.evaluate(() => document.documentElement.dataset["theme"] ?? "");
  expect(after).not.toBe(before);
  await toggle.click();
  await expect(page.evaluate(() => document.documentElement.dataset["theme"] ?? "")).resolves.toBe(before);
});

test("an API failure is shown as an error and an unknown review as not found", async ({ page }) => {
  await page.route("**/api/reviews?*", (route) => route.fulfill({ status: 500, contentType: "application/json", body: '{"error":"internal"}' }));
  await page.goto("/#/revisoes");
  await expect(page.getByRole("alert")).toBeVisible();

  await page.unroute("**/api/reviews?*");
  await page.goto("/#/revisoes/999999");
  await expect(page.getByRole("heading", { name: "Não encontramos esta revisão." })).toBeVisible();
});
