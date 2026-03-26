import test from "node:test";
import assert from "node:assert/strict";

import {
  buildCodexTurnOptions,
  buildOpencodePromptBody,
  combinePrompts,
  ensureOpencodeProviders,
  extractTextParts,
} from "../lib/runtime.mjs";

test("combinePrompts leaves prompt untouched when no system prompt", () => {
  assert.equal(combinePrompts("", "hello"), "hello");
});

test("combinePrompts prefixes system instructions", () => {
  const result = combinePrompts("be precise", "do work");
  assert.match(result, /System Instructions/);
  assert.match(result, /be precise/);
  assert.match(result, /User Request/);
  assert.match(result, /do work/);
});

test("extractTextParts flattens nested text parts", () => {
  const parts = [
    { text: "top" },
    { parts: [{ text: "nested" }] },
    { ignored: true },
  ];
  assert.equal(extractTextParts(parts), "top\nnested");
});

test("buildCodexTurnOptions includes the output schema when present", () => {
  const schema = { type: "object", properties: { ok: { type: "boolean" } } };
  assert.deepEqual(buildCodexTurnOptions(schema), { outputSchema: schema });
  assert.equal(buildCodexTurnOptions(undefined), undefined);
});

test("buildOpencodePromptBody preserves system prompt, model, and schema", () => {
  const schema = { type: "object", properties: { summary: { type: "string" } } };
  const body = buildOpencodePromptBody({
    prompt: "hello",
    systemPrompt: "system",
    outputSchema: schema,
    model: "openai/gpt-5.4",
  });

  assert.equal(body.system, "system");
  assert.deepEqual(body.parts, [{ type: "text", text: "hello" }]);
  assert.deepEqual(body.format, { type: "json_schema", schema });
  assert.deepEqual(body.model, { providerID: "openai", modelID: "gpt-5.4" });
});

test("ensureOpencodeProviders fails when no providers are configured", () => {
  assert.throws(
    () => ensureOpencodeProviders({ data: { providers: [] } }),
    /No OpenCode providers configured/
  );
});
