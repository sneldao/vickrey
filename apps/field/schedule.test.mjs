import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const schedule = require("./schedule.js");

const MIN = 60 * 1000;
const opts = { minDelayMs: 30 * MIN, jitterMs: 20 * MIN };
const t0 = Date.parse("2026-10-27T09:00:00Z");

/* An rng that replays a fixed sequence of draws. */
function seq(...values) {
  let i = 0;
  return () => values[i++ % values.length];
}

test("an anchor is never closer than the min delay to the capture", () => {
  const entry = { hash: "a", observed_at: new Date(t0).toISOString() };
  const times = {};
  const at = schedule.anchorTime(entry, times, t0, opts, seq(0));
  assert.equal(at, t0 + 30 * MIN);
  assert.ok(at - t0 >= 30 * MIN);
});

test("the jitter is drawn across the batch window", () => {
  const entry = { hash: "a", observed_at: new Date(t0).toISOString() };
  const at = schedule.anchorTime(entry, {}, t0, opts, seq(0.5));
  assert.equal(at, t0 + 30 * MIN + 10 * MIN);
});

test("the jitter is drawn once per entry and never re-rolled", () => {
  const entry = { hash: "a", observed_at: new Date(t0).toISOString() };
  const times = {};
  const first = schedule.anchorTime(entry, times, t0, opts, seq(0.25));
  const again = schedule.anchorTime(entry, times, t0, opts, seq(0.99));
  assert.equal(first, again);
  assert.equal(times.a, first);
});

test("an entry discovered late spreads from now — no burst on reconnection", () => {
  const fiveHoursAgo = new Date(t0 - 5 * 60 * MIN).toISOString();
  const entries = [
    { hash: "a", observed_at: fiveHoursAgo },
    { hash: "b", observed_at: fiveHoursAgo },
    { hash: "c", observed_at: fiveHoursAgo },
  ];
  const times = {};
  const plan = schedule.planAnchors(
    entries,
    times,
    t0,
    opts,
    seq(0.1, 0.5, 0.9),
  );
  assert.equal(
    plan.send.length,
    0,
    "nothing leaves at the moment of reconnection",
  );
  assert.equal(plan.hold.length, 3);
  const drawn = entries.map((entry) => times[entry.hash]);
  drawn.forEach((at) => {
    assert.ok(at > t0, "each anchor is after the planning moment");
    assert.ok(
      at <= t0 + 20 * MIN,
      "each anchor lands inside the jitter window",
    );
  });
  assert.equal(new Set(drawn).size, 3, "three entries, three different times");
});

test("the batch sends what is due and holds the rest, oldest first", () => {
  const entries = [
    { hash: "c", observed_at: new Date(t0 - 40 * MIN).toISOString() },
    { hash: "a", observed_at: new Date(t0 - 3 * 60 * MIN).toISOString() },
    { hash: "b", observed_at: new Date(t0 - 2 * 60 * MIN).toISOString() },
  ];
  const times = { a: t0 - 10 * MIN, b: t0 - 5 * MIN, c: t0 + 30 * MIN };
  const plan = schedule.planAnchors(entries, times, t0, opts);
  assert.deepEqual(
    plan.send.map((entry) => entry.hash),
    ["a", "b"],
    "due entries go in queue order",
  );
  assert.deepEqual(
    plan.hold.map((entry) => entry.hash),
    ["c"],
  );
  assert.equal(plan.nextCheckAt, t0 + 30 * MIN);
});

test("nextCheckAt is null when nothing is held", () => {
  const entries = [{ hash: "a", observed_at: new Date(t0).toISOString() }];
  const plan = schedule.planAnchors(entries, { a: t0 - 1 }, t0, opts);
  assert.equal(plan.hold.length, 0);
  assert.equal(plan.nextCheckAt, null);
});

test("zero jitter is deterministic at the min delay", () => {
  const entry = { hash: "a", observed_at: new Date(t0).toISOString() };
  const at = schedule.anchorTime(
    entry,
    {},
    t0,
    { minDelayMs: 30 * MIN, jitterMs: 0 },
    seq(0.99),
  );
  assert.equal(at, t0 + 30 * MIN);
});

test("an entry with no observed_at plans from the planning moment", () => {
  const at = schedule.anchorTime({ hash: "a" }, {}, t0, opts, seq(0));
  assert.equal(at, t0 + 30 * MIN);
});

test("a full window: nothing goes early, everything goes by its draw", () => {
  const entries = [
    { hash: "a", observed_at: new Date(t0 - 60 * MIN).toISOString() },
    { hash: "b", observed_at: new Date(t0 - 60 * MIN).toISOString() },
  ];
  const times = {};
  const first = schedule.planAnchors(entries, times, t0, {
    minDelayMs: 5 * MIN,
    jitterMs: 10 * MIN,
  });
  assert.equal(first.send.length, 0);
  // After the window passes, both are due in one batch, queue order kept.
  const later = schedule.planAnchors(entries, times, t0 + 60 * MIN, {
    minDelayMs: 5 * MIN,
    jitterMs: 10 * MIN,
  });
  assert.deepEqual(
    later.send.map((entry) => entry.hash),
    ["a", "b"],
  );
  assert.equal(later.nextCheckAt, null);
});

test("normalizeOptions clamps nonsense to the documented defaults", () => {
  assert.deepEqual(schedule.normalizeOptions(), {
    minDelayMs: schedule.DEFAULT_MIN_DELAY_MS,
    jitterMs: schedule.DEFAULT_JITTER_MS,
  });
  assert.deepEqual(
    schedule.normalizeOptions({ minDelayMs: -5, jitterMs: "x" }),
    {
      minDelayMs: schedule.DEFAULT_MIN_DELAY_MS,
      jitterMs: schedule.DEFAULT_JITTER_MS,
    },
  );
  assert.deepEqual(
    schedule.normalizeOptions({ minDelayMs: "1000", jitterMs: 250 }),
    {
      minDelayMs: 1000,
      jitterMs: 250,
    },
  );
});
