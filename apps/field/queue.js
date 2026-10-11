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

  function localStore(key) {
    return {
      load: function () {
        try {
          var raw = root.localStorage.getItem(key);
          return raw ? JSON.parse(raw) : [];
        } catch (err) {
          return [];
        }
      },
      save: function (items) {
        try {
          root.localStorage.setItem(key, JSON.stringify(items));
        } catch (err) {
          /* storage full or unavailable: keep the in-memory copy */
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
     * and keep the rest so nothing is dropped. */
    async function drain(send) {
      var sent = [];
      var error = null;
      while (items.length) {
        try {
          await send(items[0]);
        } catch (err) {
          error = err;
          break;
        }
        sent.push(items.shift());
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
    };
  }

  return {
    createQueue: createQueue,
    localStore: localStore,
    memoryStore: memoryStore,
  };
});
