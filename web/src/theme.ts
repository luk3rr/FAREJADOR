// Filename: theme.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Dark by default, light on request. The choice is remembered in localStorage when there is one;
// without it (private window, blocked site data) nothing breaks and the dark theme is used.

export type Theme = "dark" | "light";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const THEME_KEY = "farejador.theme";

export function loadTheme(storage: StorageLike | null): Theme {
  try {
    return storage?.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function saveTheme(storage: StorageLike | null, theme: Theme): void {
  try {
    storage?.setItem(THEME_KEY, theme);
  } catch {
    // The theme still applies to this page; it is just not remembered.
  }
}

export function toggleTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}
