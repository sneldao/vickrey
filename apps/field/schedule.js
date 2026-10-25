/* Vickrey anchor schedule.
 *
 * The timing-leak mitigation for shielded anchoring: a shielded transaction
 * appearing seconds after an observation in the same region is a correlation.
 * Anchors therefore never leave the device at capture time or at "back in
 * range"; each commitment is assigned a randomized anchor time:
 *
 *     t = max(observed_at + minDelayMs, plannedAt) + U(0, jitterMs)
 *
 * - minDelayMs — the anchor can never sit closer than this to the capture, so
 *   "sealed and immediately anchored" is impossible by construction.
 * - plannedAt — the moment the schedule first sees the entry. An entry that
 *   sat in the outbox through a dead zone is spread from *now* across the
 *   jitter window, so reconnection never fires a burst.
 * - jitterMs — the batch window. Each entry draws its own offset, so a batch
 *   of anchors is spread across the window instead of leaving together.
 *
 * The draw happens once per entry and is kept in the `times` map the caller
 * passes in (the app persists that map locally), so a reload does not re-roll
 * the dice. Nothing here touches the network or the DOM: given the same
 * entries, times, clock, and rng, the plan is identical.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreySchedule = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  /* Production defaults. The demo overrides them to seconds via the query
   * string; docs/PRIVACY.md quotes these numbers as the threat model. */
  var DEFAULT_MIN_DELAY_MS = 30 * 60 * 1000; // 30 minutes
  var DEFAULT_JITTER_MS = 20 * 60 * 1000; // 20 minutes

  function toMs(value, fallback) {
    var n = Number(value);
    return isFinite(n) && n >= 0 ? n : fallback;
  }

  function normalizeOptions(opts) {
    opts = opts || {};
    return {
      minDelayMs: toMs(opts.minDelayMs, DEFAULT_MIN_DELAY_MS),
      jitterMs: toMs(opts.jitterMs, DEFAULT_JITTER_MS),
    };
  }

  function observedAt(entry, now) {
    var at = Date.parse((entry && entry.observed_at) || "");
    return isFinite(at) ? at : now;
  }

  /* Draw the anchor time for one entry. A time already in `times` is kept:
   * the jitter is drawn once per commitment, never re-rolled. */
  function anchorTime(entry, times, now, opts, rng) {
    times = times || {};
    var hash = entry && entry.hash;
    if (typeof hash === "string" && isFinite(times[hash])) {
      return times[hash];
    }
    var config = normalizeOptions(opts);
    var draw = typeof rng === "function" ? rng : Math.random;
    var at =
      Math.max(observedAt(entry, now) + config.minDelayMs, now) +
      Math.floor(draw() * config.jitterMs);
    if (typeof hash === "string") {
      times[hash] = at;
    }
    return at;
  }

  /* Fill in any missing draws, then split the queue into what is due now and
   * what waits for its window. `send` keeps queue order (oldest first);
   * `nextCheckAt` is when the next held entry comes due, or null when nothing
   * is held. `times` is mutated so the caller can persist the draws. */
  function planAnchors(entries, times, now, opts, rng) {
    times = times || {};
    var send = [];
    var hold = [];
    var nextCheckAt = null;
    (entries || []).forEach(function (entry) {
      var at = anchorTime(entry, times, now, opts, rng);
      if (at <= now) {
        send.push(entry);
      } else {
        hold.push(entry);
        if (nextCheckAt === null || at < nextCheckAt) {
          nextCheckAt = at;
        }
      }
    });
    return { send: send, hold: hold, nextCheckAt: nextCheckAt };
  }

  return {
    DEFAULT_JITTER_MS: DEFAULT_JITTER_MS,
    DEFAULT_MIN_DELAY_MS: DEFAULT_MIN_DELAY_MS,
    anchorTime: anchorTime,
    normalizeOptions: normalizeOptions,
    planAnchors: planAnchors,
  };
});
