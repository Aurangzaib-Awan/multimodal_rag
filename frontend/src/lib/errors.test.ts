import { test } from "node:test";
import assert from "node:assert/strict";
import { apiBase, errorMessage } from "./errors.ts";

test("a throttled request (one Lambda instance is busy) gets a plain 'try again'", () => {
  assert.match(errorMessage(429, { Message: "Rate Exceeded." }), /busy.*try again/i);
});

test("the API's own message wins when it sent one", () => {
  assert.equal(errorMessage(404, { detail: "Session expired, please re-upload your PDF." }),
    "Session expired, please re-upload your PDF.");
});

test("anything else names the status", () => {
  assert.equal(errorMessage(502, {}), "Request failed (502).");
});

test("a Lambda Function URL's trailing slash is dropped, so paths don't become //document", () => {
  assert.equal(apiBase("https://abc.lambda-url.us-east-1.on.aws/"), "https://abc.lambda-url.us-east-1.on.aws");
  assert.equal(apiBase(undefined), "http://localhost:8000");
});
