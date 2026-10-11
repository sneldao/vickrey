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
  var JOURNAL_KEY = "vickrey.journal";

  var CONFIG_KEYS = [
    "ledgerUrl",
    "commonsUrl",
    "modelEndpoint",
    "model",
    "ledgerLabel",
    "area",
  ];

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
    ledgerLabel: "ledgerLabel",
    area: "area",
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
      summary: reviewDecision(entry)
        ? {
            kind: summary.kind,
            species: summary.species,
            confidence: summary.confidence,
            review: reviewDecision(entry),
          }
        : {
            kind: summary.kind,
            species: summary.species,
            confidence: summary.confidence,
          },
    };
  }

  function reviewDecision(entry) {
    var review = entry && entry.payload && entry.payload.review;
    return review && typeof review.decision === "string"
      ? review.decision
      : null;
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

  /* ------------------------------------------------------------- review */

  /* A model only ever suggests. A person confirms or corrects the suggestion,
   * and that decision is sealed with the record. Nothing is sealed without it. */
  function reviewedIdentification(suggestion, decision) {
    if (!suggestion) {
      throw new Error("there is no suggestion to review");
    }
    var action = decision && decision.action;
    if (action !== "confirm" && action !== "correct") {
      throw new Error(
        "a person must confirm or correct the suggestion before it is sealed",
      );
    }
    var suggestedSpecies =
      typeof suggestion.species === "string" ? suggestion.species.trim() : "";
    var suggestedKind = suggestion.kind || "other";
    var modelConfidence =
      typeof suggestion.confidence === "number" ? suggestion.confidence : null;
    var species = suggestedSpecies;
    var kind = suggestedKind;
    if (action === "correct") {
      species =
        typeof decision.species === "string" ? decision.species.trim() : "";
      kind = decision.kind || suggestedKind;
    }
    if (!species) {
      throw new Error(
        action === "confirm"
          ? "the model named nothing — correct it before sealing"
          : "write the name you are sure of before sealing",
      );
    }
    var corrected =
      action === "correct" &&
      (species !== suggestedSpecies || kind !== suggestedKind);
    return {
      kind: kind,
      species: species,
      // A correction is the observer's call; the model's score belongs to its
      // own suggestion, so it is kept in the review, not on the final name.
      confidence: corrected ? null : modelConfidence,
      detail: suggestion.detail || "",
      model_id: suggestion.model_id || null,
      sample: suggestion.sample === true,
      review: {
        decision: corrected ? "corrected" : "confirmed",
        suggested_species: suggestedSpecies,
        suggested_kind: suggestedKind,
        model_confidence: modelConfidence,
      },
    };
  }

  /* ------------------------------------------------------------ journal */

  function samePayload(a, b) {
    return JSON.stringify(canonicalize(a)) === JSON.stringify(canonicalize(b));
  }

  function canonicalize(value) {
    if (value === null || typeof value !== "object") {
      return value;
    }
    if (Array.isArray(value)) {
      return value.map(canonicalize);
    }
    var out = {};
    Object.keys(value)
      .sort()
      .forEach(function (key) {
        out[key] = canonicalize(value[key]);
      });
    return out;
  }

  /* One row per sighting, newest first: the journal's sealed copy, where it
   * stands (waiting in the outbox, anchored, or cracked), and the outbox copy
   * when it no longer matches what was sealed. */
  function journalView(records, outboxEntries, verdict) {
    var outbox = {};
    (outboxEntries || []).forEach(function (entry, index) {
      outbox[entry.hash] = { entry: entry, index: index };
    });
    var brokenHash =
      verdict && !verdict.ok && outboxEntries && outboxEntries[verdict.brokenAt]
        ? outboxEntries[verdict.brokenAt].hash
        : null;
    return (records || [])
      .map(function (record) {
        var hash = record.entry.hash;
        var queued = outbox[hash] || null;
        var edited = !!(
          queued && !samePayload(queued.entry.payload, record.entry.payload)
        );
        var state;
        if (record.sync && record.sync.state === "anchored") {
          state = "anchored";
        } else if (edited || hash === brokenHash) {
          state = "cracked";
        } else if (queued) {
          state = "waiting";
        } else {
          state = "local";
        }
        return {
          hash: hash,
          entry: record.entry,
          thumb: record.thumb || null,
          sync: record.sync || { state: "pending" },
          state: state,
          refused: !!(record.sync && record.sync.state === "refused"),
          queuedCopy: edited ? queued.entry : null,
        };
      })
      .reverse();
  }

  /* Write a sync outcome into the journal: every sent entry is marked with
   * its ledger row; a refusal is pinned to the entry that broke the chain. */
  function settleSync(journal, drained, rows) {
    rows = rows || {};
    (drained.sent || []).forEach(function (entry) {
      journal.markAnchored(entry.hash, rows[entry.hash] || null);
    });
    if (drained.verdict && !drained.verdict.ok) {
      var broken = (drained.remaining || [])[drained.verdict.brokenAt];
      if (broken) {
        journal.markRefused(broken.hash, "the local chain no longer verifies");
      }
    }
    return journal.list();
  }

  function parseArea(text) {
    if (typeof text !== "string") {
      return null;
    }
    var parts = text.split(",").map(function (part) {
      return Number(part.trim());
    });
    if (
      parts.length !== 2 ||
      !isFinite(parts[0]) ||
      !isFinite(parts[1]) ||
      Math.abs(parts[0]) > 90 ||
      Math.abs(parts[1]) > 180
    ) {
      return null;
    }
    return { lat: parts[0], lon: parts[1] };
  }

  /* --------------------------------------------------------- browser half */

  var STATE_LABEL = {
    waiting: "In the outbox — waiting to sync",
    anchored: "Anchored",
    cracked: "Seal cracked",
    local: "On this device only",
  };

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
      root.VickreyJournal,
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
    var journal = root.VickreyJournal.createJournal({ key: JOURNAL_KEY });
    journal.adopt(queue.list());
    var resolved = config();
    var settings = (function () {
      var ledger = resolved.ledgerUrl || "http://localhost:8088";
      return {
        ledgerUrl: ledger,
        // The anchor relay (Messages API stand-in) and the commons API are
        // usually the same host outside a demo, but not during one.
        commonsUrl: resolved.commonsUrl || ledger,
        endpoint: resolved.modelEndpoint || "http://127.0.0.1:11434",
        model: resolved.model || "gemma3",
        ledgerLabel: resolved.ledgerLabel || "mock Hornet demo",
        area: parseArea(resolved.area),
      };
    })();
    var flow =
      root.localStorage.getItem(FLOW_KEY) || "walk-" + Date.now().toString(36);
    root.localStorage.setItem(FLOW_KEY, flow);

    var state = {
      image: null,
      step: "photo",
      suggestion: null,
      correcting: false,
      identifyStarted: 0,
      error: null,
      verdict: null,
      syncError: null,
      busy: false,
      justSealed: null,
      lastSealed: null,
      justCracked: null,
      open: {},
      similar: {},
      publicKey: null,
      privateKey: null,
      publicKeyText: "",
    };
    var ticker = null;

    var logbook = root.VickreyLogbook.createLogbook({
      trust: trust,
      queue: queue,
      infer: root.VickreyInfer,
      privateKey: null,
      modelId: settings.model,
      // Continue the chain from the journal, not the outbox: after a sync the
      // outbox is empty but the next sighting still links to the last one.
      head: journal.head(),
    });

    var badge = document.getElementById("ledger-label");
    if (badge) {
      badge.textContent = "Ledger: " + settings.ledgerLabel;
    }

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

    function escapeHtml(value) {
      return String(value === null || value === undefined ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    /* ------------------------------------------------------------ render */

    function sealMark(kind, extraClass) {
      return (
        '<svg class="wax ' +
        (extraClass || "") +
        '" data-kind="' +
        kind +
        '" viewBox="0 0 48 48" aria-hidden="true" focusable="false">' +
        '<circle class="wax-disc" cx="24" cy="24" r="21" />' +
        '<circle class="wax-ring" cx="24" cy="24" r="16" />' +
        '<text x="24" y="30.5" text-anchor="middle">V</text>' +
        '<path class="wax-crack" d="M9 13 L19 21 L16 27 L25 31 L23 38 L31 44 M19 21 L27 17 L33 6 M25 31 L35 29 L44 34" />' +
        "</svg>"
      );
    }

    var STEPS = [
      ["photo", "Photo"],
      ["suggest", "Suggestion"],
      ["review", "Your call"],
      ["sealed", "Sealed"],
    ];

    function stepper() {
      var current = state.step === "identifying" ? "suggest" : state.step;
      var reached = true;
      return (
        '<ol class="steps" aria-label="Progress">' +
        STEPS.map(function (step, index) {
          var isCurrent = step[0] === current;
          var html =
            '<li data-reached="' +
            (reached ? "yes" : "no") +
            '"' +
            (isCurrent ? ' aria-current="step"' : "") +
            '><span class="step-n">' +
            ["i", "ii", "iii", "iv"][index] +
            ".</span> " +
            step[1] +
            "</li>";
          if (isCurrent) {
            reached = false;
          }
          return html;
        }).join("") +
        "</ol>"
      );
    }

    function plate() {
      if (state.image) {
        return (
          '<figure class="plate">' +
          '<img alt="Your photo of the sighting" src="' +
          state.image.preview +
          '" />' +
          (state.step === "sealed"
            ? '<div class="plate-seal">' +
              sealMark("intact", "press") +
              "</div>"
            : "") +
          '<figcaption class="mono">' +
          escapeHtml(state.image.name || "photo") +
          " · photo not anchored</figcaption>" +
          "</figure>"
        );
      }
      return (
        '<figure class="plate plate-empty">' +
        '<div class="plate-hint"><p class="script">Something worth noting?</p>' +
        "<p>Photograph it. The model suggests a name, you decide, and the record is sealed.</p></div>" +
        "</figure>"
      );
    }

    function confidenceText(value) {
      return typeof value === "number" ? value.toFixed(2) : "not given";
    }

    function reviewCard() {
      var s = state.suggestion;
      if (!s) {
        return "";
      }
      var label = s.sample ? "Sample suggestion" : "Model suggestion";
      var body =
        '<div class="specimen" role="group" aria-labelledby="specimen-name">' +
        '<p class="specimen-tag">' +
        label +
        (s.sample ? " · no model ran" : "") +
        "</p>" +
        '<p class="specimen-name" id="specimen-name">' +
        escapeHtml(s.species || "Nothing named") +
        "</p>" +
        '<dl class="specimen-meta">' +
        "<div><dt>Kind</dt><dd>" +
        escapeHtml(s.kind || "other") +
        "</dd></div>" +
        "<div><dt>Model confidence</dt><dd>" +
        confidenceText(s.confidence) +
        ' <span class="aside">the model’s own score, not measured accuracy</span></dd></div>' +
        '<div><dt>Model</dt><dd class="mono">' +
        escapeHtml(s.model_id || settings.model) +
        "</dd></div>" +
        "</dl>" +
        (s.detail
          ? '<p class="specimen-detail">“' + escapeHtml(s.detail) + "”</p>"
          : "") +
        "</div>";
      if (state.correcting) {
        return (
          body +
          '<form class="correct" id="correct-form">' +
          '<p class="hint">Write what you are sure you saw. The model’s suggestion is kept in the record beside your correction.</p>' +
          '<label>Name<input name="species" id="correct-species" autocomplete="off" required value="' +
          escapeHtml(s.species || "") +
          '" /></label>' +
          '<label>Kind<select name="kind">' +
          ["bird", "plant", "tree", "hazard", "water", "garden", "other"]
            .map(function (kind) {
              return (
                '<option value="' +
                kind +
                '"' +
                (kind === (s.kind || "other") ? " selected" : "") +
                ">" +
                kind +
                "</option>"
              );
            })
            .join("") +
          "</select></label>" +
          '<div class="row">' +
          '<button type="submit" class="primary" id="seal-correction">Seal my correction</button>' +
          '<button type="button" class="ghost" data-act="cancel-correct">Back</button>' +
          "</div></form>"
        );
      }
      return (
        body +
        '<p class="hint">Is that what you saw? Nothing is sealed until you decide.</p>' +
        '<div class="row">' +
        '<button type="button" class="primary seal-btn" id="confirm-seal" data-act="confirm">Confirm &amp; seal</button>' +
        '<button type="button" data-act="correct">Correct it</button>' +
        '<button type="button" class="ghost" data-act="discard">Discard</button>' +
        "</div>"
      );
    }

    function sealedNote() {
      var record = state.lastSealed ? journal.get(state.lastSealed) : null;
      var sync = record ? record.sync : { state: "pending" };
      if (sync.state === "anchored") {
        return (
          "<b>Sealed and anchored.</b> The ledger reports " +
          escapeHtml(sync.status) +
          ". The record is still in your field journal."
        );
      }
      if (sync.state === "refused") {
        return "<b>Sealed.</b> The queued copy was edited, so sync refused it. Your journal holds the sealed record.";
      }
      return "<b>Sealed.</b> Kept in your field journal, and waiting in the outbox until you sync.";
    }

    function actionArea() {
      var keyReady = !!state.privateKey;
      if (state.step === "identifying") {
        return (
          '<div class="working" role="status">' +
          '<span class="quill" aria-hidden="true"></span>' +
          "<p><b>" +
          escapeHtml(settings.model) +
          " is looking…</b> " +
          '<span class="mono" id="elapsed">0 s</span></p>' +
          '<p class="hint">A hosted model receives this photo. On a CPU this can take half a minute.</p>' +
          "</div>"
        );
      }
      if (state.step === "review") {
        return reviewCard();
      }
      if (state.step === "sealed") {
        return (
          '<div class="sealed-note" role="status">' +
          "<p>" +
          sealedNote() +
          "</p>" +
          '<div class="row"><button type="button" class="primary" id="next-sighting" data-act="next">Note another sighting</button></div>' +
          "</div>"
        );
      }
      var choose =
        '<label class="file' +
        (state.image ? "" : " primary") +
        '">' +
        "<span>" +
        (state.image ? "Choose a different photo" : "Take or choose a photo") +
        "</span>" +
        '<input type="file" accept="image/*" capture="environment" id="photo" />' +
        "</label>";
      if (!state.image) {
        return (
          '<div class="row">' +
          choose +
          "</div>" +
          '<p class="hint">No model running? <button type="button" class="linklike" data-act="sample"' +
          (keyReady ? "" : " disabled") +
          ">Try a labelled sample suggestion</button></p>"
        );
      }
      return (
        '<div class="row">' +
        '<button type="button" class="primary" id="ask-model" data-act="identify"' +
        (keyReady ? "" : " disabled") +
        ">Ask the model for a suggestion</button>" +
        choose +
        "</div>"
      );
    }

    function capturePanel() {
      return (
        '<section class="card capture-card" aria-labelledby="capture-h">' +
        '<h2 id="capture-h" class="visually-hidden">Note a sighting</h2>' +
        stepper() +
        plate() +
        '<div class="act">' +
        actionArea() +
        (state.error
          ? '<p class="action-error" role="alert">' +
            escapeHtml(state.error) +
            "</p>"
          : "") +
        "</div>" +
        '<details class="fine" data-open-key="privacy"' +
        (state.open.privacy ? " open" : "") +
        "><summary>What leaves this device</summary>" +
        '<ul class="help">' +
        "<li><b>To the model:</b> the photo, when you ask for a suggestion. A hosted model receives it; only a model on this device would keep it here.</li>" +
        "<li><b>To the ledger, on sync:</b> a hash of the record, the device signature, the time, a coarse area (rounded to about 1 km) and the species summary.</li>" +
        "<li><b>Never anchored:</b> the photo, your notes, the exact location.</li>" +
        "</ul></details>" +
        '<details class="fine" data-open-key="model"' +
        (state.open.model ? " open" : "") +
        "><summary>Model endpoint · " +
        escapeHtml(settings.model) +
        "</summary>" +
        '<form id="model-form" class="endpoints">' +
        '<label>Endpoint<input name="endpoint" value="' +
        escapeHtml(settings.endpoint) +
        '" /></label>' +
        '<label>Model<input name="model" value="' +
        escapeHtml(settings.model) +
        '" /></label>' +
        '<p class="hint">Any OpenAI-compatible endpoint (Ollama, llama.cpp, LM Studio), local or over a private tunnel.</p>' +
        "</form></details>" +
        "</section>"
      );
    }

    function outboxPanel() {
      var entries = queue.list();
      var verdict = state.verdict;
      var banner = "";
      if (verdict) {
        banner =
          '<p class="verdict" role="status" data-tone="' +
          (verdict.ok ? "verified" : "mismatch") +
          '">' +
          escapeHtml(verdictText(verdict)) +
          "</p>";
      }
      return (
        '<section class="card outbox" aria-labelledby="outbox-h">' +
        '<div class="card-head"><h2 id="outbox-h">Outbox</h2>' +
        '<span class="mono count" id="outbox-count">' +
        entries.length +
        " waiting</span></div>" +
        '<p class="hint">' +
        (entries.length
          ? "Sealed records wait here until there is signal. Sync checks the seal first and refuses to send anything that was edited."
          : "Nothing waiting. Synced sightings stay in your journal.") +
        "</p>" +
        banner +
        '<div class="row">' +
        '<button type="button" class="primary" id="sync" data-act="sync"' +
        (entries.length && !state.busy ? "" : " disabled") +
        ">" +
        (state.busy ? "Syncing…" : "Sync to the ledger") +
        "</button>" +
        '<button type="button" data-act="verify"' +
        (entries.length ? "" : " disabled") +
        ">Check the seal</button>" +
        "</div>" +
        (state.syncError
          ? '<p class="action-error" role="alert">' +
            escapeHtml(state.syncError) +
            "</p>"
          : "") +
        '<details class="fine demo-tools" data-open-key="demo"' +
        (state.open.demo ? " open" : "") +
        "><summary>Demo: tamper with a queued copy</summary>" +
        '<p class="hint">For the demo only. This edits the copy waiting in the outbox, as an attacker or a careless script might. Your journal keeps what you sealed.</p>' +
        '<div class="row"><button type="button" class="danger" id="tamper" data-act="tamper"' +
        (entries.length ? "" : " disabled") +
        ">Edit the queued copy</button></div>" +
        "</details>" +
        "</section>"
      );
    }

    function proofList(row) {
      var entry = row.entry;
      var sync = row.sync || {};
      var items = [
        ["Model", escapeHtml(entry.model_id || "—")],
        ["Observed", escapeHtml(entry.observed_at || "—")],
        [
          "Coarse area",
          entry.location
            ? escapeHtml(entry.location.lat + ", " + entry.location.lon)
            : "not recorded",
        ],
        [
          "Commitment (hash)",
          '<span class="mono wrap">' + escapeHtml(entry.hash) + "</span>",
        ],
        [
          "Previous",
          '<span class="mono wrap">' +
            escapeHtml(entry.prev || "— first in chain") +
            "</span>",
        ],
        [
          "Device signature",
          '<span class="mono wrap">' + escapeHtml(entry.signature) + "</span>",
        ],
        [
          "Device key",
          '<span class="mono wrap">' +
            escapeHtml(state.publicKeyText || "—") +
            "</span>",
        ],
      ];
      if (sync.state === "anchored") {
        items.push([
          "Ledger status",
          escapeHtml(sync.status) + " — " + escapeHtml(statusNote(sync.status)),
        ]);
        items.push([
          "Block",
          '<span class="mono wrap">' +
            escapeHtml(sync.block_id || "—") +
            "</span>",
        ]);
        items.push([
          "Milestone",
          '<span class="mono">' +
            escapeHtml(
              sync.milestone_index === null ||
                sync.milestone_index === undefined
                ? "—"
                : sync.milestone_index,
            ) +
            "</span>",
        ]);
      }
      return (
        '<dl class="proof">' +
        items
          .map(function (item) {
            return (
              "<div><dt>" + item[0] + "</dt><dd>" + item[1] + "</dd></div>"
            );
          })
          .join("") +
        "</dl>"
      );
    }

    function reviewLine(entry) {
      var review = entry.payload && entry.payload.review;
      if (!review) {
        return "";
      }
      if (review.decision === "corrected") {
        return (
          '<p class="review-line">You corrected the model’s “' +
          escapeHtml(review.suggested_species || "nothing") +
          "”</p>"
        );
      }
      return '<p class="review-line">You confirmed the model’s suggestion</p>';
    }

    function statusChip(row) {
      var text = STATE_LABEL[row.state];
      if (row.state === "anchored") {
        text = "Anchored · " + row.sync.status;
      }
      if (row.state === "cracked" && row.refused) {
        text = "Seal cracked · sync refused";
      }
      return (
        '<span class="chip" data-state="' +
        row.state +
        '" data-status="' +
        escapeHtml(row.sync.status || "") +
        '">' +
        escapeHtml(text) +
        "</span>"
      );
    }

    function similarBlock(row) {
      var result = state.similar[row.hash];
      var body = "";
      if (result && result.error) {
        body = '<p class="hint">' + escapeHtml(result.error) + "</p>";
      } else if (result && result.hits) {
        body = result.hits.length
          ? '<ul class="similar">' +
            result.hits
              .map(function (hit) {
                return (
                  "<li><b>" +
                  escapeHtml(hit.label || "unlabelled") +
                  '</b> <span class="mono">' +
                  escapeHtml(shortHash(hit.commitment, 8)) +
                  "</span></li>"
                );
              })
              .join("") +
            "</ul>"
          : '<p class="hint">No similar anchored sightings yet.</p>';
      }
      return (
        '<div class="commons">' +
        '<button type="button" class="linklike" data-act="similar" data-hash="' +
        row.hash +
        '">Find similar anchored sightings</button>' +
        ' <span class="aside">optional · needs a configured Atlas commons</span>' +
        body +
        "</div>"
      );
    }

    function journalRow(row) {
      var entry = row.entry;
      var summary = summaryOf(entry);
      var cracked = row.state === "cracked";
      var animate =
        (state.justSealed === row.hash ? " press" : "") +
        (state.justCracked === row.hash ? " cracking" : "");
      return (
        '<li class="sighting" data-state="' +
        row.state +
        '" id="s-' +
        row.hash.slice(0, 12) +
        '">' +
        '<div class="sighting-main">' +
        (row.thumb
          ? '<img class="thumb" alt="" src="' + row.thumb + '" />'
          : '<div class="thumb thumb-none" aria-hidden="true"></div>') +
        '<div class="sighting-text">' +
        '<h3 class="sighting-name">' +
        escapeHtml(entryTitle(entry)) +
        "</h3>" +
        '<p class="sighting-meta">' +
        escapeHtml(summary.kind) +
        " · " +
        escapeHtml((entry.observed_at || "").replace("T", " ").slice(0, 16)) +
        (entry.model_id === "sample" ? " · sample" : "") +
        "</p>" +
        reviewLine(entry) +
        statusChip(row) +
        "</div>" +
        sealMark(
          cracked
            ? "cracked"
            : row.state === "anchored"
              ? "verified"
              : "intact",
          animate,
        ) +
        "</div>" +
        (cracked && row.queuedCopy
          ? '<p class="crack-note">The queued copy now says “' +
            escapeHtml(
              row.queuedCopy.payload && row.queuedCopy.payload.species,
            ) +
            "”. Its hash no longer matches the seal, so sync will not send it. Your journal still holds what you sealed.</p>" +
            '<div class="row"><button type="button" data-act="restore" data-hash="' +
            row.hash +
            '">Put the sealed copy back</button></div>'
          : "") +
        '<details class="proof-wrap" data-open-key="p-' +
        row.hash +
        '"' +
        (state.open["p-" + row.hash] ? " open" : "") +
        "><summary>Proof</summary>" +
        proofList(row) +
        (row.state === "anchored" ? similarBlock(row) : "") +
        "</details>" +
        "</li>"
      );
    }

    function journalPanel() {
      var rows = journalView(journal.list(), queue.list(), state.verdict);
      return (
        '<section class="card journal" aria-labelledby="journal-h">' +
        '<div class="card-head"><h2 id="journal-h">Field journal</h2>' +
        '<span class="mono count" id="journal-count">' +
        rows.length +
        " sealed</span></div>" +
        (rows.length
          ? '<ol class="sightings">' + rows.map(journalRow).join("") + "</ol>"
          : '<p class="empty">Your sealed sightings will be listed here, and stay here after they sync.</p>') +
        '<p class="mono device">device key ' +
        escapeHtml(shortHash(state.publicKeyText, 12)) +
        "</p>" +
        "</section>"
      );
    }

    function render(focusId) {
      var active = document.activeElement && document.activeElement.id;
      el.innerHTML =
        '<div class="field-grid">' +
        '<div class="col-main">' +
        capturePanel() +
        "</div>" +
        '<div class="col-side">' +
        outboxPanel() +
        journalPanel() +
        "</div>" +
        "</div>";
      wire();
      var target = document.getElementById(focusId || active || "");
      if (target && typeof target.focus === "function") {
        target.focus({ preventScroll: !focusId });
      }
      state.justSealed = null;
      state.justCracked = null;
    }

    /* -------------------------------------------------------------- wiring */

    function readFile(file) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onload = function () {
          var text = String(reader.result || "");
          var comma = text.indexOf(",");
          resolve({
            name: file.name,
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

    /* A small local thumbnail for the journal. Never hashed, never sent. */
    function thumbnail(preview) {
      return new Promise(function (resolve) {
        var img = new Image();
        img.onload = function () {
          try {
            var scale = Math.min(1, 160 / Math.max(img.width, img.height));
            var canvas = document.createElement("canvas");
            canvas.width = Math.round(img.width * scale);
            canvas.height = Math.round(img.height * scale);
            canvas
              .getContext("2d")
              .drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.72));
          } catch (err) {
            resolve(null);
          }
        };
        img.onerror = function () {
          resolve(null);
        };
        img.src = preview;
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
            state.error = null;
            state.step = "photo";
          } catch (err) {
            state.error = err.message;
          }
          render("ask-model");
        });
      }
      var form = el.querySelector("#model-form");
      if (form) {
        form.addEventListener("change", function () {
          settings.endpoint = form.endpoint.value.trim() || settings.endpoint;
          settings.model = form.model.value.trim() || settings.model;
        });
      }
      var correct = el.querySelector("#correct-form");
      if (correct) {
        correct.addEventListener("submit", function (event) {
          event.preventDefault();
          sealDecision({
            action: "correct",
            species: correct.species.value,
            kind: correct.kind.value,
          });
        });
      }
      el.querySelectorAll("details[data-open-key]").forEach(function (node) {
        node.addEventListener("toggle", function () {
          state.open[node.getAttribute("data-open-key")] = node.open;
        });
      });
      el.querySelectorAll("[data-act]").forEach(function (node) {
        node.addEventListener("click", function () {
          var act = node.getAttribute("data-act");
          var hash = node.getAttribute("data-hash");
          var actions = {
            identify: identify,
            sample: function () {
              suggest(sampleIdentification());
            },
            confirm: function () {
              sealDecision({ action: "confirm" });
            },
            correct: function () {
              state.correcting = true;
              render("correct-species");
            },
            "cancel-correct": function () {
              state.correcting = false;
              render("confirm-seal");
            },
            discard: function () {
              state.suggestion = null;
              state.correcting = false;
              state.step = "photo";
              render(state.image ? "ask-model" : "photo");
            },
            next: function () {
              state.image = null;
              state.step = "photo";
              render("photo");
            },
            verify: verify,
            sync: sync,
            tamper: tamper,
            restore: function () {
              restore(hash);
            },
            similar: function () {
              similar(hash);
            },
          };
          if (actions[act]) {
            actions[act]();
          }
        });
      });
    }

    /* ------------------------------------------------------------ actions */

    function stopTicker() {
      if (ticker) {
        root.clearInterval(ticker);
        ticker = null;
      }
    }

    async function identify() {
      if (!state.image) {
        return;
      }
      state.step = "identifying";
      state.error = null;
      state.identifyStarted = Date.now();
      render();
      stopTicker();
      ticker = root.setInterval(function () {
        var node = document.getElementById("elapsed");
        if (node) {
          node.textContent =
            Math.round((Date.now() - state.identifyStarted) / 1000) + " s";
        }
      }, 1000);
      var id;
      try {
        id = await root.VickreyInfer.identify({
          imageBase64: state.image.base64,
          endpoint: settings.endpoint,
          model: settings.model,
        });
      } catch (err) {
        stopTicker();
        state.step = "photo";
        state.error =
          "No model answered at " +
          settings.endpoint +
          ". Start one, or try the labelled sample suggestion. (" +
          err.message +
          ")";
        render("ask-model");
        return;
      }
      stopTicker();
      suggest(id);
    }

    function suggest(id) {
      state.suggestion = id;
      state.correcting = false;
      state.error = null;
      state.step = "review";
      render("confirm-seal");
    }

    async function sealDecision(decision) {
      if (!state.privateKey) {
        state.error =
          "The device key is not ready yet — sealing needs it. Wait a moment, or reload the page.";
        render();
        return;
      }
      var reviewed;
      try {
        reviewed = reviewedIdentification(state.suggestion, decision);
      } catch (err) {
        state.error = err.message;
        render();
        return;
      }
      try {
        var entry = await logbook.seal(reviewed, {
          privateKey: state.privateKey,
          model: settings.model,
          observedAt: new Date().toISOString(),
          location: settings.area
            ? root.VickreyTrust.coarseLocation(settings.area, 2)
            : null,
        });
        var thumb = state.image ? await thumbnail(state.image.preview) : null;
        journal.record(entry, { thumb: thumb });
        state.justSealed = entry.hash;
        state.lastSealed = entry.hash;
        state.verdict = null;
        state.suggestion = null;
        state.correcting = false;
        state.error = null;
        state.step = "sealed";
        toast("Sealed " + entryTitle(entry));
      } catch (err) {
        state.error = err.message;
      }
      render("next-sighting");
    }

    async function verify() {
      state.verdict = await root.VickreyTrust.verifyChain(
        queue.list(),
        state.publicKey,
      );
      if (!state.verdict.ok) {
        var broken = queue.list()[state.verdict.brokenAt];
        state.justCracked = broken ? broken.hash : null;
      }
      render();
    }

    function tamper() {
      var entries = queue.list();
      if (!entries.length) {
        return;
      }
      var last = entries.length - 1;
      var mutated = applyTamper(entries, last, "Misidentified magpie");
      queue.replace(entries[last].hash, mutated[last]);
      state.verdict = null;
      state.syncError = null;
      state.justCracked = entries[last].hash;
      toast("Edited the queued copy — the seal no longer matches");
      render();
    }

    function restore(hash) {
      var record = journal.get(hash);
      if (!record) {
        return;
      }
      queue.replace(hash, record.entry);
      journal.markPending(hash);
      state.verdict = null;
      state.syncError = null;
      state.justSealed = hash;
      toast("Sealed copy restored — the seal re-forms");
      render("sync");
    }

    async function sync() {
      state.busy = true;
      state.syncError = null;
      render();
      var rows = {};
      var drained = await drainVerified(
        queue,
        state.publicKey,
        root.VickreyTrust,
        async function (entry) {
          rows[entry.hash] = await postAnchor(entry);
        },
      );
      state.busy = false;
      if (drained.empty) {
        render();
        return;
      }
      if (drained.verdict) {
        state.verdict = drained.verdict;
      }
      settleSync(journal, drained, rows);
      var sent = drained.sent.length;
      if (drained.error) {
        state.syncError =
          (sent ? "Sync stopped after " + sent + ": " : "Sync refused: ") +
          drained.error.message +
          ". Nothing unsent left the device.";
      } else {
        toast("Anchored " + sent + " sighting" + (sent === 1 ? "" : "s"));
      }
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
      return row;
    }

    async function similar(hash) {
      var record = journal.get(hash);
      if (!record) {
        return;
      }
      var query = entryTitle(record.entry);
      try {
        var url =
          trimUrl(settings.commonsUrl) +
          "/observations/similar?limit=6&q=" +
          encodeURIComponent(query);
        var response = await root.fetch(url);
        var body = await response.json();
        if (!response.ok) {
          throw new Error(body.detail || "ledger returned " + response.status);
        }
        state.similar[hash] = { hits: body.observations || [] };
      } catch (err) {
        state.similar[hash] = {
          error: "Commons search unavailable: " + String(err.message || err),
        };
      }
      render();
    }

    /* ---------------------------------------------------------------- boot */

    ensureKey()
      .catch(function (err) {
        state.error =
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
    JOURNAL_KEY: JOURNAL_KEY,
    KEY_KEY: KEY_KEY,
    anchorMessage: anchorMessage,
    applyTamper: applyTamper,
    drainVerified: drainVerified,
    entryTitle: entryTitle,
    journalView: journalView,
    parseArea: parseArea,
    reviewedIdentification: reviewedIdentification,
    settleSync: settleSync,
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
