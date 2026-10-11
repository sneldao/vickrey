/* Vickrey on-device field identification.
 *
 * Talks to a local, OpenAI-compatible endpoint (Ollama, llama.cpp server, LM
 * Studio) so an open-weight model names what the camera sees with no network
 * beyond the device. The model is swappable; the trust layer never cares which
 * one ran.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyInfer = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var DEFAULT_ENDPOINT = "http://127.0.0.1:11434";
  var DEFAULT_MODEL = "gemma3";

  var PROMPT =
    "Identify the living thing or feature in this photo. Reply with strict JSON " +
    'only: {"kind":"bird|plant|tree|hazard|water|garden|other","species":"common name",' +
    '"confidence":0.0,"detail":"one short sentence"}. Set confidence low if unsure.';

  function normalizeEndpoint(endpoint) {
    var value =
      typeof endpoint === "string" && endpoint.trim()
        ? endpoint.trim()
        : DEFAULT_ENDPOINT;
    return value.replace(/\/+$/, "");
  }

  /* Pull the first JSON object out of a model reply, with a safe fallback. */
  function parseIdentification(text) {
    var fallback = {
      kind: "other",
      species: "",
      confidence: null,
      detail: typeof text === "string" ? text.trim() : "",
    };
    if (typeof text !== "string") {
      return fallback;
    }
    var start = text.indexOf("{");
    var end = text.lastIndexOf("}");
    if (start === -1 || end === -1 || end < start) {
      return fallback;
    }
    var obj;
    try {
      obj = JSON.parse(text.slice(start, end + 1));
    } catch (err) {
      return fallback;
    }
    return {
      kind: typeof obj.kind === "string" ? obj.kind : "other",
      species: typeof obj.species === "string" ? obj.species : "",
      confidence: typeof obj.confidence === "number" ? obj.confidence : null,
      detail: typeof obj.detail === "string" ? obj.detail : "",
    };
  }

  async function identify(opts) {
    opts = opts || {};
    var endpoint = normalizeEndpoint(opts.endpoint);
    var model = opts.model || DEFAULT_MODEL;
    var doFetch = opts.fetchImpl || root.fetch;
    if (typeof doFetch !== "function") {
      throw new Error("no fetch available for local inference");
    }
    if (!opts.imageBase64) {
      throw new Error("identify needs an image");
    }
    var body = {
      model: model,
      stream: false,
      temperature: 0,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: opts.prompt || PROMPT },
            {
              type: "image_url",
              image_url: { url: "data:image/jpeg;base64," + opts.imageBase64 },
            },
          ],
        },
      ],
    };
    var res = await doFetch(endpoint + "/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res || res.ok !== true) {
      throw new Error(
        "inference failed: " + (res ? res.status : "no response"),
      );
    }
    var json = await res.json();
    var text =
      json &&
      json.choices &&
      json.choices[0] &&
      json.choices[0].message &&
      json.choices[0].message.content;
    var parsed = parseIdentification(text);
    parsed.model_id = model;
    return parsed;
  }

  return {
    DEFAULT_ENDPOINT: DEFAULT_ENDPOINT,
    DEFAULT_MODEL: DEFAULT_MODEL,
    PROMPT: PROMPT,
    identify: identify,
    normalizeEndpoint: normalizeEndpoint,
    parseIdentification: parseIdentification,
  };
});
