/* Vickrey field client.
 *
 * The loop, on one page: identify offline, seal the observation with the device
 * key, chain it, and — once in range — anchor the commitment and let the ledger
 * countersign it. The seal-crack demo lives here too: edit a past entry and the
 * chain stops verifying.
 *
 * The pure parts (anchor shaping, verdicts, tamper) are exported so they can be
 * tested without a DOM; mount() is the browser-only half.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyField = api;
    var start = function () {
      api.mount(document.getElementById("app"));
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var TAG = "veles.observation";
  var SCHEMA = "veles.observation/1";
  var QUEUE_KEY = "vickrey.queue";
  var KEY_KEY = "vickrey.device_key";
  var FLOW_KEY = "vickrey.flow";

  var CONFIG_KEYS = ["ledgerUrl", "commonsUrl", "modelEndpoint", "model"];

  /* Query-string names, short for a demo URL, mapped to config keys. Both
   * spellings are accepted so a hand-written link is hard to get wrong. */
  var QUERY_KEYS = {
    ledger: "ledgerUrl",
    ledgerUrl: "ledgerUrl",
    commons: "commonsUrl",
    commonsUrl: "commonsUrl",
    endpoint: "modelEndpoint",
    modelEndpoint: "modelEndpoint",
    model: "model",
  };

  /* Merge the file's config with URL overrides, so a demo can point one page at
   * a relay and another at the commons without editing config.js. */
  function resolveConfig(base, search) {
    var out = {};
    var source = base || {};
    CONFIG_KEYS.forEach(function (key) {
      if (typeof source[key] === "string" && source[key].trim()) {
        out[key] = source[key].trim();
      }
    });
    var params;
    try {
      params = new root.URLSearchParams(search || "");
    } catch (err) {
      return out;
    }
    CONFIG_KEYS.forEach(function (key) {
      var value = params.get(key);
      if (typeof value === "string" && value.trim()) {
        out[key] = value.trim();
      }
    });
    params.forEach(function (value, name) {
      var key = QUERY_KEYS[name];
      if (key && typeof value === "string" && value.trim()) {
        out[key] = value.trim();
      }
    });
    return out;
  }

  function config() {
    var search =
      root.location && root.location.search ? root.location.search : "";
    return resolveConfig(root.VICKREY_CONFIG, search);
  }

  function trimUrl(url) {
    return String(url || "").replace(/\/+$/, "");
  }

  /* ---------------------------------------------------------------- shape */

  function shortHash(hash, keep) {
    if (typeof hash !== "string" || hash === "") {
      return "—";
    }
    var width = keep === undefined ? 10 : keep;
    return hash.length <= width * 2
      ? hash
      : hash.slice(0, width) + "…" + hash.slice(-4);
  }

  function summaryOf(entry) {
    var payload = (entry && entry.payload) || {};
    return {
      kind: payload.kind || "other",
      species: payload.species || "",
      confidence:
        typeof payload.confidence === "number" ? payload.confidence : null,
    };
  }

  function entryTitle(entry) {
    var summary = summaryOf(entry);
    if (summary.species) {
      return summary.species;
    }
    if (summary.kind && summary.kind !== "other") {
      return summary.kind + " (unidentified)";
    }
    return "unidentified observation";
  }

  /* The anchor: commitment only. No image, no notes, no precise location. */
  function anchorMessage(entry, flowId) {
    var summary = summaryOf(entry);
    return {
      flow_id: flowId || null,
      schema: SCHEMA,
      observed_at: entry.observed_at,
      location: entry.location || null,
      model_id: entry.model_id || null,
      commitment: entry.hash,
      signature: entry.signature,
      prev: entry.prev || null,
      summary: {
        kind: summary.kind,
        species: summary.species,
        confidence: summary.confidence,
      },
    };
  }

  function relayBody(entry, flowId) {
    var anchor = anchorMessage(entry, flowId);
    return {
      blockId: entry.hash,
      tag: TAG,
      message: anchor,
      flow_id: anchor.flow_id,
    };
  }

  async function drainVerified(queueImpl, publicKey, trustImpl, send) {
    var entries = queueImpl.list();
    if (!entries.length) {
      return {
        sent: [],
        remaining: [],
        error: null,
        verdict: null,
        empty: true,
      };
    }
    if (!publicKey) {
      return {
        sent: [],
        remaining: entries,
        error: new Error("the device key is not ready"),
        verdict: null,
        empty: false,
      };
    }
    var verdict = await trustImpl.verifyChain(entries, publicKey);
    if (!verdict.ok) {
      return {
        sent: [],
        remaining: entries,
        error: new Error("the local chain no longer verifies"),
        verdict: verdict,
        empty: false,
      };
    }
    var drained = await queueImpl.drain(send);
    drained.verdict = verdict;
    drained.empty = false;
    return drained;
  }

  /* ------------------------------------------------------------- verdicts */

  function verdictText(verdict) {
    if (!verdict) {
      return "Not checked yet.";
    }
    if (verdict.ok) {
      return "The seal holds: every hash recomputes, every link is intact, and every signature verifies under this device key.";
    }
    var where = "entry " + (Number(verdict.brokenAt) + 1);
    if (verdict.reason === "hash") {
      return (
        "The seal is cracked at " +
        where +
        ": the record was edited after it was signed, so its hash no longer recomputes."
      );
    }
    if (verdict.reason === "link") {
      return (
        "The seal is cracked at " +
        where +
        ": the chain link to the previous entry was broken."
      );
    }
    if (verdict.reason === "signature") {
      return (
        "The seal is cracked at " +
        where +
        ": the signature does not verify under this device key, so the entry was forged."
      );
    }
    return "The seal is cracked at " + where + ".";
  }

  var STATUS_NOTE = {
    VERIFIED:
      "Solid, milestone-referenced, and the commitment matches the anchored block.",
    PENDING: "Stored, but the block is not yet solid or has no milestone.",
    NOT_SOLID: "The commitment matches, but the block is not solid yet.",
    PAYLOAD_MISMATCH:
      "The anchored commitment no longer matches the application copy. The block never changed — the copy did.",
  };

  function statusNote(status) {
    return STATUS_NOTE[status] || "Unrecognised ledger status.";
  }

  /* --------------------------------------------------------------- tamper */

  /* A pure edit of one entry's payload, so the demo is reproducible in tests.
   * Only the payload changes: the hash and signature are left exactly as they
   * were, which is what makes the edit detectable. */
  function applyTamper(entries, index, replacement) {
    var next = (entries || []).map(function (entry) {
      return JSON.parse(JSON.stringify(entry));
    });
    if (index < 0 || index >= next.length) {
      throw new Error("no entry at index " + index);
    }
    var payload = next[index].payload || {};
    next[index].payload = {
      kind: payload.kind || "other",
      species: typeof replacement === "string" ? replacement : "Misidentified",
      confidence: payload.confidence === undefined ? null : payload.confidence,
      detail: "edited after signing",
      _demo_edited: true,
    };
    return next;
  }

  function sampleIdentification() {
    return {
      kind: "bird",
      species: "Common blackbird",
      confidence: 0.81,
      detail: "Sample identification — no local model was reachable.",
      model_id: "sample",
      sample: true,
    };
  }

  function ledgerStatus(row) {
    if (!row) {
      return { status: "UNKNOWN", note: "No response from the ledger." };
    }
    return { status: row.status, note: statusNote(row.status) };
  }

  /* --------------------------------------------------------- browser half */

  function mount(el) {
    if (!el || typeof document === "undefined") {
      return;
    }
    var trust = root.VickreyTrust;
    var depend = [
      trust,
      root.VickreyQueue,
      root.VickreyInfer,
      root.VickreyLogbook,
    ];
    if (
      depend.some(function (part) {
        return !part;
      })
    ) {
      el.innerHTML =
        '<p class="action-error">Field modules failed to load.</p>';
      return;
    }

    var store = root.VickreyQueue.localStore(QUEUE_KEY);
    var queue = root.VickreyQueue.createQueue({ store: store });
    var settings = (function (resolved) {
      var ledger = resolved.ledgerUrl || "http://localhost:8088";
      return {
        ledgerUrl: ledger,
        // The anchor relay (Messages API stand-in) and the commons API are
        // usually the same host outside a demo, but not during one.
        commonsUrl: resolved.commonsUrl || ledger,
        endpoint: resolved.modelEndpoint || "http://127.0.0.1:11434",
        model: resolved.model || "gemma3",
      };
    })(config());
    var flow =
      root.localStorage.getItem(FLOW_KEY) || "walk-" + Date.now().toString(36);
    root.localStorage.setItem(FLOW_KEY, flow);

    var state = {
      image: null,
      identifying: false,
      identifyingError: null,
      verdict: null,
      results: {},
      resultsError: null,
      similar: null,
      similarError: null,
      similarQuery: "",
      busy: false,
      publicKey: null,
      privateKey: null,
    };

    var logbook = root.VickreyLogbook.createLogbook({
      trust: trust,
      queue: queue,
      infer: root.VickreyInfer,
      privateKey: null,
      modelId: settings.model,
    });

    function keyStorage() {
      try {
        return root.localStorage;
      } catch (err) {
        return null;
      }
    }

    async function ensureKey() {
      var storage = keyStorage();
      var saved = null;
      try {
        saved = storage ? JSON.parse(storage.getItem(KEY_KEY) || "null") : null;
      } catch (err) {
        saved = null;
      }
      if (saved && saved.pk) {
        state.publicKey = await trust.importPublicKey(saved.pk);
        state.privateKey = await root.crypto.subtle.importKey(
          "jwk",
          saved.jwk,
          { name: "Ed25519" },
          true,
          ["sign"],
        );
        state.publicKeyText = saved.pk;
        return;
      }
      var pair = await trust.generateKeyPair();
      var jwk = await root.crypto.subtle.exportKey("jwk", pair.privateKey);
      var pk = await trust.exportPublicKey(pair.publicKey);
      state.privateKey = pair.privateKey;
      state.publicKey = pair.publicKey;
      state.publicKeyText = pk;
      if (storage) {
        storage.setItem(KEY_KEY, JSON.stringify({ jwk: jwk, pk: pk }));
      }
    }

    function toast(message) {
      var node = document.getElementById("toast");
      if (!node) {
        return;
      }
      node.textContent = message;
      node.classList.add("show");
      root.setTimeout(function () {
        node.classList.remove("show");
      }, 2600);
    }

    /* ------------------------------------------------------------ render */

    function entryRow(entry, index) {
      var summary = summaryOf(entry);
      var confidence =
        summary.confidence === null ? "—" : summary.confidence.toFixed(2);
      return (
        '<li class="seal-entry" data-index="' +
        index +
        '">' +
        '<div class="seal-line">' +
        '<b class="seal-title">' +
        escapeHtml(entryTitle(entry)) +
        "</b>" +
        '<span class="seal-kind">' +
        escapeHtml(summary.kind) +
        "</span>" +
        '<span class="seal-conf" title="model confidence">' +
        confidence +
        "</span>" +
        "</div>" +
        '<p class="mono seal-meta">' +
        escapeHtml(entry.observed_at || "") +
        " · prev " +
        escapeHtml(shortHash(entry.prev, 8)) +
        "</p>" +
        '<p class="mono seal-hash">hash ' +
        escapeHtml(shortHash(entry.hash, 14)) +
        " · sig " +
        escapeHtml(shortHash(entry.signature, 10)) +
        "</p>" +
        (entry.payload && entry.payload._demo_edited
          ? '<span class="stamp" data-status="PAYLOAD_MISMATCH">EDITED AFTER SIGNING</span>'
          : "") +
        "</li>"
      );
    }

    function chainPanel() {
      var entries = queue.list();
      var verdict = state.verdict;
      var banner = "";
      if (verdict) {
        var tone = verdict.ok ? "verified" : "mismatch";
        banner =
          '<p class="verdict" data-tone="' +
          tone +
          '">' +
          escapeHtml(verdictText(verdict)) +
          "</p>";
      }
      return (
        '<section class="card">' +
        '<div class="card-head"><h2>The local log</h2>' +
        '<span class="mono count">' +
        entries.length +
        " sealed</span></div>" +
        '<p class="hint">Each entry is hashed, signed with this device key, and chained to the one before it. ' +
        "Editing a past entry breaks the chain — that is the seal cracking.</p>" +
        banner +
        (entries.length
          ? '<ul class="seal-list">' +
            entries
              .map(function (entry, index) {
                return entryRow(entry, index);
              })
              .join("") +
            "</ul>"
          : '<p class="empty">Nothing sealed yet. Identify something to start the log.</p>') +
        '<div class="row actions">' +
        '<button type="button" data-act="verify"' +
        (entries.length ? "" : " disabled") +
        ">Verify chain</button>" +
        '<button type="button" class="danger" data-act="tamper"' +
        (entries.length ? "" : " disabled") +
        ">Edit the last entry</button>" +
        '<button type="button" class="primary" data-act="sync"' +
        (entries.length ? "" : " disabled") +
        ">Sync to the ledger</button>" +
        "</div>" +
        (state.resultsError
          ? '<p class="action-error">' + escapeHtml(state.resultsError) + "</p>"
          : "") +
        resultsPanel() +
        "</section>"
      );
    }

    function resultsPanel() {
      var entries = queue.list();
      var keys = Object.keys(state.results);
      if (!keys.length) {
        return "";
      }
      return (
        '<div class="results">' +
        "<h3>Ledger countersignature</h3>" +
        keys
          .map(function (hash) {
            var result = ledgerStatus(state.results[hash]);
            var entry = null;
            for (var i = 0; i < entries.length; i++) {
              if (entries[i].hash === hash) {
                entry = entries[i];
              }
            }
            return (
              '<div class="result">' +
              '<div class="result-head">' +
              '<span class="stamp" data-status="' +
              escapeHtml(result.status) +
              '">' +
              escapeHtml(result.status) +
              "</span>" +
              '<span class="seal-title">' +
              escapeHtml(entry ? entryTitle(entry) : shortHash(hash, 8)) +
              "</span>" +
              "</div>" +
              '<p class="hint">' +
              escapeHtml(result.note) +
              "</p>" +
              '<p class="mono seal-meta">block ' +
              escapeHtml(
                (state.results[hash] && state.results[hash].block_id) || "—",
              ) +
              " · milestone " +
              escapeHtml(
                String(
                  state.results[hash] &&
                    state.results[hash].milestone_index !== null
                    ? state.results[hash].milestone_index
                    : "—",
                ),
              ) +
              "</p>" +
              "</div>"
            );
          })
          .join("") +
        "</div>"
      );
    }

    function similarPanel() {
      var body;
      if (state.similarError) {
        body =
          '<p class="action-error">' + escapeHtml(state.similarError) + "</p>";
      } else if (state.similar === null) {
        body =
          '<p class="hint">When configured, Atlas Vector Search finds related anchored sightings. ' +
          "It returns labels and commitments, never raw records.</p>";
      } else if (!state.similar.length) {
        body = '<p class="empty">No similar anchored sightings yet.</p>';
      } else {
        body =
          '<ul class="similar">' +
          state.similar
            .map(function (hit) {
              return (
                "<li><b>" +
                escapeHtml(hit.label || "unlabelled") +
                "</b>" +
                '<span class="mono"> · ' +
                escapeHtml(shortHash(hit.commitment, 10)) +
                " · " +
                escapeHtml(hit.observed_at || "") +
                (typeof hit.score === "number"
                  ? " · " + hit.score.toFixed(3)
                  : "") +
                "</span></li>"
              );
            })
            .join("") +
          "</ul>";
      }
      return (
        '<section class="card">' +
        '<div class="card-head"><h2>Similar sightings</h2>' +
        '<span class="mono count">atlas optional</span></div>' +
        '<div class="row">' +
        '<input type="search" id="similar-q" placeholder="species or kind" value="' +
        escapeHtml(state.similarQuery) +
        '" />' +
        '<button type="button" data-act="similar">Search the commons</button>' +
        "</div>" +
        body +
        "</section>"
      );
    }

    function capturePanel() {
      var preview = state.image
        ? '<img class="shot" alt="captured observation" src="' +
          state.image.preview +
          '" />'
        : '<div class="shot shot-empty">no photo yet</div>';
      return (
        '<section class="card">' +
        '<div class="card-head"><h2>Identify &amp; seal</h2>' +
        '<span class="mono count">device seal</span></div>' +
        '<div class="capture">' +
        preview +
        '<div class="capture-side">' +
        '<label class="file">' +
        "<span>Take or choose a photo</span>" +
        '<input type="file" accept="image/*" capture="environment" id="photo" />' +
        "</label>" +
        '<details class="endpoints"><summary>Model endpoint</summary>' +
        '<form id="model-form">' +
        '<label>Endpoint<input name="endpoint" value="' +
        escapeHtml(settings.endpoint) +
        '" /></label>' +
        '<label>Model<input name="model" value="' +
        escapeHtml(settings.model) +
        '" /></label>' +
        '<p class="hint">Any OpenAI-compatible endpoint, local or reachable through a private tunnel. ' +
        "A hosted model receives the photo; choose local inference for offline privacy. " +
        "If nothing answers, use the labelled sample identification.</p>" +
        "</form></details>" +
        '<div class="row">' +
        '<button type="button" class="primary" data-act="identify"' +
        (state.image && !state.identifying && state.privateKey
          ? ""
          : " disabled") +
        ">" +
        (state.identifying ? "Identifying…" : "Identify &amp; seal") +
        "</button>" +
        '<button type="button" class="ghost" data-act="sample"' +
        (state.privateKey ? "" : " disabled") +
        ">Use sample identification</button>" +
        "</div>" +
        (state.identifyingError
          ? '<p class="action-error">' +
            escapeHtml(state.identifyingError) +
            "</p>"
          : "") +
        "</div></div>" +
        '<p class="mono device">device key ' +
        escapeHtml(shortHash(state.publicKeyText, 12)) +
        "</p>" +
        "</section>"
      );
    }

    function render() {
      el.innerHTML =
        '<div class="field-grid">' +
        '<div class="col">' +
        capturePanel() +
        chainPanel() +
        "</div>" +
        '<div class="col"><div class="detail">' +
        similarPanel() +
        helpPanel() +
        "</div></div>" +
        "</div>";
      wire();
    }

    function helpPanel() {
      return (
        '<section class="card">' +
        "<h2>How to read this</h2>" +
        '<ul class="help">' +
        "<li><b>Sealed.</b> The hash is the commitment; the signature proves this device sealed it before any upload.</li>" +
        "<li><b>Cracked.</b> Edit a past entry and the hash no longer recomputes. Signatures prove who, hashes prove what.</li>" +
        "<li><b>Anchored.</b> The commitment, signature, timestamp, coarse location and species summary reach the ledger. Raw photos and notes are not anchored; a hosted model receives the photo for inference.</li>" +
        "<li><b>Countersigned.</b> The ledger independently reads the block: solid, milestone-referenced, and still matching.</li>" +
        "</ul>" +
        "</section>"
      );
    }

    /* -------------------------------------------------------------- wiring */

    function escapeHtml(value) {
      return String(value === null || value === undefined ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function readFile(file) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onload = function () {
          var text = String(reader.result || "");
          var comma = text.indexOf(",");
          resolve({
            preview: text,
            base64: comma === -1 ? text : text.slice(comma + 1),
          });
        };
        reader.onerror = function () {
          reject(new Error("could not read the photo"));
        };
        reader.readAsDataURL(file);
      });
    }

    function wire() {
      var photo = el.querySelector("#photo");
      if (photo) {
        photo.addEventListener("change", async function (event) {
          var file = event.target.files && event.target.files[0];
          if (!file) {
            return;
          }
          try {
            state.image = await readFile(file);
            state.identifyingError = null;
          } catch (err) {
            state.identifyingError = err.message;
          }
          render();
        });
      }
      var form = el.querySelector("#model-form");
      if (form) {
        form.addEventListener("change", function () {
          settings.endpoint = form.endpoint.value.trim() || settings.endpoint;
          settings.model = form.model.value.trim() || settings.model;
        });
      }
      var query = el.querySelector("#similar-q");
      if (query) {
        query.addEventListener("input", function () {
          state.similarQuery = query.value;
        });
      }
      el.querySelectorAll("[data-act]").forEach(function (node) {
        node.addEventListener("click", function () {
          var act = node.getAttribute("data-act");
          if (act === "verify") {
            verify();
          } else if (act === "tamper") {
            tamper();
          } else if (act === "sync") {
            sync();
          } else if (act === "sample") {
            seal(sampleIdentification());
          } else if (act === "identify") {
            identify();
          } else if (act === "similar") {
            similar();
          }
        });
      });
    }

    /* ------------------------------------------------------------ actions */

    async function identify() {
      if (!state.image) {
        return;
      }
      state.identifying = true;
      state.identifyingError = null;
      render();
      var id;
      try {
        id = await root.VickreyInfer.identify({
          imageBase64: state.image.base64,
          endpoint: settings.endpoint,
          model: settings.model,
        });
      } catch (err) {
        state.identifying = false;
        state.identifyingError =
          "No local model answered at " +
          settings.endpoint +
          ". Start one, or use the sample identification. (" +
          err.message +
          ")";
        render();
        return;
      }
      state.identifying = false;
      await seal(id);
    }

    async function seal(id) {
      if (!state.privateKey) {
        state.identifyingError =
          "The device key is not ready yet — sealing needs it. Wait a moment, or reload the page if it never appears.";
        render();
        return;
      }
      try {
        var entry = await logbook.seal(id, {
          privateKey: state.privateKey,
          model: settings.model,
          observedAt: new Date().toISOString(),
          location: coarseFromBrowser(),
        });
        state.verdict = null;
        toast("Sealed " + entryTitle(entry));
      } catch (err) {
        state.identifyingError = err.message;
      }
      render();
    }

    function coarseFromBrowser() {
      var location = config().location;
      if (location && typeof location.lat === "number") {
        return root.VickreyTrust.coarseLocation(location, 2);
      }
      return null;
    }

    async function verify() {
      var entries = queue.list();
      state.verdict = await root.VickreyTrust.verifyChain(
        entries,
        state.publicKey,
      );
      render();
    }

    function tamper() {
      var entries = queue.list();
      if (!entries.length) {
        return;
      }
      var last = entries.length - 1;
      var mutated = applyTamper(entries, last, "Misidentified magpie");
      entries[last].payload = mutated[last].payload;
      store.save(entries);
      state.verdict = null;
      state.results = {};
      toast("Edited the last entry — now verify the chain");
      render();
    }

    async function sync() {
      state.busy = true;
      state.resultsError = null;
      render();
      var drained = await drainVerified(
        queue,
        state.publicKey,
        root.VickreyTrust,
        function (entry) {
          return postAnchor(entry);
        },
      );
      if (drained.empty) {
        state.busy = false;
        render();
        return;
      }
      if (drained.verdict) {
        state.verdict = drained.verdict;
      }
      drained.sent.forEach(function (entry) {
        if (entry.__ledger) {
          state.results[entry.hash] = entry.__ledger;
        }
      });
      // The queue keeps unsent entries; results are read from the sent ones.
      var sent = drained.sent.length;
      if (drained.error) {
        if (sent) {
          state.resultsError =
            "Sync stopped at " +
            (sent + 1) +
            " of " +
            (sent + drained.remaining.length) +
            ": " +
            drained.error.message +
            ". Unsent records stayed on the device.";
        } else {
          state.resultsError =
            "Sync refused: " +
            drained.error.message +
            ". Nothing was sent; the records stayed on the device.";
        }
      } else {
        toast("Anchored " + sent + " observation" + (sent === 1 ? "" : "s"));
      }
      state.busy = false;
      render();
    }

    async function postAnchor(entry) {
      var body = relayBody(entry, flow);
      var response = await root.fetch(trimUrl(settings.ledgerUrl) + "/ingest", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      var row = null;
      try {
        row = await response.json();
      } catch (err) {
        row = null;
      }
      if (!response.ok) {
        throw new Error("ledger returned " + response.status);
      }
      entry.__ledger = row;
      return row;
    }

    async function similar() {
      var query = state.similarQuery.trim();
      if (!query) {
        state.similarError = "Type something to search for.";
        render();
        return;
      }
      state.similar = null;
      state.similarError = null;
      render();
      try {
        var url =
          trimUrl(settings.commonsUrl) +
          "/observations/similar?limit=8&q=" +
          encodeURIComponent(query);
        var response = await root.fetch(url);
        var body = await response.json();
        if (!response.ok) {
          throw new Error(body.detail || "ledger returned " + response.status);
        }
        state.similar = body.observations || [];
      } catch (err) {
        state.similarError = String(err.message || err);
      }
      render();
    }

    /* ---------------------------------------------------------------- boot */

    ensureKey()
      .catch(function (err) {
        state.identifyingError =
          "Could not create a device key: " +
          err.message +
          ". Sealing needs Web Crypto — serve this page over https or localhost, then reload.";
      })
      .then(function () {
        render();
      });
    render();
  }

  return {
    TAG: TAG,
    SCHEMA: SCHEMA,
    QUEUE_KEY: QUEUE_KEY,
    KEY_KEY: KEY_KEY,
    anchorMessage: anchorMessage,
    applyTamper: applyTamper,
    drainVerified: drainVerified,
    entryTitle: entryTitle,
    ledgerStatus: ledgerStatus,
    mount: mount,
    relayBody: relayBody,
    resolveConfig: resolveConfig,
    sampleIdentification: sampleIdentification,
    shortHash: shortHash,
    statusNote: statusNote,
    summaryOf: summaryOf,
    verdictText: verdictText,
  };
});
