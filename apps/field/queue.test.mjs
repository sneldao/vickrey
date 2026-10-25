import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const queue = require("./queue.js");

const entries = [
  { hash: "a", payload: { species: "robin" } },
  { hash: "b", payload: { species: "wren" } },
  { hash: "c", payload: { species: "finch" } },
];

test("entries queue in order and report their count", () => {
  const q = queue.createQueue();
  entries.forEach((entry) => q.enqueue(entry));
  assert.equal(q.size(), 3);
  assert.deepEqual(
    q.list().map((entry) => entry.hash),
    ["a", "b", "c"],
  );
});

test("drain sends oldest first and empties the queue on success", async () => {
  const q = queue.createQueue();
  entries.forEach((entry) => q.enqueue(entry));
  const sent = [];
  const result = await q.drain(async (entry) => {
    sent.push(entry.hash);
  });
  assert.deepEqual(sent, ["a", "b", "c"]);
  assert.deepEqual(
    result.sent.map((entry) => entry.hash),
    ["a", "b", "c"],
  );
  assert.equal(result.error, null);
  assert.deepEqual(result.remaining, []);
  assert.equal(q.size(), 0);
});

test("a dropped signal stops the drain and keeps the unsent records", async () => {
  const q = queue.createQueue();
  entries.forEach((entry) => q.enqueue(entry));
  let calls = 0;
  const result = await q.drain(async () => {
    calls += 1;
    if (calls === 2) {
      throw new Error("offline");
    }
  });
  assert.equal(result.error.message, "offline");
  assert.deepEqual(
    result.sent.map((entry) => entry.hash),
    ["a"],
  );
  assert.deepEqual(
    result.remaining.map((entry) => entry.hash),
    ["b", "c"],
  );
  assert.equal(q.size(), 2);
});

test("a later drain resumes the unsent records", async () => {
  const q = queue.createQueue();
  entries.forEach((entry) => q.enqueue(entry));
  let calls = 0;
  await q.drain(async () => {
    calls += 1;
    if (calls === 2) {
      throw new Error("offline");
    }
  });
  const sent = [];
  const result = await q.drain(async (entry) => {
    sent.push(entry.hash);
  });
  assert.deepEqual(sent, ["b", "c"]);
  assert.equal(result.error, null);
  assert.equal(q.size(), 0);
});

test("a store adapter persists the queue across instances", () => {
  const backing = [];
  const store = {
    load: () => backing.slice(),
    save: (items) => {
      backing.length = 0;
      backing.push(...items);
    },
  };
  const first = queue.createQueue({ store });
  first.enqueue(entries[0]);
  first.enqueue(entries[1]);
  const second = queue.createQueue({ store });
  assert.equal(second.size(), 2);
  assert.deepEqual(
    second.list().map((entry) => entry.hash),
    ["a", "b"],
  );
});

test("drain with an only-filter sends due entries and keeps the rest in order", async () => {
  const q = queue.createQueue();
  entries.forEach((entry) => q.enqueue(entry));
  const sent = [];
  const result = await q.drain(
    async (entry) => {
      sent.push(entry.hash);
    },
    (entry) => entry.hash !== "b",
  );
  assert.deepEqual(sent, ["a", "c"]);
  assert.deepEqual(
    result.sent.map((entry) => entry.hash),
    ["a", "c"],
  );
  assert.deepEqual(
    result.remaining.map((entry) => entry.hash),
    ["b"],
  );
  assert.deepEqual(
    q.list().map((entry) => entry.hash),
    ["b"],
    "the held entry stays queued, in order",
  );
});

test("a failure stops at the first due entry and keeps the held ones", async () => {
  const q = queue.createQueue();
  entries.forEach((entry) => q.enqueue(entry));
  const result = await q.drain(
    async (entry) => {
      if (entry.hash === "c") {
        throw new Error("offline");
      }
    },
    (entry) => entry.hash !== "b",
  );
  assert.deepEqual(
    q.list().map((entry) => entry.hash),
    ["b", "c"],
  );
  assert.equal(result.error.message, "offline");
  assert.deepEqual(
    result.sent.map((entry) => entry.hash),
    ["a"],
  );
});

test("replace swaps one queued entry in place and persists", () => {
  const saved = [];
  const q = queue.createQueue({
    store: { load: () => [], save: (items) => saved.push(items.length) },
  });
  entries.forEach((entry) => q.enqueue(entry));
  assert.equal(
    q.replace("b", { hash: "b", payload: { species: "magpie" } }),
    true,
  );
  assert.equal(q.list()[1].payload.species, "magpie");
  assert.equal(q.replace("zzz", { hash: "zzz" }), false);
  assert.equal(q.size(), 3);
});
