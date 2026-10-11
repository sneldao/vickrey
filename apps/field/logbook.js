/* Vickrey logbook.
 *
 * The field client's spine: identify offline, seal the observation, queue it,
 * and drain the queue when back in range. Dependencies are injected so the same
 * module runs in the browser (globals) and in tests.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyLogbook = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  /* What gets signed. A human review travels inside the payload, so the
   * decision is sealed with the observation and cannot be added later. */
  function payloadOf(id) {
    var payload = {
      kind: id.kind,
      species: id.species,
      confidence: id.confidence,
      detail: id.detail,
    };
    if (id.review && typeof id.review === "object") {
      payload.review = id.review;
    }
    return payload;
  }

  function createLogbook(opts) {
    opts = opts || {};
    var trust = opts.trust || root.VickreyTrust;
    var queue =
      opts.queue || (root.VickreyQueue && root.VickreyQueue.createQueue());
    var infer = opts.infer || root.VickreyInfer;
    if (!trust || !queue || !infer) {
      throw new Error("logbook needs trust, a queue instance, and infer");
    }
    var head = opts.head || null;
    if (!head) {
      var pending = queue.list();
      head = pending.length ? pending[pending.length - 1].hash : null;
    }

    async function seal(id, input) {
      id = id || {};
      input = input || {};
      var privateKey = input.privateKey || opts.privateKey;
      if (!privateKey) {
        throw new Error(
          "no device key to seal with — generate or restore one first",
        );
      }
      var entry = await trust.sealObservation({
        privateKey: privateKey,
        prev: head,
        observedAt: input.observedAt,
        location: input.location,
        modelId: id.model_id || input.model || opts.modelId,
        payload: payloadOf(id),
      });
      head = entry.hash;
      queue.enqueue(entry);
      return entry;
    }

    /* Identify a photo offline, seal it, and queue it for later sync. */
    async function observe(input) {
      input = input || {};
      var id = await infer.identify({
        imageBase64: input.imageBase64,
        endpoint: input.endpoint,
        model: input.model || opts.modelId,
        prompt: input.prompt,
        fetchImpl: input.fetchImpl,
      });
      return seal(id, input);
    }

    /* Drain queued observations to a sender once signal returns. */
    function sync(send) {
      return queue.drain(send);
    }

    return {
      observe: observe,
      seal: seal,
      sync: sync,
      pending: function () {
        return queue.list();
      },
      size: function () {
        return queue.size();
      },
      head: function () {
        return head;
      },
    };
  }

  return { createLogbook: createLogbook, payloadOf: payloadOf };
});
