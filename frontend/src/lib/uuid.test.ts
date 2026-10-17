import { test } from "node:test";
import assert from "node:assert/strict";
import { newId } from "./uuid.ts";

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test("uses crypto.randomUUID when the page is secure", () => {
  const id = "11111111-1111-4111-8111-111111111111";
  assert.equal(newId({ randomUUID: () => id, getRandomValues: (a) => a }), id);
});

test("falls back to getRandomValues on plain-HTTP pages, where randomUUID is missing", () => {
  const insecure = { getRandomValues: <T extends ArrayBufferView>(a: T) => crypto.getRandomValues(a) };
  const ids = Array.from({ length: 200 }, () => newId(insecure));
  for (const id of ids) assert.match(id, V4); // the backend only accepts real UUIDs
  assert.equal(new Set(ids).size, ids.length);
});
