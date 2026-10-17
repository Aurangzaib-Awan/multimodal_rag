type Random = { randomUUID?: () => string; getRandomValues: <T extends ArrayBufferView>(a: T) => T };

/** A v4 UUID. crypto.randomUUID only exists on HTTPS or localhost pages; getRandomValues works everywhere. */
export function newId(c: Random = globalThis.crypto): string {
  if (c.randomUUID) return c.randomUUID();
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
