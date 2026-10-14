/* Vickrey sample walk.
 *
 * The demo needs the page to arrive alive. A first-time visitor has no photo,
 * no laptop camera and no signal, so an empty journal is the most likely thing
 * a judge ever sees -- and the least persuasive one.
 *
 * This module is only a *specification* of a plausible walk: which specimen
 * plate, what the model suggested, what the observer decided, and when. It
 * deliberately does not seal anything. The field client runs each step through
 * the real logbook, so every hash is computed and every signature is real. A
 * seeded walk is an ordinary walk that has already happened, not a mock.
 *
 * The middle step is the one worth watching: the model suggests a Common
 * blackbird, the observer corrects it to a European robin, and the correction
 * is sealed inside the record beside the suggestion. That is the whole thesis
 * in one row of the journal.
 *
 * Pure: no DOM, no network, no crypto. It returns data for app.js to seal.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreySampleWalk = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /* Dalston, where this was last walked. Rounded to about a kilometre when it
   * is sealed, so the anchor carries an area and not a position. */
  var WALK_AREA = { lat: 51.5433, lon: -0.0756 };
  var WALK_PLACE = "a walk around Dalston";

  var MODEL = "gemma3:4b";

  var STEPS = [
    {
      plate: "ivy",
      plateName: "Common ivy",
      minutesAgo: 34,
      suggestion: {
        kind: "plant",
        species: "Common ivy",
        confidence: 0.88,
        detail: "Lobed leaves with pale veins, climbing a south-facing wall.",
        model_id: MODEL,
      },
      decision: { action: "confirm" },
    },
    {
      plate: "robin",
      plateName: "European robin",
      minutesAgo: 21,
      suggestion: {
        /* The wrong answer, and a realistic one: both are common urban
         * Turdus-like birds and a small VLM genuinely confuses them. */
        kind: "bird",
        species: "Common blackbird",
        confidence: 0.54,
        detail: "Small dark bird with an orange patch on the breast.",
        model_id: MODEL,
      },
      decision: { action: "correct", species: "European robin", kind: "bird" },
      correction:
        "The model read the orange bib as a blackbird; it is a robin.",
    },
    {
      plate: "hawthorn",
      plateName: "Common hawthorn",
      minutesAgo: 9,
      suggestion: {
        kind: "tree",
        species: "Common hawthorn",
        confidence: 0.79,
        detail: "Deeply lobed leaves, a straight thorn, and red haws.",
        model_id: MODEL,
      },
      decision: { action: "confirm" },
    },
  ];

  /* A stable, plausible observed_at for step i, relative to now. */
  function stepTime(minutesAgo, now) {
    var base = now instanceof Date ? now.getTime() : Date.now();
    return new Date(base - minutesAgo * 60 * 1000).toISOString();
  }

  /* The walk, ready to seal: one entry per step, oldest first so the chain
   * links in the order the observer actually walked it. */
  function sampleWalk(options) {
    options = options || {};
    var now = options.now instanceof Date ? options.now : new Date();
    var location = options.location || WALK_AREA;
    return STEPS.map(function (step) {
      return {
        plate: step.plate,
        plateName: step.plateName,
        suggestion: {
          kind: step.suggestion.kind,
          species: step.suggestion.species,
          confidence: step.suggestion.confidence,
          detail: step.suggestion.detail,
          model_id: step.suggestion.model_id,
          sample: true,
        },
        decision: {
          action: step.decision.action,
          species: step.decision.species,
          kind: step.decision.kind,
        },
        correction: step.correction || null,
        observedAt: stepTime(step.minutesAgo, now),
        location: location,
        modelId: MODEL,
      };
    });
  }

  /* One line per step, for the UI to explain what is about to happen before
   * anyone commits to loading it. */
  function preview() {
    return STEPS.map(function (step, index) {
      var verdict =
        step.decision.action === "correct"
          ? "you correct it to " + step.decision.species
          : "you confirm it";
      return {
        index: index,
        plate: step.plate,
        plateName: step.plateName,
        suggested: step.suggestion.species,
        corrected: step.decision.action === "correct",
        line: "the model suggests " + step.suggestion.species + " — " + verdict,
      };
    });
  }

  return {
    MODEL: MODEL,
    STEPS: STEPS,
    WALK_AREA: WALK_AREA,
    WALK_PLACE: WALK_PLACE,
    preview: preview,
    sampleWalk: sampleWalk,
    stepTime: stepTime,
  };
});
