/* Incident Evidence Explorer.
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

  function pitchLine(message) {
    if (!message) {
      return "";
    }
    if (message.status === "VERIFIED") {
      return "This incident agrees. The application copy matches the Hornet block, the block is solid, and a milestone references it.";
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
      defaults: {
        ledgerUrl: cfg.ledgerUrl || "http://localhost:8088",
        dashboardUrl: cfg.dashboardUrl || "http://localhost:31011",
        hornetUrl: cfg.hornetUrl || "http://localhost:14265",
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
      defaults: config.defaults,
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
    };

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
        healthText.textContent =
          "Ledger answering at " +
          state.ledgerUrl +
          ". It reads Hornet at " +
          hornet +
          ".";
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
          " stored incidents. The ledger page size stops at 500.";
      } else {
        hint.textContent = "";
      }
    }

    function signature() {
      return JSON.stringify({
        filter: state.filter,
        query: state.blockQuery,
        selected: state.selectedId,
        error: state.error,
        notice: state.notice,
        actionError: state.actionError,
        busy: state.busy,
        loaded: state.loaded,
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
        timeline.append(
          el("p", { class: "empty", text: "Reading the evidence ledger…" }),
        );
        return;
      }
      if (state.error && !state.messages.length) {
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
      var visible = applyFilter(state.messages, state.filter, state.blockQuery);
      if (!visible.length) {
        timeline.append(
          el("p", { class: "empty", text: "No incidents in this filter." }),
        );
      } else {
        groupByFlow(visible).forEach(function (group) {
          var countLabel =
            group.messages.length === 1
              ? "1 incident"
              : group.messages.length + " incidents";
          var title = el("h2", { class: "flow-label" }, [
            el("span", {}, [
              el("span", { class: "flow-kicker", text: "flow" }),
              document.createTextNode(" "),
              el("b", { text: group.flowId || "No flowId" }),
            ]),
            el("span", { text: countLabel }),
          ]);
          var list = el("ol", { class: "events" });
          group.messages.forEach(function (message) {
            list.append(renderEvent(message));
          });
          timeline.append(el("section", { class: "flow" }, [title, list]));
        });
      }
      var selected = state.messages.find(function (message) {
        return message.block_id === state.selectedId;
      });
      if (!selected) {
        detail.append(
          el("p", {
            class: "empty",
            text: "Open an incident to see the trust checklist.",
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
            text: "This incident is outside the current filter. The checklist stays open.",
          }),
        );
      }
      detail.append(renderDetail(selected));
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
                text: statusLabel(message.status),
              }),
              el("span", {
                class: "event-tag",
                text: message.tag || "(no tag)",
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
      var checks = checklist(message);
      var differ = payloadsDiffer(
        message.payload_json,
        message.ledger_payload_json,
      );
      var dashboard = dashboardBlockUrl(state.dashboardUrl, message.block_id);
      var hornet = hornetBlockUrl(state.hornetUrl, message.block_id);
      var meta =
        message.block_id +
        " · " +
        formatTime(message.inserted_at) +
        (message.flow_id ? " · " + message.flow_id : " · no flowId");
      var nodes = [
        el("span", {
          class: "stamp large",
          "data-status": message.status || "",
          text: statusLabel(message.status),
        }),
        highlightedFlag(message),
        el("h2", { text: message.tag || "(no tag)" }),
        el("p", { class: "block-line mono", text: meta }),
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
        ]),
        renderCompare(message, differ),
      ];
      if (message.detail) {
        nodes.push(
          el("p", { class: "pitch", text: "Last check: " + message.detail }),
        );
      }
      return el("article", {}, nodes);
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

    function renderCompare(message, differ) {
      var ledgerKnown =
        message.ledger_payload_json !== null &&
        message.ledger_payload_json !== undefined;
      if (!ledgerKnown && message.status !== "PAYLOAD_MISMATCH") {
        return el("section", { class: "compare" }, [
          el("h3", { text: "Application copy" }),
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
              el("th", { text: "Application" }),
              el("th", { text: "Hornet" }),
            ]),
          ]),
        ]);
        var body = el("tbody");
        keys.forEach(function (key) {
          body.append(
            el("tr", { class: "diff" }, [
              el("th", { text: key }),
              el("td", {}, [
                el("b", { text: formatCell(message.payload_json[key]) }),
              ]),
              el("td", {}, [
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
            el("h4", { text: "Application copy" }),
            el("pre", { text: pretty(message.payload_json) }),
          ]),
          el("section", { class: differ ? "differs" : "" }, [
            el("h4", { text: "Hornet tagged data" }),
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
        { class: "compare" + (differ ? " is-mismatch" : "") },
        children,
      );
    }

    function renderDemo(message) {
      return el("div", { class: "demo" }, [
        el("div", { class: "row" }, [
          el("button", {
            type: "button",
            id: "reverify",
            text: "Re-check Hornet",
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
          text: "Tamper overwrites the application copy only. Hornet is not modified.",
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

    async function load() {
      var gen = ++loadGen;
      state.error = null;
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
        state.health = pair[0];
        state.messages = (pair[1] && pair[1].messages) || [];
        state.total =
          pair[1] && typeof pair[1].total === "number"
            ? pair[1].total
            : state.messages.length;
        var stillThere = state.messages.some(function (message) {
          return message.block_id === state.selectedId;
        });
        if (!stillThere) {
          state.selectedId = chooseInitial(state.messages);
        }
      } catch (error) {
        if (gen !== loadGen) {
          return;
        }
        state.health = null;
        state.error = error instanceof Error ? error.message : String(error);
        if (!state.loaded) {
          state.messages = [];
          state.total = 0;
        }
      } finally {
        if (gen === loadGen) {
          state.loaded = true;
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
        replaceMessage(body);
        state.notice =
          "Re-checked. Status is " + statusLabel(body.status) + ".";
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
      var body = {};
      if (isPlainObject(message.payload_json)) {
        body = { temperature: 999.9 };
      }
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
        state.notice =
          result && result.note
            ? result.note
            : "Application copy overwritten. Status is " +
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

    window.setInterval(function () {
      if (!state.auto || state.busy || document.hidden) {
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
    changedKeys: changedKeys,
    checklist: checklist,
    chooseInitial: chooseInitial,
    dashboardBlockUrl: dashboardBlockUrl,
    groupByFlow: groupByFlow,
    hornetBlockUrl: hornetBlockUrl,
    httpOrigin: httpOrigin,
    highlightLabel: highlightLabel,
    isHighlighted: isHighlighted,
    mount: mount,
    normalizeFilter: normalizeFilter,
    payloadsDiffer: payloadsDiffer,
    pitchLine: pitchLine,
    statusLabel: statusLabel,
  };
});
