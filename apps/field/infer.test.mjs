import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const infer = require("./infer.js");

test("parseIdentification extracts strict JSON from a chatty reply", () => {
  const parsed = infer.parseIdentification(
    'Sure! {"kind":"bird","species":"Common blackbird","confidence":0.82,"detail":"singing"} hope that helps',
  );
  assert.equal(parsed.kind, "bird");
  assert.equal(parsed.species, "Common blackbird");
  assert.equal(parsed.confidence, 0.82);
  assert.equal(parsed.detail, "singing");
});

test("parseIdentification falls back to prose on a reply with no JSON", () => {
  const parsed = infer.parseIdentification("I cannot tell from this photo");
  assert.equal(parsed.kind, "other");
  assert.equal(parsed.species, "");
  assert.equal(parsed.confidence, null);
  assert.equal(parsed.detail, "I cannot tell from this photo");
});

test("identify posts to the local endpoint and stamps the model id", async () => {
  let captured = null;
  const fetchImpl = async (url, init) => {
    captured = { url, body: JSON.parse(init.body) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        choices: [
          {
            message: {
              content:
                '{"kind":"plant","species":"Foxglove","confidence":0.7,"detail":"in shade"}',
            },
          },
        ],
      }),
    };
  };
  const result = await infer.identify({
    imageBase64: "AAAA",
    endpoint: "http://127.0.0.1:11434/",
    model: "gemma3:4b",
    fetchImpl,
  });
  assert.equal(captured.url, "http://127.0.0.1:11434/v1/chat/completions");
  assert.equal(captured.body.model, "gemma3:4b");
  assert.equal(
    captured.body.messages[0].content[1].image_url.url,
    "data:image/jpeg;base64,AAAA",
  );
  assert.equal(result.species, "Foxglove");
  assert.equal(result.model_id, "gemma3:4b");
});

test("identify throws on a failed response", async () => {
  const fetchImpl = async () => ({
    ok: false,
    status: 500,
    json: async () => ({}),
  });
  await assert.rejects(
    () => infer.identify({ imageBase64: "AAAA", fetchImpl }),
    /inference failed: 500/,
  );
});

test("identify requires an image", async () => {
  await assert.rejects(
    () => infer.identify({ fetchImpl: async () => ({}) }),
    /needs an image/,
  );
});
