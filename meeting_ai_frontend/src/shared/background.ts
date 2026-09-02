// Per-user page background.
//
// Stored in localStorage, not on the server, for three reasons:
//   1. "Only visible to them" is then structural rather than enforced — the
//      value never leaves their machine, so there is no endpoint to get the
//      scoping wrong on.
//   2. It matches what this app already does for per-person UI state
//      (`sidebar:collapsed`, `sidebar:scroll` in Sidebar.tsx).
//   3. No migration, no endpoint, no request on every page load.
//
// The trade-off, stated plainly: the choice does NOT follow the user to
// another browser or device. Moving it to a `users` column later is a small
// change — this module is the only thing that touches storage, so swapping the
// two functions below for a fetch is the whole job.
//
// Implementation is a single CSS custom property. `--vb-canvas` is the design
// system's "default page floor" (styles/vibrant-tokens/colors.css), so
// overriding it on :root repaints every surface built on `bg-canvas` without
// touching a single component.

const STORAGE_KEY = "ui:background";
const IMAGE_KEY = "ui:background-image";
const CANVAS_VAR = "--vb-canvas";

export interface BackgroundOption {
  id: string;
  label: string;
  /** The colour written into `--vb-canvas`. */
  value: string;
}

// Deliberately a small, curated set rather than a free colour picker: every
// one of these has been eyeballed against `--vb-ink` (#0a0a0a) body text, and
// an arbitrary picker lets someone choose a background their text vanishes on.
export const BACKGROUNDS: BackgroundOption[] = [
  { id: "cream", label: "Cream", value: "#fffaf0" }, // the shipped default
  { id: "paper", label: "Paper", value: "#ffffff" },
  { id: "mist", label: "Mist", value: "#f4f6f8" },
  { id: "sage", label: "Sage", value: "#f1f5f0" },
  { id: "sand", label: "Sand", value: "#f7f3ea" },
  { id: "blush", label: "Blush", value: "#fdf3f3" },
  { id: "sky", label: "Sky", value: "#f0f5fb" },
  { id: "lavender", label: "Lavender", value: "#f5f2fb" },
];

export const DEFAULT_BACKGROUND_ID = "cream";

/** The stored choice, or the default. Never throws. */
export function getBackgroundId(): string {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    // Validate against the known set: a stale id from a removed option must
    // fall back to the default rather than writing `undefined` into the CSS
    // variable, which would blank the page.
    if (saved && BACKGROUNDS.some((b) => b.id === saved)) return saved;
  } catch {
    // Private browsing, or storage disabled. A background preference is not
    // worth breaking the app over.
  }
  return DEFAULT_BACKGROUND_ID;
}

/** Paint a background id onto the document. Safe to call before React mounts. */
export function applyBackground(id: string): void {
  const option =
    BACKGROUNDS.find((b) => b.id === id) ??
    BACKGROUNDS.find((b) => b.id === DEFAULT_BACKGROUND_ID)!;

  // In dark mode the preset is NOT applied. Every preset is a light cream and
  // this writes an INLINE custom property, which outranks the
  // `html.theme-dark` class rule — so applying one would hand a dark-mode user
  // a cream page floor with light text on it. Removing the property instead
  // lets the theme govern, and the choice stays stored so it returns intact
  // when they switch back to light.
  if (document.documentElement.classList.contains("theme-dark")) {
    document.documentElement.style.removeProperty(CANVAS_VAR);
    return;
  }
  document.documentElement.style.setProperty(CANVAS_VAR, option.value);
}

/** Persist and apply. Storage failure still applies for this session. */
export function setBackground(id: string): void {
  applyBackground(id);
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* see getBackgroundId */
  }
}

/**
 * Apply the saved choice. Call from the entry module, BEFORE React renders —
 * doing it in a component's effect paints the default first and then swaps,
 * which reads as a flash of the wrong colour on every page load.
 */
export function initBackground(): void {
  applyBackground(getBackgroundId());
  // An image wins over the colour preset when both are set — the colour stays
  // stored so removing the image reveals it again rather than snapping to the
  // default.
  applyBackgroundImage(getBackgroundImage());
}


// ---------------------------------------------------------------------------
// Custom background images
// ---------------------------------------------------------------------------
//
// The picked file is downscaled in a canvas and stored as a data URL in
// localStorage. It therefore never leaves the machine — the same "private by
// construction" property as the colour presets, and no upload endpoint to get
// the scoping wrong on.
//
// Downscaling is not cosmetic, it is what makes this possible at all:
// localStorage holds roughly 5MB and a phone photo is 3-8MB, so storing the
// original would fail on most real images. 1920px wide at JPEG 0.82 lands
// around 200-400KB, which is indistinguishable as a full-screen background.

const MAX_WIDTH = 1920;
const JPEG_QUALITY = 0.82;

/** A File -> downscaled JPEG data URL. Rejects on a non-image or decode failure. */
export function fileToBackgroundDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith("image/")) {
      reject(new Error("That file isn't an image."));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Couldn't read that file."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Couldn't decode that image."));
      img.onload = () => {
        const scale = Math.min(1, MAX_WIDTH / (img.width || MAX_WIDTH));
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error("Couldn't process that image."));
          return;
        }
        // JPEG has no alpha, so a transparent PNG would composite onto black.
        // Paint white first.
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", JPEG_QUALITY));
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

export function getBackgroundImage(): string | null {
  try {
    return window.localStorage.getItem(IMAGE_KEY);
  } catch {
    return null;
  }
}

/** Store + apply a data URL. Throws a readable error if the quota is blown. */
export function setBackgroundImage(dataUrl: string): void {
  try {
    window.localStorage.setItem(IMAGE_KEY, dataUrl);
  } catch {
    throw new Error(
      "That image is too large to save in this browser. Try a smaller one.",
    );
  }
  applyBackgroundImage(dataUrl);
}

export function clearBackgroundImage(): void {
  try {
    window.localStorage.removeItem(IMAGE_KEY);
  } catch {
    /* see getBackgroundId */
  }
  applyBackgroundImage(null);
  applyBackground(getBackgroundId());
}

/** Paint (or remove) the image. The class is what index.css hangs the
 *  transparency rules off — without it, body would cover the image. */
export function applyBackgroundImage(dataUrl: string | null): void {
  const root = document.documentElement;
  if (dataUrl) {
    // No overlay — the image is shown exactly as picked.
    //
    // Safe here in a way it was not when surfaces were translucent: cards, the
    // sidebar and every panel stay opaque, so body text never sits directly on
    // the photo. Only the page floor between them shows it. Do not add a scrim
    // back without also making surfaces see-through, or it dims the picture
    // for no reader benefit.
    root.style.backgroundImage = `url("${dataUrl}")`;
    root.classList.add("has-bg-image");
  } else {
    root.style.removeProperty("background-image");
    root.classList.remove("has-bg-image");
  }
}
