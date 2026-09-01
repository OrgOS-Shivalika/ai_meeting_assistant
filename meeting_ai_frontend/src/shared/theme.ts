// Light / dark theme, per person, stored in localStorage.
//
// Same reasoning as `background.ts`: a display preference, private by
// construction, no endpoint. It does NOT follow the user to another device —
// swap the two storage calls for a fetch if that changes.
//
// The whole implementation is one class on <html>; every dark value lives in
// the `html.theme-dark` block in index.css. No component knows about themes.

const STORAGE_KEY = "ui:theme";
const DARK_CLASS = "theme-dark";

export type Theme = "light" | "dark";

export function getTheme(): Theme {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    // Private browsing or storage disabled — a theme preference is not worth
    // breaking the app over.
  }
  // No stored choice: follow the OS. Someone whose machine is in dark mode
  // should not be handed a white screen on first load.
  try {
    if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) return "dark";
  } catch {
    /* matchMedia missing in some embedded webviews */
  }
  return "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle(DARK_CLASS, theme === "dark");
}

export function setTheme(theme: Theme): void {
  applyTheme(theme);
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* see getTheme */
  }
}

/**
 * Apply the stored theme. Call from the entry module BEFORE React renders —
 * doing it in an effect paints the light theme first and then swaps, which is
 * a full-screen white flash for every dark-mode user on every page load.
 */
export function initTheme(): void {
  applyTheme(getTheme());
}
