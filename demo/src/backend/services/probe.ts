// Helpers for building the IntegrationProbe payloads shown by the
// "Check Integrations" panel. Tokens are masked and response bodies are
// truncated so the UI stays readable and we never leak full credentials.

/** Mask a bearer token to "Bearer abc12…xyz", or "(not set)" when empty. */
export function maskToken(token: string): string {
  if (!token) return "(not set)";
  const t = token.startsWith("Bearer ") ? token.slice(7) : token;
  if (t.length <= 8) return "Bearer ****";
  return `Bearer ${t.slice(0, 5)}…${t.slice(-3)}`;
}

/** Replace a sensitive value in a copied request body with a masked preview. */
export function maskValue(value: string): string {
  if (!value) return "(not set)";
  if (value.length <= 8) return "****";
  return `${value.slice(0, 5)}…${value.slice(-3)}`;
}

/** Pretty-print and truncate a value for display in a <pre> block. */
export function preview(value: unknown, max = 1500): string {
  let str: string;
  if (typeof value === "string") {
    str = value;
  } else {
    // JSON.stringify returns undefined for undefined / functions / symbols.
    str = JSON.stringify(value, null, 2) ?? String(value);
  }
  if (str.length <= max) return str;
  return `${str.slice(0, max)}\n… (truncated, ${str.length} chars total)`;
}
