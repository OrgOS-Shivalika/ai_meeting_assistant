/**
 * Base64 password transport.
 *
 * Passwords are base64-encoded before they go into a request body, so the
 * credential isn't sitting in the DevTools "Payload" pane (or a proxy log,
 * or a screenshot pasted into a ticket) as casually readable text.
 *
 * This is obfuscation, not protection. Base64 is reversible by anyone who
 * holds the payload — confidentiality in flight comes from HTTPS, and at
 * rest from the bcrypt hash on the server. Don't treat an encoded password
 * as safe to log or persist.
 *
 * The backend decodes these fields unconditionally — there is no marker
 * field and no plaintext fallback, so every password-carrying request must
 * go through here. See app/utils/password_transport.py.
 */

/**
 * Base64-encode `value` as UTF-8.
 *
 * `btoa` alone throws `InvalidCharacterError` on any code point above
 * U+00FF, so a password with an accent or emoji would break the login
 * form. Encoding to UTF-8 bytes first keeps every password legal, and the
 * server decodes with the matching utf-8 step.
 */
export function encodePassword(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

/**
 * Wrap a request body, base64-encoding the named password fields.
 *
 * The shape is otherwise unchanged — no extra fields are added, so the
 * payload looks exactly like the plaintext one with an encoded value.
 * Returns a new object; the caller's state is never mutated.
 */
export function withEncodedPasswords<T extends Record<string, unknown>>(
  body: T,
  fields: readonly (keyof T & string)[],
): T {
  const next: Record<string, unknown> = { ...body };

  for (const field of fields) {
    const raw = next[field];
    if (typeof raw === "string") {
      next[field] = encodePassword(raw);
    }
  }

  return next as T;
}
