/* Vickrey field journal.
 *
 * The durable, on-device history of every sealed sighting. The outbox
 * (queue.js) only holds what still has to be sent, and sync drains it; the
 * journal is never drained, so a verified sync cannot erase a sighting from the
 * device. Each record keeps the sealed entry exactly as it was signed, plus
 * local-only extras (a small thumbnail, the sync outcome). None of the extras
 * are part of the hash or the anchor.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyJournal = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function createJournal(options) {
    options = options || {};
    var queueApi = root.VickreyQueue;
    var store =
      options.store ||
      (options.key && queueApi
        ? queueApi.localStore(options.key)
        : {
            load: function () {
              return [];
            },
            save: function () {},
          });
    var records = (store.load() || []).filter(function (record) {
      return record && record.entry && typeof record.entry.hash === "string";
    });

    function persist() {
      store.save(records);
    }

    function indexOf(hash) {
      for (var i = 0; i < records.length; i++) {
        if (records[i].entry.hash === hash) {
          return i;
        }
      }
      return -1;
    }

    /* Keep a sealed entry. A deep copy, so a later edit to the outbox copy can
     * never reach the journal's copy. Recording the same hash twice is a no-op. */
    function record(entry, extras) {
      if (!entry || typeof entry.hash !== "string") {
        throw new Error("journal needs a sealed entry with a hash");
      }
      var existing = indexOf(entry.hash);
      if (existing !== -1) {
        return records[existing];
      }
      extras = extras || {};
      var item = {
        entry: clone(entry),
        thumb: typeof extras.thumb === "string" ? extras.thumb : null,
        recorded_at: extras.recordedAt || new Date().toISOString(),
        sync: { state: "pending" },
      };
      records.push(item);
      persist();
      return item;
    }

    /* Adopt entries that were sealed before the journal existed. */
    function adopt(entries) {
      var added = 0;
      (entries || []).forEach(function (entry) {
        if (
          entry &&
          typeof entry.hash === "string" &&
          indexOf(entry.hash) === -1
        ) {
          record(entry);
          added += 1;
        }
      });
      return added;
    }

    function markAnchored(hash, row, at) {
      var i = indexOf(hash);
      if (i === -1) {
        return null;
      }
      row = row || {};
      records[i].sync = {
        state: "anchored",
        status: typeof row.status === "string" ? row.status : "UNKNOWN",
        mode: row.mode === "shielded" ? "shielded" : "public",
        /* The mechanism the anchor service actually ran (docs/ZANCHOR_API.md):
         * "A" note-burn or "B" encrypted memo — kept beside `mode`, which
         * records the routing (shielded vs public). */
        anchor_mode:
          row.anchor_mode === "A" || row.anchor_mode === "B"
            ? row.anchor_mode
            : null,
        /* What the service said the transaction is (docs/ZANCHOR_API.md).
         * null when it did not say: the page must not assume shielding. */
        shielded:
          row.shielded === true ? true : row.shielded === false ? false : null,
        block_id: row.block_id || null,
        milestone_index:
          row.milestone_index === undefined ? null : row.milestone_index,
        /* Shielded receipts (docs/ZANCHOR_API.md): the commitment-to-txid-to-
         * height binding. All null in public mode. */
        receipt_id: row.receipt_id || null,
        txid: row.txid || null,
        height: row.height === undefined ? null : row.height,
        at: at || new Date().toISOString(),
      };
      persist();
      return records[i];
    }

    function markRefused(hash, reason, at) {
      var i = indexOf(hash);
      if (i === -1 || records[i].sync.state === "anchored") {
        return null;
      }
      records[i].sync = {
        state: "refused",
        reason: String(reason || "sync refused"),
        at: at || new Date().toISOString(),
      };
      persist();
      return records[i];
    }

    /* An accepted anchor can still fail later (the node's operation errors
     * after broadcast). The sealed entry is untouched; the record is marked
     * failed so the page can offer an explicit retry of the same entry. */
    function markFailed(hash, reason, at) {
      var i = indexOf(hash);
      if (i === -1) {
        return null;
      }
      var prev = records[i].sync || {};
      if (prev.state === "anchored" && prev.status === "confirmed") {
        return null;
      }
      records[i].sync = {
        state: "failed",
        reason: String(reason || "anchor failed"),
        mode: prev.mode === "shielded" ? "shielded" : prev.mode || null,
        anchor_mode: prev.anchor_mode || null,
        shielded:
          prev.shielded === true
            ? true
            : prev.shielded === false
              ? false
              : null,
        receipt_id: prev.receipt_id || null,
        txid: prev.txid || null,
        height: prev.height === undefined ? null : prev.height,
        at: at || new Date().toISOString(),
      };
      persist();
      return records[i];
    }

    function markPending(hash) {
      var i = indexOf(hash);
      if (i === -1 || records[i].sync.state === "anchored") {
        return null;
      }
      records[i].sync = { state: "pending" };
      persist();
      return records[i];
    }

    function get(hash) {
      var i = indexOf(hash);
      return i === -1 ? null : clone(records[i]);
    }

    function list() {
      return clone(records);
    }

    /* The chain head: the last sealed entry, whether or not it has synced. */
    function head() {
      return records.length ? records[records.length - 1].entry.hash : null;
    }

    return {
      adopt: adopt,
      get: get,
      head: head,
      list: list,
      markAnchored: markAnchored,
      markFailed: markFailed,
      markPending: markPending,
      markRefused: markRefused,
      record: record,
      size: function () {
        return records.length;
      },
    };
  }

  return { createJournal: createJournal };
});
