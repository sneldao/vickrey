/* Vickrey transactional device storage.
 *
 * IndexedDB holds one structured state record. Every mutation is staged on a
 * copy and committed with one put(), so a journal append cannot survive without
 * its outbox entry, schedule draw and signed head checkpoint.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyStorage = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var DB_NAME = "vickrey-field";
  var DB_VERSION = 1;
  var STORE_NAME = "state";
  var STATE_KEY = "device";
  var SCHEMA = "vickrey.field-state/1";
  var STORAGE_KEYS = [
    "vickrey.device_key",
    "vickrey.flow",
    "vickrey.journal",
    "vickrey.queue",
    "vickrey.anchor_plan",
  ];

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function failure(code, message, cause) {
    var error = new Error(message);
    error.code = code;
    if (cause) {
      error.cause = cause;
    }
    return error;
  }

  function memoryBackend() {
    var value = null;
    return {
      load: async function () {
        return clone(value);
      },
      save: async function (next) {
        value = clone(next);
      },
    };
  }

  function requestResult(request) {
    return new Promise(function (resolve, reject) {
      request.onsuccess = function () {
        resolve(request.result);
      };
      request.onerror = function () {
        reject(request.error || new Error("IndexedDB request failed"));
      };
    });
  }

  function transactionDone(transaction) {
    return new Promise(function (resolve, reject) {
      transaction.oncomplete = function () {
        resolve();
      };
      transaction.onerror = function () {
        reject(transaction.error || new Error("IndexedDB transaction failed"));
      };
      transaction.onabort = function () {
        reject(transaction.error || new Error("IndexedDB transaction aborted"));
      };
    });
  }

  function indexedDBBackend(factory) {
    var idb = factory || root.indexedDB;
    if (!idb) {
      throw failure(
        "STORAGE_UNAVAILABLE",
        "Persistent device storage is unavailable. Vickrey will not start with an empty device.",
      );
    }
    var opening = new Promise(function (resolve, reject) {
      var request = idb.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = function () {
        request.result.createObjectStore(STORE_NAME);
      };
      request.onsuccess = function () {
        resolve(request.result);
      };
      request.onerror = function () {
        reject(request.error || new Error("IndexedDB could not be opened"));
      };
      request.onblocked = function () {
        reject(
          new Error("Another Vickrey tab is blocking the storage upgrade"),
        );
      };
    });
    return {
      load: async function () {
        var db = await opening;
        var transaction = db.transaction(STORE_NAME, "readonly");
        return await requestResult(
          transaction.objectStore(STORE_NAME).get(STATE_KEY),
        );
      },
      save: async function (next) {
        var db = await opening;
        var transaction = db.transaction(STORE_NAME, "readwrite");
        transaction.objectStore(STORE_NAME).put(clone(next), STATE_KEY);
        await transactionDone(transaction);
      },
    };
  }

  function parseStored(text, key, fallback) {
    if (text === null) {
      return clone(fallback);
    }
    try {
      return JSON.parse(text);
    } catch (err) {
      throw failure(
        "STORAGE_CORRUPT",
        'Stored data for "' +
          key +
          '" is not valid JSON. Existing records were not changed.',
        err,
      );
    }
  }

  function legacySnapshot(localStorage) {
    var values = {};
    STORAGE_KEYS.forEach(function (key) {
      var text = null;
      try {
        text = localStorage ? localStorage.getItem(key) : null;
      } catch (err) {
        throw failure(
          "STORAGE_READ",
          'Device storage could not read "' + key + '".',
          err,
        );
      }
      values[key] = typeof text === "string" ? text : null;
    });
    var journal = parseStored(values["vickrey.journal"], "vickrey.journal", []);
    var queue = parseStored(values["vickrey.queue"], "vickrey.queue", []);
    var plan = parseStored(
      values["vickrey.anchor_plan"],
      "vickrey.anchor_plan",
      {},
    );
    if (!Array.isArray(journal) || !Array.isArray(queue)) {
      throw failure("STORAGE_CORRUPT", "The journal and outbox must be lists.");
    }
    if (!plan || typeof plan !== "object" || Array.isArray(plan)) {
      throw failure(
        "STORAGE_CORRUPT",
        "The anchor schedule must be an object.",
      );
    }
    return {
      schema: SCHEMA,
      values: values,
      checkpoint: null,
      corrections: [],
    };
  }

  function validateSnapshot(snapshot) {
    if (
      !snapshot ||
      snapshot.schema !== SCHEMA ||
      !snapshot.values ||
      typeof snapshot.values !== "object" ||
      Array.isArray(snapshot.values)
    ) {
      throw failure(
        "STORAGE_CORRUPT",
        "The device state has an unsupported schema.",
      );
    }
    return snapshot;
  }

  async function openStore(options) {
    options = options || {};
    var backend = options.backend || indexedDBBackend(options.indexedDB);
    var snapshot = await backend.load();
    if (snapshot === null || snapshot === undefined) {
      snapshot = legacySnapshot(options.localStorage || null);
      await backend.save(snapshot);
    }
    return { backend: backend, snapshot: validateSnapshot(snapshot) };
  }

  function valuesOf(snapshot) {
    return snapshot.values;
  }

  function text(snapshot, key) {
    var value = valuesOf(snapshot)[key];
    return typeof value === "string" ? value : null;
  }

  function list(snapshot, key) {
    return parseStored(text(snapshot, key), key, []);
  }

  function object(snapshot, key) {
    return parseStored(text(snapshot, key), key, {});
  }

  function put(snapshot, key, value) {
    valuesOf(snapshot)[key] = value === null ? null : JSON.stringify(value);
  }

  function createRepository(opened, options) {
    options = options || {};
    var backend = opened.backend;
    var current = clone(opened.snapshot);
    var queue = root.VickreyQueue.createQueue({
      store: root.VickreyQueue.memoryStore(),
    });
    var journal = root.VickreyJournal.createJournal({
      store: {
        load: function () {
          return [];
        },
        save: function () {},
      },
    });
    var tail = Promise.resolve();

    function apply(snapshot) {
      queue.replaceAll(list(snapshot, "vickrey.queue"));
      journal.replaceAll(list(snapshot, "vickrey.journal"));
    }

    function transact(mutate) {
      var run = tail.then(async function () {
        var candidate = clone(current);
        var result = await mutate(candidate);
        try {
          await backend.save(candidate);
        } catch (err) {
          apply(current);
          if (err && err.code) {
            throw err;
          }
          throw failure(
            "STORAGE_WRITE",
            "The record could not be saved. Existing records were not changed.",
            err,
          );
        }
        current = candidate;
        apply(current);
        return result;
      });
      tail = run.catch(function () {});
      return run;
    }

    function checkpointFor(snapshot, privateKey) {
      var records = list(snapshot, "vickrey.journal");
      if (!records.length || !privateKey) {
        return snapshot.checkpoint || null;
      }
      return options.checkpoint(
        records[records.length - 1].entry.hash,
        records.length,
        typeof privateKey === "function" ? privateKey() : privateKey,
      );
    }

    apply(current);

    return {
      queue: queue,
      journal: journal,
      initialize: function () {
        return transact(function (candidate) {
          var records = list(candidate, "vickrey.journal");
          var known = {};
          records.forEach(function (record) {
            known[record.entry.hash] = true;
          });
          var queued = list(candidate, "vickrey.queue");
          var added = 0;
          queued.forEach(function (entry) {
            if (!known[entry.hash]) {
              records.push({
                entry: clone(entry),
                thumb: null,
                recorded_at: entry.observed_at || new Date().toISOString(),
                sync: { state: "pending" },
              });
              known[entry.hash] = true;
              added += 1;
            }
          });
          if (added) {
            put(candidate, "vickrey.journal", records);
          }
          return added;
        });
      },
      append: function (entry, extras, anchorOptions) {
        return transact(async function (candidate) {
          var records = list(candidate, "vickrey.journal");
          if (
            records.some(function (record) {
              return record.entry.hash === entry.hash;
            })
          ) {
            throw new Error("This sealed record is already retained.");
          }
          var queued = list(candidate, "vickrey.queue");
          var plan = object(candidate, "vickrey.anchor_plan");
          var at = options.anchorTime
            ? options.anchorTime(entry, plan, anchorOptions)
            : null;
          records.push({
            entry: clone(entry),
            thumb:
              extras && typeof extras.thumb === "string" ? extras.thumb : null,
            recorded_at:
              (extras && extras.recordedAt) || new Date().toISOString(),
            sync: { state: "pending" },
          });
          queued.push(clone(entry));
          put(candidate, "vickrey.journal", records);
          put(candidate, "vickrey.queue", queued);
          put(candidate, "vickrey.anchor_plan", plan);
          candidate.checkpoint = await checkpointFor(
            candidate,
            options.privateKey,
          );
          return at;
        });
      },
      commitMemory: function (plan) {
        return transact(function (candidate) {
          put(candidate, "vickrey.queue", queue.list());
          put(candidate, "vickrey.journal", journal.list());
          if (plan) {
            put(candidate, "vickrey.anchor_plan", plan);
          }
        });
      },
      requeue: function (hash) {
        return transact(function (candidate) {
          var records = list(candidate, "vickrey.journal");
          var record = records.find(function (item) {
            return item.entry && item.entry.hash === hash;
          });
          if (!record) {
            throw new Error("The record being retried is not in this journal.");
          }
          var sync = record.sync || {};
          if (sync.state !== "failed" && sync.state !== "refused") {
            return false;
          }
          var queued = list(candidate, "vickrey.queue");
          if (
            !queued.some(function (entry) {
              return entry.hash === hash;
            })
          ) {
            queued.push(clone(record.entry));
          }
          record.sync = { state: "pending" };
          put(candidate, "vickrey.queue", queued);
          put(candidate, "vickrey.journal", records);
          return true;
        });
      },
      correct: function (supersedes, payload, privateKey) {
        return transact(async function (candidate) {
          var records = list(candidate, "vickrey.journal");
          if (
            !records.some(function (record) {
              return record.entry.hash === supersedes;
            })
          ) {
            throw new Error(
              "The record being corrected is not in this journal.",
            );
          }
          if (
            candidate.corrections.some(function (entry) {
              return entry.payload && entry.payload.supersedes === supersedes;
            })
          ) {
            throw new Error("This record already has a correction.");
          }
          var previous = candidate.corrections.length
            ? candidate.corrections[candidate.corrections.length - 1].hash
            : null;
          var correction = await options.sealCorrection({
            privateKey: privateKey,
            prev: previous,
            supersedes: supersedes,
            payload: payload,
          });
          candidate.corrections.push(correction);
          return correction;
        });
      },
      ensureCheckpoint: function (privateKey) {
        return transact(async function (candidate) {
          if (!candidate.checkpoint) {
            candidate.checkpoint = await checkpointFor(candidate, privateKey);
          }
        });
      },
      getValue: function (key) {
        return text(current, key);
      },
      setValue: function (key, value) {
        return transact(function (candidate) {
          if (value !== null && typeof value !== "string") {
            throw new Error("Stored value for " + key + " must be text");
          }
          candidate.values[key] = value;
        });
      },
      anchorPlan: function () {
        return object(current, "vickrey.anchor_plan");
      },
      checkpoint: function () {
        return clone(current.checkpoint);
      },
      corrections: function () {
        return clone(current.corrections);
      },
      backupStorage: function () {
        return {
          getItem: function (key) {
            return text(current, key);
          },
          backupMetadata: function () {
            return {
              checkpoint: clone(current.checkpoint),
              corrections: clone(current.corrections),
            };
          },
          replaceAll: async function (values) {
            await transact(function (candidate) {
              STORAGE_KEYS.forEach(function (key) {
                if (!Object.prototype.hasOwnProperty.call(values, key)) {
                  throw new Error("Restored state is missing " + key);
                }
                if (values[key] !== null && typeof values[key] !== "string") {
                  throw new Error("Restored value for " + key + " is not text");
                }
                candidate.values[key] = values[key];
              });
              candidate.checkpoint = Object.prototype.hasOwnProperty.call(
                values,
                "checkpoint",
              )
                ? clone(values.checkpoint)
                : null;
              candidate.corrections = Object.prototype.hasOwnProperty.call(
                values,
                "corrections",
              )
                ? clone(values.corrections)
                : [];
            });
          },
        };
      },
      clearWalk: function () {
        return transact(function (candidate) {
          put(candidate, "vickrey.journal", []);
          put(candidate, "vickrey.queue", []);
          put(candidate, "vickrey.anchor_plan", {});
          put(candidate, "vickrey.flow", null);
          candidate.checkpoint = null;
          candidate.corrections = [];
        });
      },
    };
  }

  return {
    DB_NAME: DB_NAME,
    SCHEMA: SCHEMA,
    STORAGE_KEYS: STORAGE_KEYS,
    createRepository: createRepository,
    indexedDBBackend: indexedDBBackend,
    memoryBackend: memoryBackend,
    openStore: openStore,
  };
});
