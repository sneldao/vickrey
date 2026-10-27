/* Vickrey field logbook.
 *
 * Reads the Day 2 ledger and shows whether the application row still matches
 * the Hornet block. It does not submit blocks. Re-check and tamper call the
 * existing ledger routes.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyExplorer = api;
    var start = function () {
      api.mount(document.getElementById("app"));
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var FILTERS = [
    { id: "ALL", label: "All" },
    { id: "VERIFIED", label: "Verified" },
    { id: "PENDING", label: "Pending" },
    { id: "PAYLOAD_MISMATCH", label: "Mismatch" },
    { id: "NOT_SOLID", label: "Not solid" },
  ];

  var CHECK_WORD = {
    pass: "Pass",
    fail: "Fail",
    wait: "Waiting",
    unknown: "Unknown",
    hidden: "Hidden",
    /* On the chain, in the open — the honest word for a transparent anchor's
     * own transaction, which is not "hidden" and not a failure either. */
    exposed: "Exposed",
  };

  function apiUrl(base, path) {
    return String(base || "").replace(/\/+$/, "") + path;
  }

  function httpOrigin(value) {
    if (value == null || String(value).trim() === "") {
      return "";
    }
    var url;
    try {
      url = new URL(String(value).trim());
    } catch (error) {
      return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.toString().replace(/\/+$/, "");
  }

  function dashboardBlockUrl(dashboardUrl, blockId) {
    var origin = httpOrigin(dashboardUrl);
    if (!origin) {
      return "";
    }
    return origin + "/explorer/block/" + encodeURIComponent(blockId);
  }

  function hornetBlockUrl(hornetUrl, blockId) {
    var origin = httpOrigin(hornetUrl);
    if (!origin) {
      return "";
    }
    return origin + "/api/core/v2/blocks/" + encodeURIComponent(blockId);
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function stable(value) {
    if (Array.isArray(value)) {
      return value.map(stable);
    }
    if (isPlainObject(value)) {
      var out = {};
      Object.keys(value)
        .sort()
        .forEach(function (key) {
          out[key] = stable(value[key]);
        });
      return out;
    }
    return value;
  }

  function canonical(value) {
    return JSON.stringify(stable(value));
  }

  function payloadsDiffer(appPayload, ledgerPayload) {
    if (ledgerPayload === null || ledgerPayload === undefined) {
      return false;
    }
    try {
      return canonical(appPayload) !== canonical(ledgerPayload);
    } catch (error) {
      return true;
    }
  }

  function changedKeys(appPayload, ledgerPayload) {
    if (!isPlainObject(appPayload) || !isPlainObject(ledgerPayload)) {
      return [];
    }
    var keys = Object.keys(appPayload).concat(Object.keys(ledgerPayload));
    var seen = {};
    return keys
      .filter(function (key) {
        if (seen[key]) {
          return false;
        }
        seen[key] = true;
        return canonical(appPayload[key]) !== canonical(ledgerPayload[key]);
      })
      .sort();
  }

  function payloadKind(value) {
    return isPlainObject(value) ? value.kind : undefined;
  }

  function isHighlighted(message) {
    return highlightLabel(message) !== "";
  }

  function highlightLabel(message) {
    if (!message) {
      return "";
    }
    var kind =
      payloadKind(message.payload_json) ||
      payloadKind(message.ledger_payload_json);
    if (kind === "alarm") {
      return "alarm";
    }
    var tag = message.tag ? String(message.tag) : "";
    if (tag.indexOf("incident.") === 0) {
      return "incident";
    }
    return "";
  }

  function incidentTitle(message) {
    if (message && message.zanchor) {
      if (message.shielded === false) {
        return "Anchor (transparent)";
      }
      return message.shielded === true ? "Shielded anchor" : "Anchored receipt";
    }
    var payload = isPlainObject(message && message.payload_json)
      ? message.payload_json
      : {};
    var detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) {
      var text = detail.trim();
      return text.charAt(0).toUpperCase() + text.slice(1);
    }
    if (message && message.tag) {
      return String(message.tag).replace(/[._-]+/g, " ");
    }
    return "Observation";
  }

  function valueWithUnit(message, value) {
    var unit =
      typeof value === "number" && isPlainObject(message.payload_json)
        ? message.payload_json.unit
        : undefined;
    var rendered = formatCell(value);
    return typeof unit === "string" && unit ? rendered + " " + unit : rendered;
  }

  function verdictLine(message) {
    var keys = changedKeys(
      message.payload_json,
      message.ledger_payload_json,
    ).filter(function (key) {
      var app = message.payload_json[key];
      var anchor = message.ledger_payload_json[key];
      return app !== undefined || anchor !== undefined;
    });
    var key = null;
    var i;
    for (i = 0; i < keys.length; i++) {
      if (
        typeof message.payload_json[keys[i]] === "number" &&
        typeof message.ledger_payload_json[keys[i]] === "number"
      ) {
        key = keys[i];
        break;
      }
    }
    if (!key) {
      for (i = 0; i < keys.length; i++) {
        if (
          typeof message.payload_json[keys[i]] === "number" ||
          typeof message.ledger_payload_json[keys[i]] === "number"
        ) {
          key = keys[i];
          break;
        }
      }
    }
    if (!key && keys.length) {
      key = keys[0];
    }
    if (!key) {
      return "";
    }
    return (
      "Your app says " +
      valueWithUnit(message, message.payload_json[key]) +
      " — the network recorded " +
      valueWithUnit(message, message.ledger_payload_json[key]) +
      "."
    );
  }

  function relativeTime(iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    var seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) {
      return "just now";
    }
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
      return minutes + "m ago";
    }
    var hours = Math.floor(minutes / 60);
    if (hours < 24) {
      return hours + "h ago";
    }
    return Math.floor(hours / 24) + "d ago";
  }

  function tamperBody(message) {
    var payload = isPlainObject(message.payload_json)
      ? message.payload_json
      : {};
    var anchored = isPlainObject(message.ledger_payload_json)
      ? message.ledger_payload_json
      : {};
    // Scale the anchored value so the edit is plausible in shape but plainly
    // wrong in number — and re-tampering stays idempotent.
    function scaled(key) {
      var base =
        typeof anchored[key] === "number" ? anchored[key] : payload[key];
      return Math.round(base * 4 * 10) / 10;
    }
    if (typeof payload.temperature === "number") {
      return { temperature: scaled("temperature") };
    }
    var keys = Object.keys(payload);
    for (var i = 0; i < keys.length; i++) {
      if (typeof payload[keys[i]] === "number") {
        var patch = {};
        keys.forEach(function (other) {
          patch[other] = payload[other];
        });
        patch[keys[i]] = scaled(keys[i]);
        return { payload: patch };
      }
    }
    return {};
  }

  function statusLabel(status) {
    switch (status) {
      case "VERIFIED":
        return "VERIFIED";
      case "PENDING":
        return "PENDING";
      case "PAYLOAD_MISMATCH":
        return "PAYLOAD MISMATCH";
      case "NOT_SOLID":
        return "NOT SOLID";
      default:
        return status || "UNKNOWN";
    }
  }

  function normalizeFilter(value) {
    if (value == null || String(value).trim() === "") {
      return "ALL";
    }
    var text = String(value)
      .trim()
      .toUpperCase()
      .replace(/[\s-]+/g, "_");
    if (text === "ALL") {
      return "ALL";
    }
    if (text === "MISMATCH" || text === "PAYLOAD_MISMATCH") {
      return "PAYLOAD_MISMATCH";
    }
    if (text === "NOT_SOLID" || text === "NOTSOLID") {
      return "NOT_SOLID";
    }
    if (text === "VERIFIED" || text === "PENDING") {
      return text;
    }
    return "ALL";
  }

  function payloadCheck(message) {
    var ledger = message.ledger_payload_json;
    var known = ledger !== null && ledger !== undefined;
    if (known) {
      if (payloadsDiffer(message.payload_json, ledger)) {
        return {
          state: "fail",
          label: "Payload differs",
          detail: "Application JSON is not the Hornet tagged data.",
        };
      }
      return {
        state: "pass",
        label: "Payload matches",
        detail: "Semantic JSON, key order ignored.",
      };
    }
    if (message.content_match === true) {
      return { state: "pass", label: "Payload matches", detail: "" };
    }
    if (message.content_match === false) {
      return {
        state: "fail",
        label: "Payload differs",
        detail: "Hornet payload was not decoded.",
      };
    }
    return { state: "unknown", label: "Payload not checked", detail: "" };
  }

  function solidCheck(message) {
    if (message.solid === true) {
      return {
        state: "pass",
        label: "Solid",
        detail: "Hornet metadata isSolid is true.",
      };
    }
    if (message.solid === false) {
      return {
        state: "fail",
        label: "Not solid",
        detail: "Hornet metadata isSolid is false.",
      };
    }
    return { state: "unknown", label: "Solid not checked", detail: "" };
  }

  function milestoneCheck(message) {
    if (typeof message.milestone_index === "number") {
      return {
        state: "pass",
        label: "Milestone " + message.milestone_index,
        detail: "referencedByMilestoneIndex",
      };
    }
    if (message.solid === null || message.solid === undefined) {
      return { state: "unknown", label: "No milestone yet", detail: "" };
    }
    return {
      state: "wait",
      label: "No milestone yet",
      detail: "The coordinator has not referenced this block.",
    };
  }

  function tagCheck(message) {
    if (typeof message.ledger_tag === "string") {
      if (message.ledger_tag === message.tag) {
        return {
          state: "pass",
          label: "Tag matches",
          detail: message.tag || "(empty)",
        };
      }
      return {
        state: "fail",
        label: "Tag differs",
        detail:
          "Stored " +
          (message.tag || "(empty)") +
          " · Hornet " +
          message.ledger_tag,
      };
    }
    if (message.content_match === true) {
      return { state: "pass", label: "Tag matches", detail: message.tag || "" };
    }
    if (message.content_match === false) {
      return {
        state: "fail",
        label: "Tag differs",
        detail: "Hornet tag was not decoded.",
      };
    }
    return {
      state: "unknown",
      label: "Tag not checked",
      detail: message.tag || "",
    };
  }

  function checklist(message) {
    return {
      payload: payloadCheck(message),
      solid: solidCheck(message),
      milestone: milestoneCheck(message),
      tag: tagCheck(message),
    };
  }

  /* ------------------------------------------------------------- shielded */

  /* A shielded anchor's verdict. The receipt says what the verifier holds;
   * the chain check says what anyone can confirm. VERIFIED needs both — a
   * receipt nobody has checked against the chain is only PENDING, and a
   * receipt the chain contradicts is a MISMATCH. */
  function shieldedState(receipt, chain) {
    if (!receipt || !receipt.txid) {
      return "PENDING";
    }
    if (chain && chain.exists === false) {
      return "PAYLOAD_MISMATCH";
    }
    if (receipt.status === "confirmed" && chain && chain.exists === true) {
      return "VERIFIED";
    }
    return "PENDING";
  }

  /* A shielded receipt shaped like a timeline row (docs/ZANCHOR_API.md). It
   * carries the receipt and nothing else — there is no payload to leak,
   * because the anchor never had one. */
  function shieldedMessage(receipt, chain) {
    receipt = receipt || {};
    return {
      /* `zanchor` says where this row came from; `shielded` is the service's
       * own answer about the transaction (docs/ZANCHOR_API.md). The row is
       * anchored either way — the stamp is what must not lie. */
      zanchor: true,
      shielded:
        receipt.shielded === true
          ? true
          : receipt.shielded === false
            ? false
            : null,
      receipt: receipt,
      chain: chain || null,
      block_id: receipt.txid || receipt.receipt_id || "",
      status: shieldedState(receipt, chain),
      inserted_at: receipt.anchored_at || "",
      flow_id: "shielded",
      tag: null,
      payload_json: null,
      ledger_payload_json: null,
    };
  }

  /* What the public chain reveals about an anchor. For a shielded transaction
   * every row is empty by construction. For the transparent fallback the
   * transaction itself is on the chain, so those rows say "Exposed" and name
   * exactly what shows — the difference between "nothing to check" and "a
   * constant-amount transfer that does not say what it anchors". */
  function revealRows(shielded) {
    function hidden(name, detail) {
      return {
        name: name,
        state: "hidden",
        label: "Not revealed",
        detail: detail,
      };
    }
    var transparent = shielded === false;
    var rows = [
      hidden("Species", "The transaction carries no summary of what was seen."),
      hidden(
        "Coarse area",
        "No location of any resolution rides with the anchor.",
      ),
      hidden("Observer", "No key or identity is linked to the transaction."),
      transparent
        ? {
            name: "Observation time",
            state: "exposed",
            label: "Block time only",
            detail:
              "The block's timestamp is public; the capture time is not. The anchor waits at least 30 minutes after capture, then up to 20 minutes more.",
          }
        : hidden(
            "Observation time",
            "Only the block's own timestamp exists, far enough from the capture to be uncorrelatable.",
          ),
      hidden("Purpose", "Nothing marks this transaction as an anchor."),
      transparent
        ? {
            name: "Amount",
            state: "exposed",
            label: "Constant",
            detail:
              "Every anchor moves the same amount, so the visible amount cannot fingerprint an event.",
          }
        : {
            name: "Amount",
            state: "hidden",
            label: "Constant",
            detail:
              "Every anchor moves the same amount, so amounts cannot fingerprint events.",
          },
    ];
    if (transparent) {
      rows.push({
        name: "Transaction",
        state: "exposed",
        label: "Public",
        detail:
          "A transparent transaction shows its amount, its addresses and its block. None of them describe the observation.",
      });
    }
    return rows;
  }

  /* The verifier-held binding: commitment <-> txid <-> height. */
  function receiptRows(receipt, chain) {
    receipt = receipt || {};
    var height =
      chain && chain.height != null
        ? chain.height
        : receipt.height != null
          ? receipt.height
          : "—";
    return [
      { label: "Commitment", value: receipt.commitment || "—", mono: true },
      { label: "Transaction", value: receipt.txid || "—", mono: true },
      { label: "Height", value: height, mono: true },
      { label: "Receipt", value: receipt.receipt_id || "—", mono: true },
    ];
  }

  function blockExplorerUrl(txid) {
    if (!txid) {
      return "";
    }
    return (
      "https://blockchair.com/zcash/transaction/" + encodeURIComponent(txid)
    );
  }

  /* The stamp is a claim, so it is derived from the service's answer and not
   * from the routing: SHIELDED only when the transaction really is shielded,
   * TRANSPARENT when the service fell back, plain status when it did not say. */
  function stampText(message) {
    var verdict = statusLabel(message && message.status);
    if (!message || !message.zanchor) {
      return verdict;
    }
    if (message.shielded === true) {
      return "SHIELDED · " + verdict;
    }
    if (message.shielded === false) {
      return "TRANSPARENT · " + verdict;
    }
    return verdict;
  }

  function pitchLine(message) {
    if (!message) {
      return "";
    }
    if (message.status === "VERIFIED") {
      return "This observation agrees. The application copy matches the Hornet block, the block is solid, and a milestone references it.";
    }
    if (
      message.status === "PAYLOAD_MISMATCH" &&
      payloadsDiffer(message.payload_json, message.ledger_payload_json)
    ) {
      return "PAYLOAD MISMATCH. The application copy changed. The Hornet block still holds the original tagged data.";
    }
    if (message.status === "PAYLOAD_MISMATCH") {
      return "The content check failed. The checklist shows whether the tag, the payload, or both disagree.";
    }
    if (message.status === "NOT_SOLID") {
      return "The tagged data matches, and Hornet says this block is not solid.";
    }
    if (message.status === "PENDING") {
      return "The row is stored. The solid check, the content check, or the milestone reference has not finished.";
    }
    return message.detail || "";
  }

  function groupByFlow(messages) {
    var sorted = messages.slice().sort(function (a, b) {
      var byTime = String(a.inserted_at || "").localeCompare(
        String(b.inserted_at || ""),
      );
      if (byTime !== 0) {
        return byTime;
      }
      return String(a.block_id).localeCompare(String(b.block_id));
    });
    var groups = new Map();
    sorted.forEach(function (message) {
      var key = message.flow_id ? String(message.flow_id) : "";
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(message);
    });
    var keys = Array.from(groups.keys());
    keys.sort(function (a, b) {
      if (a === "") {
        return 1;
      }
      if (b === "") {
        return -1;
      }
      var aTime = groups.get(a)[0].inserted_at || "";
      var bTime = groups.get(b)[0].inserted_at || "";
      var byTime = String(aTime).localeCompare(String(bTime));
      if (byTime !== 0) {
        return byTime;
      }
      return a.localeCompare(b);
    });
    return keys.map(function (key) {
      return { flowId: key || null, messages: groups.get(key) };
    });
  }

  function applyFilter(messages, filter, query) {
    var needle = String(query || "")
      .trim()
      .toLowerCase()
      .replace(/^0x/, "");
    return messages.filter(function (message) {
      if (filter !== "ALL" && message.status !== filter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return String(message.block_id || "")
        .toLowerCase()
        .replace(/^0x/, "")
        .includes(needle);
    });
  }

  function formatClock(iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    var hh = String(date.getUTCHours()).padStart(2, "0");
    var mm = String(date.getUTCMinutes()).padStart(2, "0");
    var ss = String(date.getUTCSeconds()).padStart(2, "0");
    return hh + ":" + mm + ":" + ss;
  }

  function formatTime(iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      return String(iso || "");
    }
    var months = [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
    ];
    var dd = String(date.getUTCDate()).padStart(2, "0");
    return (
      dd + " " + months[date.getUTCMonth()] + " " + formatClock(iso) + " UTC"
    );
  }

  function shortId(blockId) {
    var raw = String(blockId || "");
    var norm = raw.replace(/^0x/i, "");
    if (norm.length <= 14) {
      return raw;
    }
    return norm.slice(0, 6) + "…" + norm.slice(-4);
  }

  function pretty(value) {
    if (typeof value === "string") {
      return value;
    }
    if (value === undefined) {
      return "";
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }

  function formatCell(value) {
    if (value === undefined) {
      return "—";
    }
    if (typeof value === "string") {
      return value;
    }
    try {
      return JSON.stringify(value);
    } catch (error) {
      return String(value);
    }
  }

  function blockIdFromHash() {
    if (typeof window === "undefined") {
      return "";
    }
    var raw = window.location.hash.replace(/^#/, "");
    if (!raw) {
      return "";
    }
    try {
      return decodeURIComponent(raw);
    } catch (error) {
      return raw;
    }
  }

  function chooseInitial(messages) {
    var hash = blockIdFromHash();
    if (
      hash &&
      messages.some(function (message) {
        return message.block_id === hash;
      })
    ) {
      return hash;
    }
    var alarm = messages.find(function (message) {
      return message.status === "VERIFIED" && isHighlighted(message);
    });
    if (alarm) {
      return alarm.block_id;
    }
    return messages.length ? messages[0].block_id : null;
  }

  function readConfig() {
    var cfg = (typeof window !== "undefined" && window.VICKREY_CONFIG) || {};
    var params =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search)
        : new URLSearchParams();
    function stored(key) {
      try {
        return window.localStorage.getItem(key);
      } catch (error) {
        return null;
      }
    }
    function pick(param, storageKey, fallback) {
      var fromQuery = params.get(param);
      if (fromQuery && fromQuery.trim()) {
        return fromQuery.trim();
      }
      var fromStore = stored(storageKey);
      if (fromStore && fromStore.trim()) {
        return fromStore.trim();
      }
      return (fallback || "").trim();
    }
    return {
      ledgerUrl: pick(
        "ledger",
        "vickrey.ledgerUrl",
        cfg.ledgerUrl || "http://localhost:8088",
      ),
      dashboardUrl: pick(
        "dashboard",
        "vickrey.dashboardUrl",
        cfg.dashboardUrl || "http://localhost:31011",
      ),
      hornetUrl: pick(
        "hornet",
        "vickrey.hornetUrl",
        cfg.hornetUrl || "http://localhost:14265",
      ),
      zanchorUrl: pick(
        "zanchor",
        "vickrey.zanchorUrl",
        cfg.zanchorUrl || "http://localhost:8092",
      ),
      /* Shielded receipts are handed to this page one id at a time
       * (?receipt=…&receipt=…): the contract has no list endpoint on purpose. */
      receipts: params
        .getAll("receipt")
        .map(function (value) {
          return String(value || "").trim();
        })
        .filter(Boolean),
      defaults: {
        ledgerUrl: cfg.ledgerUrl || "http://localhost:8088",
        dashboardUrl: cfg.dashboardUrl || "http://localhost:31011",
        hornetUrl: cfg.hornetUrl || "http://localhost:14265",
        zanchorUrl: cfg.zanchorUrl || "http://localhost:8092",
      },
    };
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value == null || value === false) {
          return;
        }
        if (key === "class") {
          node.className = value;
        } else if (key === "text") {
          node.textContent = value;
        } else if (key === "disabled") {
          node.disabled = true;
        } else if (key.indexOf("on") === 0 && typeof value === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else {
          node.setAttribute(key, value === true ? "" : String(value));
        }
      });
    }
    (children || []).forEach(function (child) {
      if (child == null) {
        return;
      }
      node.append(child);
    });
    return node;
  }

  function mount(root) {
    if (!root || typeof document === "undefined") {
      return;
    }
    var config = readConfig();
    var params = new URLSearchParams(window.location.search);
    var state = {
      ledgerUrl: config.ledgerUrl,
      dashboardUrl: config.dashboardUrl,
      hornetUrl: config.hornetUrl,
      zanchorUrl: config.zanchorUrl,
      defaults: config.defaults,
      receiptIds: config.receipts,
      shielded: [],
      shieldedChain: {},
      shieldedErrors: {},
      filter: normalizeFilter(params.get("status")),
      blockQuery: "",
      messages: [],
      total: 0,
      selectedId: null,
      health: null,
      error: null,
      notice: "",
      actionError: "",
      busy: false,
      loaded: false,
      auto: true,
      rendered: "",
      lastChecked: 0,
      justTampered: null,
      justReverified: null,
      walk: { tampered: false, sawMismatch: false, reverified: false },
      walkDismissed: storedFlag("vickrey.walk.dismissed"),
    };

    /* Public rows and shielded receipts in one timeline: the two anchor
     * modes, side by side. */
    function rows() {
      return state.messages.concat(
        state.shielded.map(function (receipt) {
          return shieldedMessage(
            receipt,
            state.shieldedChain[receipt.txid] || null,
          );
        }),
      );
    }

    /* Read the receipts this page was handed. A failed receipt is named, not
     * hidden: a missing panel would be a worse lie than an error. */
    async function loadShielded() {
      if (!state.receiptIds.length) {
        return;
      }
      var fetched = [];
      for (var i = 0; i < state.receiptIds.length; i++) {
        var id = state.receiptIds[i];
        try {
          var body = await requestJson(
            apiUrl(state.zanchorUrl, "/receipts/" + encodeURIComponent(id)),
          );
          fetched.push(body);
          delete state.shieldedErrors[id];
        } catch (error) {
          state.shieldedErrors[id] =
            error instanceof Error ? error.message : String(error);
        }
      }
      state.shielded = fetched;
    }

    function storedFlag(key) {
      try {
        return window.localStorage.getItem(key) === "1";
      } catch (error) {
        return false;
      }
    }

    var toastTimer = null;
    var toast = el("div", { class: "toast", role: "status" });
    function showToast(text) {
      toast.textContent = text;
      toast.classList.add("show");
      if (toastTimer) {
        clearTimeout(toastTimer);
      }
      toastTimer = setTimeout(function () {
        toast.classList.remove("show");
      }, 1800);
    }

    function copyText(text, okLabel) {
      var done = function () {
        showToast(okLabel || "Copied");
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {
          legacyCopy(text);
          done();
        });
      } else {
        legacyCopy(text);
        done();
      }
    }

    function legacyCopy(text) {
      var area = el("textarea", {
        style: "position:fixed;top:0;left:0;opacity:0;pointer-events:none;",
      });
      area.value = text;
      document.body.append(area);
      area.select();
      try {
        document.execCommand("copy");
      } catch (error) {
        /* no clipboard — the text stays selectable in the field */
      }
      area.remove();
    }

    var healthText = el("span", {
      id: "health-text",
      text: "Reading the evidence ledger…",
    });
    var health = el("p", { class: "health" }, [
      el("span", { class: "dot wait", id: "health-dot" }),
      healthText,
    ]);
    var refreshButton = el("button", {
      type: "button",
      id: "refresh",
      text: "Refresh",
      onClick: function () {
        load();
      },
    });
    var autoBox = el("input", { type: "checkbox", id: "auto-refresh" });
    autoBox.checked = true;
    autoBox.addEventListener("change", function () {
      state.auto = autoBox.checked;
    });
    var ledgerInput = el("input", {
      id: "ledger-url",
      type: "url",
      value: state.ledgerUrl,
      spellcheck: "false",
    });
    var dashboardInput = el("input", {
      id: "dashboard-url",
      type: "url",
      value: state.dashboardUrl,
      spellcheck: "false",
    });
    var hornetInput = el("input", {
      id: "hornet-url",
      type: "url",
      value: state.hornetUrl,
      spellcheck: "false",
    });
    var endpointForm = el("form", {}, [
      el("label", { text: "Ledger" }, [ledgerInput]),
      el("label", { text: "Hornet dashboard" }, [dashboardInput]),
      el("label", { text: "Hornet REST" }, [hornetInput]),
      el("div", { class: "endpoint-actions" }, [
        el("button", { type: "submit", text: "Apply" }),
        el("button", {
          type: "button",
          text: "Use defaults",
          onClick: resetEndpoints,
        }),
      ]),
    ]);
    endpointForm.addEventListener("submit", function (event) {
      event.preventDefault();
      applyEndpoints();
    });
    var toolbar = el("div", { class: "toolbar" }, [
      health,
      el("div", { class: "toolbar-actions" }, [
        refreshButton,
        el("label", { class: "auto" }, [
          autoBox,
          document.createTextNode("Auto"),
        ]),
        el("details", { class: "endpoints" }, [
          el("summary", { text: "Endpoints" }),
          endpointForm,
        ]),
      ]),
    ]);

    var filterButtons = {};
    var filterRow = el("div", {
      class: "filters",
      role: "group",
      "aria-label": "Evidence state",
    });
    FILTERS.forEach(function (filter) {
      var count = el("span", { class: "count", text: "0" });
      var button = el(
        "button",
        {
          type: "button",
          "data-filter": filter.id,
          "aria-pressed": filter.id === state.filter ? "true" : "false",
          onClick: function () {
            state.filter = filter.id;
            renderBoard();
          },
        },
        [document.createTextNode(filter.label + " "), count],
      );
      filterButtons[filter.id] = { button: button, count: count };
      filterRow.append(button);
    });
    var searchInput = el("input", {
      id: "block-query",
      type: "search",
      placeholder: "0x…",
      spellcheck: "false",
      onInput: function (event) {
        state.blockQuery = event.target.value;
        renderBoard();
      },
    });
    filterRow.append(
      el("label", { class: "search" }, [
        document.createTextNode("Block id"),
        searchInput,
      ]),
    );

    var timeline = el("div", { id: "timeline", class: "timeline" });
    var detail = el("div", { id: "detail", class: "detail" });
    var hint = el("p", { class: "hint", id: "truncation" });
    root.append(
      toolbar,
      filterRow,
      el("div", { class: "workspace" }, [timeline, detail]),
      hint,
      toast,
    );

    window.addEventListener("hashchange", function () {
      var id = blockIdFromHash();
      if (
        id &&
        state.messages.some(function (message) {
          return message.block_id === id;
        })
      ) {
        state.selectedId = id;
        renderBoard();
      }
    });

    function store(key, value) {
      try {
        if (value) {
          window.localStorage.setItem(key, value);
        } else {
          window.localStorage.removeItem(key);
        }
      } catch (error) {
        /* Private mode can reject storage. The form still applies for this visit. */
      }
    }

    function stripEndpointParams() {
      var next = new URLSearchParams(window.location.search);
      next.delete("ledger");
      next.delete("dashboard");
      next.delete("hornet");
      var query = next.toString();
      var hash = window.location.hash || "";
      window.history.replaceState(
        null,
        "",
        window.location.pathname + (query ? "?" + query : "") + hash,
      );
    }

    function applyEndpoints() {
      var ledger = httpOrigin(ledgerInput.value);
      var dashboard = httpOrigin(dashboardInput.value);
      var hornet = httpOrigin(hornetInput.value);
      if (ledger == null || dashboard == null || hornet == null) {
        state.error = "Endpoints must be http or https URLs.";
        updateChrome();
        return;
      }
      if (!ledger) {
        state.error = "The ledger URL is required.";
        updateChrome();
        return;
      }
      state.ledgerUrl = ledger;
      state.dashboardUrl = dashboard;
      state.hornetUrl = hornet;
      ledgerInput.value = ledger;
      dashboardInput.value = dashboard;
      hornetInput.value = hornet;
      store("vickrey.ledgerUrl", ledger);
      store("vickrey.dashboardUrl", dashboard);
      store("vickrey.hornetUrl", hornet);
      stripEndpointParams();
      state.selectedId = null;
      state.rendered = "";
      load();
    }

    function resetEndpoints() {
      store("vickrey.ledgerUrl", "");
      store("vickrey.dashboardUrl", "");
      store("vickrey.hornetUrl", "");
      state.ledgerUrl = state.defaults.ledgerUrl;
      state.dashboardUrl = state.defaults.dashboardUrl;
      state.hornetUrl = state.defaults.hornetUrl;
      ledgerInput.value = state.ledgerUrl;
      dashboardInput.value = state.dashboardUrl;
      hornetInput.value = state.hornetUrl;
      stripEndpointParams();
      state.selectedId = null;
      state.rendered = "";
      load();
    }

    function syncUrl() {
      var next = new URLSearchParams(window.location.search);
      if (state.filter === "ALL") {
        next.delete("status");
      } else {
        next.set("status", state.filter);
      }
      var query = next.toString();
      var hash = state.selectedId
        ? "#" + encodeURIComponent(state.selectedId)
        : "";
      window.history.replaceState(
        null,
        "",
        window.location.pathname + (query ? "?" + query : "") + hash,
      );
    }

    function updateChrome() {
      var dot = document.getElementById("health-dot");
      dot.className = "dot";
      if (!state.loaded) {
        dot.classList.add("wait");
        healthText.textContent =
          "Reading the evidence ledger at " + state.ledgerUrl + "…";
      } else if (state.error && !state.messages.length) {
        dot.classList.add("bad");
        healthText.textContent =
          "Ledger did not answer at " + state.ledgerUrl + ". " + state.error;
      } else if (state.error) {
        dot.classList.add("bad");
        healthText.textContent =
          "Ledger read failed (" + state.error + "). Showing the last docket.";
      } else {
        dot.classList.add("ok");
        var hornet =
          state.health && state.health.hornet_url
            ? state.health.hornet_url
            : "an unknown Hornet";
        var checked = "";
        if (state.lastChecked) {
          var ago = Math.max(
            0,
            Math.round((Date.now() - state.lastChecked) / 1000),
          );
          checked = " · checked " + (ago < 5 ? "just now" : ago + "s ago");
        }
        healthText.textContent =
          "Ledger answering at " +
          state.ledgerUrl +
          ". It reads Hornet at " +
          hornet +
          "." +
          checked;
      }
      var counts = { ALL: state.messages.length };
      FILTERS.forEach(function (filter) {
        if (filter.id !== "ALL") {
          counts[filter.id] = state.messages.filter(function (message) {
            return message.status === filter.id;
          }).length;
        }
        var entry = filterButtons[filter.id];
        entry.count.textContent = String(counts[filter.id]);
        entry.button.setAttribute(
          "aria-pressed",
          filter.id === state.filter ? "true" : "false",
        );
      });
      if (state.loaded && state.total > state.messages.length) {
        hint.textContent =
          "Showing " +
          state.messages.length +
          " of " +
          state.total +
          " stored observations. The ledger page size stops at 500.";
      } else {
        hint.textContent = "";
      }
    }

    function signature() {
      return JSON.stringify({
        filter: state.filter,
        query: state.blockQuery,
        selected: state.selectedId,
        shielded: state.shielded,
        shieldedChain: state.shieldedChain,
        shieldedErrors: state.shieldedErrors,
        error: state.error,
        notice: state.notice,
        actionError: state.actionError,
        busy: state.busy,
        loaded: state.loaded,
        walk: state.walk,
        walkDismissed: state.walkDismissed,
        justTampered: state.justTampered,
        justReverified: state.justReverified,
        messages: state.messages.map(function (message) {
          return [
            message.block_id,
            message.status,
            message.updated_at,
            message.payload_json,
            message.ledger_payload_json,
            message.ledger_tag,
            message.solid,
            message.milestone_index,
            message.detail,
          ];
        }),
      });
    }

    function renderBoard() {
      updateChrome();
      var sig = signature();
      if (sig === state.rendered) {
        return;
      }
      state.rendered = sig;
      syncUrl();
      timeline.replaceChildren();
      detail.replaceChildren();
      if (!state.loaded) {
        var skeleton = el("ol", { class: "events skeleton" });
        for (var row = 0; row < 4; row++) {
          skeleton.append(el("li", { class: "skeleton-row" }));
        }
        timeline.append(skeleton);
        return;
      }
      if (state.error && !state.messages.length && !state.shielded.length) {
        timeline.append(
          el("p", {
            class: "empty",
            text: "Nothing to show until the ledger answers.",
          }),
        );
        detail.append(
          el("p", {
            class: "empty",
            text: "Start the ledger on port 8088, or set Endpoints to the machine that publishes it.",
          }),
        );
        return;
      }
      Object.keys(state.shieldedErrors).forEach(function (id) {
        timeline.append(
          el("p", {
            class: "empty",
            text:
              "Shielded receipt " +
              id +
              " could not be read: " +
              state.shieldedErrors[id],
          }),
        );
      });
      var visible = applyFilter(rows(), state.filter, state.blockQuery);
      if (!visible.length) {
        var emptyText = "No observations in this filter.";
        if (String(state.blockQuery || "").trim()) {
          emptyText = "No observation matches that block id.";
        } else if (state.filter === "PAYLOAD_MISMATCH") {
          emptyText = "No mismatches — every record agrees.";
        } else if (state.filter === "VERIFIED") {
          emptyText = "Nothing verified yet.";
        } else if (state.filter === "NOT_SOLID") {
          emptyText = "Everything is solid.";
        } else if (state.filter === "PENDING") {
          emptyText = "Nothing pending — every check has settled.";
        }
        timeline.append(el("p", { class: "empty", text: emptyText }));
      } else {
        groupByFlow(visible).forEach(function (group) {
          var countLabel =
            group.messages.length === 1
              ? "1 observation"
              : group.messages.length + " observations";
          var title = el("h2", { class: "flow-label" }, [
            el("span", {}, [
              el("span", { class: "flow-kicker", text: "flow" }),
              document.createTextNode(" "),
              el("b", { text: group.flowId || "No flowId" }),
            ]),
            el("span", { text: countLabel }),
          ]);
          var list = el("ol", { class: "events" });
          /* Arrow keys move focus between events in a flow; Enter or Space
           * (native button behaviour) selects the focused one. */
          list.addEventListener("keydown", function (event) {
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
              return;
            }
            var buttons = Array.prototype.slice.call(
              list.querySelectorAll("button.event"),
            );
            var index = buttons.indexOf(document.activeElement);
            var next = buttons[index + (event.key === "ArrowDown" ? 1 : -1)];
            if (index < 0 || !next) {
              return;
            }
            event.preventDefault();
            next.focus();
          });
          group.messages.forEach(function (message) {
            list.append(renderEvent(message));
          });
          timeline.append(el("section", { class: "flow" }, [title, list]));
        });
      }
      var selected = rows().find(function (message) {
        return message.block_id === state.selectedId;
      });
      var walk = renderWalkthrough(selected);
      if (walk) {
        detail.append(walk);
      }
      if (!selected) {
        detail.append(
          el("p", {
            class: "empty",
            text: "Open an observation to see the trust checklist.",
          }),
        );
        return;
      }
      var inView = visible.some(function (message) {
        return message.block_id === selected.block_id;
      });
      if (!inView) {
        detail.append(
          el("p", {
            class: "hint",
            text: "This observation is outside the current filter. The checklist stays open.",
          }),
        );
      }
      if (selected.status === "PAYLOAD_MISMATCH") {
        state.walk.sawMismatch = true;
      }
      detail.append(renderDetail(selected));
    }

    function renderWalkthrough(selected) {
      if (state.walkDismissed) {
        return null;
      }
      var steps = [
        { text: "Open an observation", done: state.selectedId != null },
        { text: "Tamper the application copy", done: state.walk.tampered },
        {
          text: "Watch the verdict flip to mismatch",
          done:
            state.walk.sawMismatch ||
            (selected && selected.status === "PAYLOAD_MISMATCH"),
        },
        {
          text: "Restore — the network copy wins",
          done: state.walk.reverified,
        },
      ];
      return el("section", { class: "walkthrough" }, [
        el("div", { class: "walk-head" }, [
          el("span", { class: "walk-kicker", text: "Try the demo" }),
          el("button", {
            type: "button",
            class: "walk-dismiss",
            text: "Hide",
            onClick: function () {
              state.walkDismissed = true;
              store("vickrey.walk.dismissed", "1");
              renderBoard();
            },
          }),
        ]),
        el(
          "ol",
          { class: "walk-steps" },
          steps.map(function (step, index) {
            return el("li", { class: step.done ? "done" : "" }, [
              el("span", { class: "walk-num", text: String(index + 1) }),
              el("span", { text: step.text }),
            ]);
          }),
        ),
      ]);
    }

    function renderEvent(message) {
      var mark = highlightLabel(message);
      return el("li", {}, [
        el(
          "button",
          {
            type: "button",
            class: "event" + (mark ? " is-alarm" : ""),
            "data-status": message.status || "",
            "aria-current":
              message.block_id === state.selectedId ? "true" : "false",
            onClick: function () {
              state.selectedId = message.block_id;
              state.notice = "";
              state.actionError = "";
              state.rendered = "";
              renderBoard();
            },
          },
          [
            el("span", {
              class: "event-time",
              text: formatClock(message.inserted_at),
            }),
            el("span", { class: "event-main" }, [
              el("span", {
                class: "stamp",
                "data-status": message.status || "",
                text: stampText(message),
              }),
              el("span", {
                class: "event-title",
                text: incidentTitle(message),
              }),
              el("span", {
                class: "event-id",
                text: shortId(message.block_id),
              }),
              mark ? el("span", { class: "flag", text: mark }) : null,
            ]),
          ],
        ),
      ]);
    }

    function renderDetail(message) {
      if (message && message.zanchor) {
        return renderShieldedDetail(message);
      }
      var checks = checklist(message);
      var differ = payloadsDiffer(
        message.payload_json,
        message.ledger_payload_json,
      );
      var dashboard = dashboardBlockUrl(state.dashboardUrl, message.block_id);
      var hornet = hornetBlockUrl(state.hornetUrl, message.block_id);
      var flash = "";
      if (state.justTampered === message.block_id) {
        flash = " just-tampered";
        state.justTampered = null;
      } else if (state.justReverified === message.block_id) {
        flash = " just-reverified";
        state.justReverified = null;
      }
      var rel = relativeTime(message.inserted_at);
      var verdict = differ ? verdictLine(message) : "";
      var nodes = [
        el("span", {
          class: "stamp large" + (flash ? " stamp-flip" : ""),
          "data-status": message.status || "",
          text: statusLabel(message.status),
        }),
        highlightedFlag(message),
        el("h2", { text: incidentTitle(message) }),
        el("p", { class: "block-line mono" }, [
          el("button", {
            type: "button",
            class: "id-btn",
            title: "Copy the full block id",
            text: message.block_id,
            onClick: function () {
              copyText(message.block_id, "Block id copied");
            },
          }),
          document.createTextNode(
            " · " +
              formatTime(message.inserted_at) +
              (rel ? " (" + rel + ")" : "") +
              (message.flow_id ? " · " + message.flow_id : "") +
              (message.tag ? " · " + message.tag : ""),
          ),
        ]),
        verdict ? el("p", { class: "verdict", text: verdict }) : null,
        renderChecklist(checks),
        renderDemo(message),
        el("p", { class: "pitch", text: pitchLine(message) }),
        el("div", { class: "links" }, [
          dashboard
            ? el("a", {
                href: dashboard,
                target: "_blank",
                rel: "noopener noreferrer",
                text: "Open on Hornet dashboard",
              })
            : null,
          hornet
            ? el("a", {
                href: hornet,
                target: "_blank",
                rel: "noopener noreferrer",
                text: "Hornet block JSON",
              })
            : null,
          el("button", {
            type: "button",
            class: "link-btn",
            text: "Copy link to this observation",
            onClick: function () {
              var url =
                window.location.origin +
                window.location.pathname +
                "#" +
                encodeURIComponent(message.block_id);
              copyText(url, "Observation link copied");
            },
          }),
        ]),
        renderCompare(message, differ, flash),
      ];
      if (message.detail) {
        nodes.push(
          el("p", { class: "pitch", text: "Last check: " + message.detail }),
        );
      }
      return el("article", { class: flash ? flash.slice(1) : "" }, nodes);
    }

    /* The money shot: SHIELDED · VERIFIED over a public checklist that has
     * nothing to check — beside the verifier's binding and the one check
     * anyone can run. When the service reports a transparent fallback the
     * card keeps the shape and changes the claims: TRANSPARENT stamp, the
     * exposure rows, and a paragraph that says what the chain does show. */
    function renderShieldedDetail(message) {
      var receipt = message.receipt || {};
      var chain = message.chain;
      var explorer = blockExplorerUrl(receipt.txid);
      var shielded = message.shielded;
      var pitch =
        shielded === true
          ? "The public chain proves that a transaction exists at a height — and reveals nothing else. No species, no area, no observer, no purpose. This checklist is not short of checks; there is nothing on the chain to check against."
          : shielded === false
            ? "This anchor is not shielded. The transaction is public — its amount, its addresses, its block time — and none of that names a species, an area, or an observer. What links this transaction to an observation is the receipt, which the verifier holds."
            : "The service did not report whether this transaction is shielded, so this page claims nothing about it. The receipt is still the only link to the observation.";
      return el("article", { class: "shielded-detail" }, [
        el("span", {
          class: "stamp large",
          "data-status": message.status || "",
          text: stampText(message),
        }),
        el("h2", { text: incidentTitle(message) }),
        el("p", { class: "block-line mono" }, [
          el("button", {
            type: "button",
            class: "id-btn",
            title: "Copy the transaction id",
            text: receipt.txid || receipt.receipt_id || "—",
            onClick: function () {
              copyText(
                receipt.txid || receipt.receipt_id,
                "Transaction id copied",
              );
            },
          }),
          document.createTextNode(
            " · " +
              (receipt.anchored_at
                ? formatTime(receipt.anchored_at)
                : "not yet confirmed") +
              (receipt.receipt_id ? " · " + receipt.receipt_id : ""),
          ),
        ]),
        el("p", { class: "pitch", text: pitch }),
        el("section", { class: "shield-block" }, [
          el("h3", { text: "What the public chain reveals" }),
          el(
            "ul",
            { class: "checklist" },
            revealRows(shielded).map(function (row) {
              return checkItem(row.name, row);
            }),
          ),
        ]),
        el("section", { class: "shield-block" }, [
          el("h3", { text: "What anyone can check" }),
          el("p", {
            class: "hint",
            text: "Proof of existence: the transaction id sits at a block height. Anyone can run this check, and it answers nothing about the observation.",
          }),
          el("div", { class: "links" }, [
            el("button", {
              type: "button",
              class: "link-btn",
              text: chain ? "Check the chain again" : "Check the chain",
              onClick: function () {
                checkChain(message);
              },
            }),
            explorer
              ? el("a", {
                  href: explorer,
                  target: "_blank",
                  rel: "noopener noreferrer",
                  text: "Open the transaction in a block explorer",
                })
              : null,
          ]),
          chain ? renderChainCheck(chain, shielded) : null,
        ]),
        el("section", { class: "shield-block" }, [
          el("h3", { text: "What the verifier holds" }),
          el(
            "ul",
            { class: "receipt" },
            receiptRows(receipt, chain).map(function (row) {
              return el("li", {}, [
                el("b", { text: row.label }),
                el("span", {
                  class: row.mono ? "mono wrap" : "",
                  text: String(row.value),
                }),
              ]);
            }),
          ),
          el("p", {
            class: "hint",
            text: "The verifier holds this binding and can disclose one anchor at a time through the viewing key — to a researcher or a court, and to nobody else.",
          }),
        ]),
      ]);
    }

    function renderChainCheck(chain, shielded) {
      if (chain && chain.exists) {
        return el("ul", { class: "checklist" }, [
          el("li", { class: "check pass" }, [
            el("b", { text: CHECK_WORD.pass }),
            el("span", {
              text:
                "The transaction exists at height " +
                chain.height +
                (chain.confirmations == null
                  ? ""
                  : " · " + chain.confirmations + " confirmations") +
                (shielded === false
                  ? ". It is transparent — what it anchors is not on the chain."
                  : ". Nothing else is on the chain."),
            }),
          ]),
        ]);
      }
      return el("ul", { class: "checklist" }, [
        el("li", { class: "check fail" }, [
          el("b", { text: CHECK_WORD.fail }),
          el("span", { text: "The node does not know this transaction." }),
        ]),
      ]);
    }

    function highlightedFlag(message) {
      var label = highlightLabel(message);
      if (!label) {
        return null;
      }
      return el("span", { class: "flag", text: label });
    }

    function renderChecklist(checks) {
      return el("ul", { class: "checklist" }, [
        checkItem("Payload", checks.payload),
        checkItem("Solid", checks.solid),
        checkItem("Milestone", checks.milestone),
        checkItem("Tag", checks.tag),
      ]);
    }

    function checkItem(name, item) {
      return el("li", { class: "check " + item.state }, [
        el("b", { text: CHECK_WORD[item.state] || item.state }),
        el("span", {}, [
          document.createTextNode(name + " — " + item.label),
          item.detail ? el("small", { text: item.detail }) : null,
        ]),
      ]);
    }

    function renderCompare(message, differ, flash) {
      var ledgerKnown =
        message.ledger_payload_json !== null &&
        message.ledger_payload_json !== undefined;
      if (!ledgerKnown && message.status !== "PAYLOAD_MISMATCH") {
        return el("section", { class: "compare" }, [
          el("h3", { text: "Your app says" }),
          el("pre", { text: pretty(message.payload_json) }),
        ]);
      }
      var heading = differ
        ? "PAYLOAD MISMATCH"
        : ledgerKnown
          ? "Payloads agree"
          : "Content check";
      var keys = changedKeys(message.payload_json, message.ledger_payload_json);
      var children = [el("h3", { text: heading })];
      if (!differ && message.status === "PAYLOAD_MISMATCH" && ledgerKnown) {
        children.push(
          el("p", {
            class: "pitch",
            text: "These JSON values agree. The tag check failed.",
          }),
        );
      }
      if (keys.length) {
        var table = el("table", { class: "delta" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Field" }),
              el("th", { text: "Your app" }),
              el("th", { text: "The network" }),
            ]),
          ]),
        ]);
        var body = el("tbody");
        keys.forEach(function (key) {
          body.append(
            el("tr", { class: "diff" }, [
              el("th", { text: key }),
              el("td", { class: "cell-app" }, [
                el("b", { text: formatCell(message.payload_json[key]) }),
              ]),
              el("td", { class: "cell-anchor" }, [
                el("b", { text: formatCell(message.ledger_payload_json[key]) }),
              ]),
            ]),
          );
        });
        table.append(body);
        children.push(table);
      }
      children.push(
        el("div", { class: "columns" }, [
          el("section", { class: differ ? "differs" : "" }, [
            el("h4", {}, [
              document.createTextNode("Your app says "),
              el("small", { text: "application copy" }),
            ]),
            el("pre", { text: pretty(message.payload_json) }),
          ]),
          el("section", { class: differ ? "differs" : "" }, [
            el("h4", {}, [
              document.createTextNode("The network recorded "),
              el("small", { text: "Hornet tagged data" }),
            ]),
            el("pre", {
              text: pretty(
                ledgerKnown
                  ? message.ledger_payload_json
                  : message.detail || "Unavailable",
              ),
            }),
          ]),
        ]),
      );
      return el(
        "section",
        {
          class:
            "compare" +
            (differ ? " is-mismatch" : "") +
            (flash ? " pulse-once" : ""),
        },
        children,
      );
    }

    function renderDemo(message) {
      var mismatched = message.status === "PAYLOAD_MISMATCH";
      var canRestore = mismatched && isPlainObject(message.ledger_payload_json);
      return el("div", { class: "demo" }, [
        el("div", { class: "row" }, [
          canRestore
            ? el("button", {
                type: "button",
                id: "restore",
                class: "primary",
                text: "Restore the app copy from the network",
                disabled: state.busy,
                onClick: function () {
                  restore(message);
                },
              })
            : null,
          el("button", {
            type: "button",
            id: "reverify",
            class: mismatched && !canRestore ? "primary" : "",
            text: "Re-verify against the network",
            disabled: state.busy,
            onClick: function () {
              reverify(message.block_id);
            },
          }),
          el("button", {
            type: "button",
            id: "tamper",
            class: "danger",
            text: "Tamper application copy",
            disabled: state.busy,
            onClick: function () {
              tamper(message);
            },
          }),
        ]),
        el("p", {
          text: mismatched
            ? "The block never changed — restoring puts the anchored copy back in the app."
            : "Tamper edits the application copy only — the anchored block is never modified.",
        }),
        state.notice
          ? el("p", { class: "notice", role: "status", text: state.notice })
          : null,
        state.actionError
          ? el("p", {
              class: "action-error",
              role: "alert",
              text: state.actionError,
            })
          : null,
      ]);
    }

    function replaceMessage(message) {
      var found = false;
      state.messages = state.messages.map(function (row) {
        if (row.block_id !== message.block_id) {
          return row;
        }
        found = true;
        return message;
      });
      if (!found) {
        state.messages.unshift(message);
      }
      state.selectedId = message.block_id;
    }

    async function requestJson(url, options) {
      var response = await fetch(url, options || {});
      var text = await response.text();
      var body = null;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch (error) {
          body = { detail: text };
        }
      }
      if (!response.ok) {
        var detail =
          body && body.detail
            ? body.detail
            : response.status + " " + response.statusText;
        if (typeof detail !== "string") {
          detail = JSON.stringify(detail);
        }
        throw new Error(detail);
      }
      return body;
    }

    var loadGen = 0;

    function messagesKey(list) {
      return (list || [])
        .map(function (message) {
          return [
            message.block_id,
            message.status,
            message.updated_at,
            message.ledger_tag,
            message.solid,
            message.payload_json,
          ].join("|");
        })
        .join("\n");
    }

    async function load() {
      var gen = ++loadGen;
      state.error = null;
      /* Receipts are read first and outside the ledger's try: the two services
       * run separately, and a receipt link must still open the shielded card
       * when the ledger is down. loadShielded records its own per-receipt
       * errors, so a zanchor failure is named rather than swallowed. */
      await loadShielded();
      if (gen !== loadGen) {
        return;
      }
      try {
        var healthUrl = apiUrl(state.ledgerUrl, "/health");
        var listUrl = apiUrl(state.ledgerUrl, "/messages?limit=500");
        var pair = await Promise.all([
          requestJson(healthUrl),
          requestJson(listUrl),
        ]);
        if (gen !== loadGen) {
          return;
        }
        var previousKey = messagesKey(state.messages);
        state.health = pair[0];
        state.lastChecked = Date.now();
        state.messages = (pair[1] && pair[1].messages) || [];
        /* Back off while the ledger is unchanged: each quiet poll adds one
         * interval of wait, capped at 8 skipped ticks (about 32s). Any change
         * or error returns to the 4s cadence. */
        if (messagesKey(state.messages) === previousKey) {
          pollIdle += 1;
        } else {
          pollIdle = 0;
        }
        pollWait = Math.min(pollIdle, 8);
        state.total =
          pair[1] && typeof pair[1].total === "number"
            ? pair[1].total
            : state.messages.length;
      } catch (error) {
        if (gen !== loadGen) {
          return;
        }
        state.health = null;
        pollIdle = 0;
        pollWait = 0;
        state.error = error instanceof Error ? error.message : String(error);
        if (!state.loaded) {
          state.messages = [];
          state.total = 0;
        }
      } finally {
        if (gen === loadGen) {
          state.loaded = true;
          /* Selection happens here, not in the try: a receipt row must be
           * selectable even when the ledger fetch threw. */
          var all = rows();
          var stillThere = all.some(function (message) {
            return message.block_id === state.selectedId;
          });
          if (!stillThere) {
            state.selectedId = chooseInitial(all);
          }
          renderBoard();
        }
      }
    }

    async function reverify(blockId) {
      state.busy = true;
      state.notice = "";
      state.actionError = "";
      renderBoard();
      try {
        var body = await requestJson(
          apiUrl(
            state.ledgerUrl,
            "/messages/" + encodeURIComponent(blockId) + "/reverify",
          ),
          {
            method: "POST",
            headers: { accept: "application/json" },
          },
        );
        var wasMismatch =
          body.status === "VERIFIED" &&
          state.messages.some(function (row) {
            return (
              row.block_id === body.block_id &&
              row.status === "PAYLOAD_MISMATCH"
            );
          });
        replaceMessage(body);
        if (body.status === "VERIFIED") {
          state.walk.reverified = true;
          if (wasMismatch) {
            state.justReverified = body.block_id;
          }
        }
        state.notice =
          "Re-verified. Status is " + statusLabel(body.status) + ".";
      } catch (error) {
        state.actionError =
          error instanceof Error ? error.message : String(error);
      } finally {
        state.busy = false;
        renderBoard();
      }
    }

    async function restore(message) {
      state.busy = true;
      state.notice = "";
      state.actionError = "";
      renderBoard();
      try {
        var body = await requestJson(
          apiUrl(
            state.ledgerUrl,
            "/messages/" + encodeURIComponent(message.block_id) + "/restore",
          ),
          {
            method: "POST",
            headers: { accept: "application/json" },
          },
        );
        replaceMessage(body);
        if (body.status === "VERIFIED") {
          state.walk.reverified = true;
          state.justReverified = body.block_id;
        }
        state.notice =
          "Application copy restored from the anchored block. Status is " +
          statusLabel(body.status) +
          ".";
      } catch (error) {
        state.actionError =
          error instanceof Error ? error.message : String(error);
      } finally {
        state.busy = false;
        renderBoard();
      }
    }

    /* The check anyone can run: this transaction id exists at a height. It
     * answers nothing about the observation. */
    async function checkChain(message) {
      var receipt = (message && message.receipt) || {};
      if (!receipt.txid) {
        return;
      }
      state.busy = true;
      state.notice = "";
      state.actionError = "";
      renderBoard();
      try {
        var body = await requestJson(
          apiUrl(
            state.zanchorUrl,
            "/chain/tx/" + encodeURIComponent(receipt.txid),
          ),
        );
        state.shieldedChain[receipt.txid] = body;
        state.notice =
          body && body.exists
            ? "Public check: the transaction exists at height " +
              body.height +
              ". Nothing else is on the chain."
            : "Public check: the node does not know this transaction.";
      } catch (error) {
        state.actionError =
          error instanceof Error ? error.message : String(error);
      } finally {
        state.busy = false;
        renderBoard();
      }
    }

    async function tamper(message) {
      state.busy = true;
      state.notice = "";
      state.actionError = "";
      renderBoard();
      var body = tamperBody(message);
      try {
        var result = await requestJson(
          apiUrl(
            state.ledgerUrl,
            "/messages/" + encodeURIComponent(message.block_id) + "/tamper",
          ),
          {
            method: "POST",
            headers: {
              accept: "application/json",
              "content-type": "application/json",
            },
            body: JSON.stringify(body),
          },
        );
        var updated = result && result.message ? result.message : result;
        replaceMessage(updated);
        state.walk.tampered = true;
        state.justTampered = updated.block_id;
        state.notice =
          result && result.note
            ? result.note
            : "Only the application copy changed — the anchored block is byte-identical. Status is " +
              statusLabel(updated.status) +
              ".";
      } catch (error) {
        state.actionError =
          error instanceof Error ? error.message : String(error);
      } finally {
        state.busy = false;
        renderBoard();
      }
    }

    var pollIdle = 0;
    var pollWait = 0;
    window.setInterval(function () {
      if (!state.auto || state.busy || document.hidden) {
        return;
      }
      if (pollWait > 0) {
        pollWait -= 1;
        return;
      }
      load();
    }, 4000);

    renderBoard();
    load();
  }

  return {
    apiUrl: apiUrl,
    applyFilter: applyFilter,
    blockExplorerUrl: blockExplorerUrl,
    changedKeys: changedKeys,
    checklist: checklist,
    chooseInitial: chooseInitial,
    dashboardBlockUrl: dashboardBlockUrl,
    groupByFlow: groupByFlow,
    hornetBlockUrl: hornetBlockUrl,
    httpOrigin: httpOrigin,
    highlightLabel: highlightLabel,
    incidentTitle: incidentTitle,
    isHighlighted: isHighlighted,
    mount: mount,
    normalizeFilter: normalizeFilter,
    payloadsDiffer: payloadsDiffer,
    pitchLine: pitchLine,
    receiptRows: receiptRows,
    relativeTime: relativeTime,
    revealRows: revealRows,
    shieldedMessage: shieldedMessage,
    shieldedState: shieldedState,
    stampText: stampText,
    statusLabel: statusLabel,
    tamperBody: tamperBody,
    verdictLine: verdictLine,
  };
});
