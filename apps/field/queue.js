/* Vickrey offline queue.
 *
 * A field device seals observations with no signal, then drains them once it is
 * back in range. The queue keeps order, stops at the first failure (so a dropped
 * signal never loses a record), and can persist through a small store adapter.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyQueue = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  function memoryStore() {
    var items = [];
    return {
      load: function () {
        return items.slice();
      },
      save: function (next) {
        items = next.slice();
      },
    };
  }

  function storageError(code, action, key, cause) {
    var error = new Error(
      "Device storage could not be " +
        action +
        ' for "' +
        key +
        '". Existing records were not changed.',
    );
    error.code = code;
    if (cause) {
      error.cause = cause;
    }
    return error;
  }

  function localStore(key) {
    return {
      load: function () {
        var storage;
        try {
          storage = root.localStorage;
          if (!storage) {
            throw new Error("localStorage unavailable");
          }
          var raw = storage.getItem(key);
          return raw ? JSON.parse(raw) : [];
        } catch (err) {
          if (err && err.code === "STORAGE_READ") {
            throw err;
          }
          throw storageError("STORAGE_CORRUPT", "read", key, err);
        }
      },
      save: function (items) {
        var storage;
        try {
          storage = root.localStorage;
          if (!storage) {
            throw new Error("localStorage unavailable");
          }
          storage.setItem(key, JSON.stringify(items));
        } catch (err) {
          throw storageError("STORAGE_WRITE", "saved", key, err);
        }
      },
    };
  }

  function createQueue(options) {
    options = options || {};
    var store =
      options.store || (options.key ? localStore(options.key) : memoryStore());
    var items = store.load() || [];

    function persist() {
      store.save(items);
    }

    function list() {
      return items.slice();
    }

    function size() {
      return items.length;
    }

    function replaceAll(next) {
      if (!Array.isArray(next)) {
        throw new Error("queue storage is not a list");
      }
      items = next.slice();
    }

    function enqueue(entry) {
      items.push(entry);
      persist();
      return entry;
    }

    /* Swap the queued copy of one entry (matched by hash). The demo uses this
     * to edit a queued copy, and to put the sealed copy back. */
    function replace(hash, entry) {
      for (var i = 0; i < items.length; i++) {
        if (items[i].hash === hash) {
          items[i] = entry;
          persist();
          return true;
        }
      }
      return false;
    }

    /* Try to send every queued entry, oldest first. Stop at the first failure
     * and keep the rest so nothing is dropped. `only` (optional) marks whose
     * turn it is: held entries are skipped and kept in order, so the jittered
     * anchor schedule can hold one back without disturbing the rest. */
    async function drain(send, only) {
      var sent = [];
      var error = null;
      var i = 0;
      while (i < items.length) {
        if (only && !only(items[i])) {
          i += 1;
          continue;
        }
        try {
          await send(items[i]);
        } catch (err) {
          error = err;
          break;
        }
        sent.push(items[i]);
        items.splice(i, 1);
      }
      persist();
      return { sent: sent, remaining: items.slice(), error: error };
    }

    return {
      enqueue: enqueue,
      list: list,
      size: size,
      drain: drain,
      replace: replace,
      replaceAll: replaceAll,
    };
  }

  return {
    createQueue: createQueue,
    localStore: localStore,
    memoryStore: memoryStore,
  };
});
