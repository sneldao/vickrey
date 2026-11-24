/* Vickrey research export — a fail-closed Darwin Core occurrence CSV. */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyExport = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var SCHEMA = "vickrey.research-export/1";
  var CHECKPOINT_SCHEMA = "vickrey.journal-checkpoint/1";
  var CORRECTION_SCHEMA = "vickrey.correction/1";
  var HASH_RE = /^[0-9a-f]{64}$/;
  var BASE64URL_RE = /^[A-Za-z0-9_-]+={0,2}$/;
  var ISO_RE =
    /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?)?$/;

  var DARWIN_CORE_TERMS = [
    "occurrenceID",
    "basisOfRecord",
    "eventDate",
    "decimalLatitude",
    "decimalLongitude",
    "coordinateUncertaintyInMeters",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "scientificName",
    "vernacularName",
    "recordedBy",
    "occurrenceRemarks",
    "associatedMedia",
    "datasetID",
    "institutionCode",
    "datasetName",
    "informationWithheld",
    "dataGeneralizations",
    "identificationQualifier",
    "identificationVerificationStatus",
    "georeferenceRemarks",
    "dcterms:provenance",
  ];
  var PROVENANCE_COLUMNS = [
    "vickrey:commitment",
    "vickrey:devicePublicKey",
    "vickrey:signature",
    "vickrey:journalHead",
    "vickrey:journalCount",
    "vickrey:journalVerificationStatus",
    "vickrey:checkpointVerificationStatus",
    "vickrey:correctionsVerificationStatus",
    "vickrey:correctionReferences",
    "vickrey:verificationSources",
    "vickrey:disclosureVerificationStatus",
    "vickrey:disclosureVerificationSource",
  ];
  var COLUMNS = DARWIN_CORE_TERMS.concat(PROVENANCE_COLUMNS);
  var TAXONOMY_FIELDS = [
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "scientificName",
    "vernacularName",
  ];
  var PAYLOAD_TEXT_FIELDS = [
    "recordedBy",
    "occurrenceRemarks",
    "informationWithheld",
    "dataGeneralizations",
    "identificationQualifier",
    "identificationVerificationStatus",
    "georeferenceRemarks",
    "datasetID",
    "institutionCode",
    "datasetName",
  ];
  var DATASET_FIELDS = ["datasetID", "institutionCode", "datasetName"];
  var BASIS_OF_RECORD = {
    PreservedSpecimen: true,
    FossilSpecimen: true,
    LivingSpecimen: true,
    MaterialSample: true,
    Event: true,
    HumanObservation: true,
    MachineObservation: true,
    Taxon: true,
    Occurrence: true,
  };

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function hasOwn(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  function fail(message) {
    throw new Error("invalid research export: " + message);
  }

  function isWellFormed(text) {
    for (var i = 0; i < text.length; i++) {
      var code = text.charCodeAt(i);
      if (code >= 0xd800 && code <= 0xdbff) {
        if (i + 1 >= text.length) {
          return false;
        }
        var next = text.charCodeAt(i + 1);
        if (next < 0xdc00 || next > 0xdfff) {
          return false;
        }
        i++;
      } else if (code >= 0xdc00 && code <= 0xdfff) {
        return false;
      }
    }
    return true;
  }

  function textValue(value, label, allowEmpty) {
    if (typeof value !== "string") {
      fail(label + " must be text");
    }
    if (!isWellFormed(value)) {
      fail(label + " is not valid Unicode");
    }
    if (!allowEmpty && !value) {
      fail(label + " must not be empty");
    }
    return value;
  }

  function optionalText(obj, key, label) {
    if (!hasOwn(obj, key) || obj[key] === undefined || obj[key] === null) {
      return "";
    }
    return textValue(obj[key], label, true);
  }

  function trustModule() {
    if (root.VickreyTrust) {
      return root.VickreyTrust;
    }
    if (typeof module === "object" && module.exports) {
      return require("./trust.js");
    }
    throw new Error("VickreyTrust is not loaded");
  }

  function disclosureModule() {
    if (root.VickreyDisclosure) {
      return root.VickreyDisclosure;
    }
    if (typeof module === "object" && module.exports) {
      return require("./disclosure.js");
    }
    throw new Error("VickreyDisclosure is not loaded");
  }

  function validDate(text, label) {
    textValue(text, label, false);
    var match = ISO_RE.exec(text);
    if (!match || !Number.isFinite(Date.parse(text))) {
      fail(label + " must be an ISO 8601 date or date-time");
    }
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    var leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    var days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (month < 1 || month > 12 || day < 1 || day > days[month - 1]) {
      fail(label + " is not a real calendar date");
    }
    if (match[4] !== undefined) {
      var hour = Number(match[4]);
      var minute = Number(match[5]);
      var second = match[6] === undefined ? 0 : Number(match[6]);
      if (hour > 23 || minute > 59 || second > 59) {
        fail(label + " has an invalid time");
      }
      var zone = match[8];
      if (zone && zone !== "Z") {
        var zoneHour = Number(zone.slice(1, 3));
        var zoneMinute = Number(zone.slice(4, 6));
        if (zoneHour > 23 || zoneMinute > 59) {
          fail(label + " has an invalid timezone offset");
        }
      }
    }
    return text;
  }

  function validCoordinate(value, label, minimum, maximum) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      fail(label + " must be a finite number");
    }
    if (value < minimum || value > maximum) {
      fail(label + " is outside its valid range");
    }
    return value;
  }

  function checkLocation(location, label) {
    if (location === undefined || location === null) {
      return null;
    }
    if (!isPlainObject(location)) {
      fail(label + " must be an object or null");
    }
    validCoordinate(location.lat, label + ".lat", -90, 90);
    validCoordinate(location.lon, label + ".lon", -180, 180);
    return { lat: location.lat, lon: location.lon };
  }

  function checkPayloadCoordinates(payload, label) {
    var hasLat =
      hasOwn(payload, "decimalLatitude") &&
      payload.decimalLatitude !== undefined &&
      payload.decimalLatitude !== null;
    var hasLon =
      hasOwn(payload, "decimalLongitude") &&
      payload.decimalLongitude !== undefined &&
      payload.decimalLongitude !== null;
    if (hasLat !== hasLon) {
      fail(label + " must provide both decimalLatitude and decimalLongitude");
    }
    if (!hasLat) {
      return null;
    }
    return {
      lat: validCoordinate(
        payload.decimalLatitude,
        label + ".decimalLatitude",
        -90,
        90,
      ),
      lon: validCoordinate(
        payload.decimalLongitude,
        label + ".decimalLongitude",
        -180,
        180,
      ),
    };
  }

  function checkUncertainty(payload, label) {
    if (
      !hasOwn(payload, "coordinateUncertaintyInMeters") ||
      payload.coordinateUncertaintyInMeters === undefined ||
      payload.coordinateUncertaintyInMeters === null
    ) {
      return null;
    }
    var value = payload.coordinateUncertaintyInMeters;
    if (!Number.isSafeInteger(value) || value <= 0) {
      fail(
        label +
          ".coordinateUncertaintyInMeters must be a positive safe integer",
      );
    }
    return value;
  }

  function checkBasis(value, label) {
    if (value && !hasOwn(BASIS_OF_RECORD, value)) {
      fail(label + " is not a supported Darwin Core basisOfRecord");
    }
  }

  function checkMedia(value, label) {
    if (value === undefined || value === null) {
      return;
    }
    if (typeof value === "string") {
      textValue(value, label, true);
      return;
    }
    if (!Array.isArray(value)) {
      fail(label + " must be text or an array of text");
    }
    value.forEach(function (item, index) {
      textValue(item, label + "[" + index + "]", true);
    });
  }

  function checkEntry(entry, label, correction, trust) {
    if (!isPlainObject(entry)) {
      fail(label + " is not an object");
    }
    if (typeof entry.hash !== "string" || !HASH_RE.test(entry.hash)) {
      fail(label + ".hash is not a 64-hex commitment");
    }
    if (
      typeof entry.signature !== "string" ||
      !BASE64URL_RE.test(entry.signature)
    ) {
      fail(label + ".signature is not base64url text");
    }
    try {
      if (trust.base64urlToBytes(entry.signature).length !== 64) {
        fail(label + ".signature is not a 64-byte Ed25519 signature");
      }
    } catch (err) {
      fail(label + ".signature is not valid base64url");
    }
    validDate(entry.observed_at, label + ".observed_at");
    if (
      entry.prev !== null &&
      (typeof entry.prev !== "string" || !HASH_RE.test(entry.prev))
    ) {
      fail(label + ".prev is not null or a 64-hex link");
    }
    if (
      entry.model_id !== undefined &&
      entry.model_id !== null &&
      typeof entry.model_id !== "string"
    ) {
      fail(label + ".model_id must be text or null");
    }
    if (correction && entry.model_id !== CORRECTION_SCHEMA) {
      fail(label + " is not a Vickrey correction");
    }
    if (!correction && entry.model_id === CORRECTION_SCHEMA) {
      fail(label + " is a correction, not a journal observation");
    }
    if (!isPlainObject(entry.payload)) {
      fail(label + ".payload is not an object");
    }
    var location = checkLocation(entry.location, label + ".location");
    var payloadCoordinates = checkPayloadCoordinates(
      entry.payload,
      label + ".payload",
    );
    if (
      location &&
      payloadCoordinates &&
      (location.lat !== payloadCoordinates.lat ||
        location.lon !== payloadCoordinates.lon)
    ) {
      fail(label + " has ambiguous coordinate sources");
    }
    checkUncertainty(entry.payload, label + ".payload");
    if (
      entry.payload.taxonomy !== undefined &&
      entry.payload.taxonomy !== null
    ) {
      if (!isPlainObject(entry.payload.taxonomy)) {
        fail(label + ".payload.taxonomy is not an object");
      }
      TAXONOMY_FIELDS.forEach(function (field) {
        optionalText(
          entry.payload.taxonomy,
          field,
          label + ".payload.taxonomy." + field,
        );
      });
    }
    TAXONOMY_FIELDS.concat(PAYLOAD_TEXT_FIELDS).forEach(function (field) {
      optionalText(entry.payload, field, label + ".payload." + field);
    });
    optionalText(
      entry.payload,
      "basisOfRecord",
      label + ".payload.basisOfRecord",
    );
    checkBasis(entry.payload.basisOfRecord, label + ".payload.basisOfRecord");
    checkMedia(
      entry.payload.associatedMedia,
      label + ".payload.associatedMedia",
    );
  }

  function normalizePolicy(policy) {
    if (policy === undefined || policy === null) {
      return {
        allow: false,
        mode: null,
        decimals: null,
        uncertaintyMeters: null,
      };
    }
    if (!isPlainObject(policy)) {
      fail("locationPolicy must be an object");
    }
    Object.keys(policy).forEach(function (key) {
      if (
        ["allow", "mode", "decimals", "uncertaintyMeters"].indexOf(key) === -1
      ) {
        fail("locationPolicy has an unknown field: " + key);
      }
    });
    if (typeof policy.allow !== "boolean") {
      fail("locationPolicy.allow must be a boolean");
    }
    var normalized = {
      allow: policy.allow,
      mode: null,
      decimals: null,
      uncertaintyMeters: null,
    };
    if (
      policy.uncertaintyMeters !== undefined &&
      policy.uncertaintyMeters !== null
    ) {
      if (
        !Number.isSafeInteger(policy.uncertaintyMeters) ||
        policy.uncertaintyMeters <= 0
      ) {
        fail(
          "locationPolicy.uncertaintyMeters must be a positive safe integer",
        );
      }
      normalized.uncertaintyMeters = policy.uncertaintyMeters;
    }
    if (!policy.allow) {
      return normalized;
    }
    if (policy.mode !== "coarse" && policy.mode !== "exact") {
      fail(
        'locationPolicy.mode must be "coarse" or "exact" when allow is true',
      );
    }
    normalized.mode = policy.mode;
    if (policy.mode === "coarse") {
      normalized.decimals = policy.decimals === undefined ? 2 : policy.decimals;
      if (
        !Number.isInteger(normalized.decimals) ||
        normalized.decimals < 0 ||
        normalized.decimals > 3
      ) {
        fail("coarse locationPolicy.decimals must be an integer from 0 to 3");
      }
    } else if (policy.decimals !== undefined && policy.decimals !== null) {
      fail("exact locationPolicy must not specify decimals");
    }
    return normalized;
  }

  function normalizeOptions(options) {
    if (options === undefined || options === null) {
      options = {};
    }
    if (!isPlainObject(options)) {
      fail("options must be an object");
    }
    if (options.bom !== undefined && typeof options.bom !== "boolean") {
      fail("options.bom must be a boolean");
    }
    var metadata =
      options.metadata === undefined || options.metadata === null
        ? {}
        : options.metadata;
    if (!isPlainObject(metadata)) {
      fail("options.metadata must be an object");
    }
    var dataset = {};
    DATASET_FIELDS.forEach(function (field) {
      dataset[field] = hasOwn(options, field)
        ? optionalText(options, field, "options." + field)
        : optionalText(metadata, field, "options.metadata." + field);
    });
    var basis = hasOwn(options, "basisOfRecord")
      ? optionalText(options, "basisOfRecord", "options.basisOfRecord")
      : "";
    checkBasis(basis, "options.basisOfRecord");
    return {
      bom: options.bom === true,
      dataset: dataset,
      defaultBasis: basis || "HumanObservation",
      locationPolicy: normalizePolicy(options.locationPolicy),
    };
  }

  async function importDeviceKey(publicKeyText, trust) {
    textValue(publicKeyText, "publicKeyText", false);
    if (!BASE64URL_RE.test(publicKeyText)) {
      fail("publicKeyText is not base64url text");
    }
    try {
      return await trust.importPublicKey(publicKeyText);
    } catch (err) {
      fail("publicKeyText cannot be imported as an Ed25519 public key");
    }
  }

  async function verifyJournal(entries, publicKey, trust) {
    try {
      var verdict = await trust.verifyChain(entries, publicKey);
      if (!verdict.ok) {
        fail(
          "journal chain does not verify (" +
            verdict.reason +
            " at " +
            verdict.brokenAt +
            ")",
        );
      }
    } catch (err) {
      if (
        err &&
        err.message &&
        err.message.indexOf("invalid research export:") === 0
      ) {
        throw err;
      }
      fail("journal signatures could not be verified");
    }
  }

  async function verifyCheckpoint(checkpoint, head, count, publicKey, trust) {
    if (!isPlainObject(checkpoint) || checkpoint.schema !== CHECKPOINT_SCHEMA) {
      fail("checkpoint schema is missing or invalid");
    }
    if (checkpoint.head !== head || checkpoint.count !== count) {
      fail("checkpoint does not cover the supplied journal head and count");
    }
    if (typeof checkpoint.hash !== "string" || !HASH_RE.test(checkpoint.hash)) {
      fail("checkpoint.hash is not a 64-hex commitment");
    }
    if (
      typeof checkpoint.signature !== "string" ||
      !BASE64URL_RE.test(checkpoint.signature)
    ) {
      fail("checkpoint.signature is not base64url text");
    }
    try {
      if (trust.base64urlToBytes(checkpoint.signature).length !== 64) {
        fail("checkpoint.signature is not a 64-byte Ed25519 signature");
      }
    } catch (err) {
      fail("checkpoint.signature is not valid base64url");
    }
    var expected = await trust.commitment({
      schema: CHECKPOINT_SCHEMA,
      head: head,
      count: count,
    });
    if (expected !== checkpoint.hash) {
      fail("checkpoint commitment does not recompute");
    }
    var valid = await trust.verifyCommitment(
      publicKey,
      checkpoint.hash,
      checkpoint.signature,
    );
    if (!valid) {
      fail("checkpoint signature does not verify under the device key");
    }
  }

  async function verifyCorrections(corrections, entries, publicKey, trust) {
    if (!Array.isArray(corrections)) {
      fail("corrections must be an array");
    }
    var known = {};
    entries.forEach(function (entry) {
      known[entry.hash] = true;
    });
    var superseded = {};
    var seen = {};
    corrections.forEach(function (entry, index) {
      var label = "corrections[" + index + "]";
      checkEntry(entry, label, true, trust);
      if (seen[entry.hash] || known[entry.hash]) {
        fail(label + " duplicates a commitment");
      }
      seen[entry.hash] = true;
      if (
        entry.payload.schema !== CORRECTION_SCHEMA ||
        !HASH_RE.test(entry.payload.supersedes || "")
      ) {
        fail(label + " has an invalid correction payload");
      }
      if (
        !known[entry.payload.supersedes] ||
        superseded[entry.payload.supersedes]
      ) {
        fail(
          label + " references an unknown or already corrected journal entry",
        );
      }
      if (
        typeof entry.payload.reason !== "string" ||
        !hasOwn(entry.payload, "correction")
      ) {
        fail(label + " needs a reason and correction payload");
      }
      textValue(entry.payload.reason, label + ".payload.reason", true);
      superseded[entry.payload.supersedes] = true;
    });
    if (corrections.length && corrections[0].prev !== null) {
      fail("corrections chain does not start at null");
    }
    try {
      var verdict = await trust.verifyChain(corrections, publicKey);
      if (!verdict.ok) {
        fail(
          "corrections chain does not verify (" +
            verdict.reason +
            " at " +
            verdict.brokenAt +
            ")",
        );
      }
    } catch (err) {
      if (
        err &&
        err.message &&
        err.message.indexOf("invalid research export:") === 0
      ) {
        throw err;
      }
      fail("correction signatures could not be verified");
    }
  }

  async function verifyDisclosure(bundle, publicKeyText, entries) {
    if (!isPlainObject(bundle)) {
      fail("disclosure must be an object");
    }
    if (bundle.public_key !== publicKeyText) {
      fail("disclosure public key does not match the supplied device key");
    }
    if (
      bundle.verification !== undefined &&
      bundle.verification !== null &&
      !isPlainObject(bundle.verification)
    ) {
      fail("disclosure.verification must be an object");
    }
    var source = "";
    if (
      bundle.verification &&
      hasOwn(bundle.verification, "verification_source") &&
      bundle.verification.verification_source !== undefined &&
      bundle.verification.verification_source !== null
    ) {
      source = textValue(
        bundle.verification.verification_source,
        "disclosure.verification.verification_source",
        true,
      );
    }
    var matched = null;
    try {
      await disclosureModule().verifyDisclosure(bundle);
    } catch (err) {
      fail("disclosure does not verify locally (" + err.message + ")");
    }
    entries.forEach(function (entry) {
      if (bundle.entry && entry.hash === bundle.entry.hash) {
        matched = entry.hash;
      }
    });
    if (!matched) {
      fail("disclosure entry is not in the supplied journal");
    }
    return {
      hash: matched,
      historicalSource: source,
    };
  }

  function coordinateSource(entry) {
    var explicit = checkPayloadCoordinates(entry.payload, "payload");
    if (explicit) {
      return explicit;
    }
    return checkLocation(entry.location, "entry.location");
  }

  function mediaText(value) {
    if (value === undefined || value === null) {
      return "";
    }
    return Array.isArray(value) ? value.join(" | ") : value;
  }

  function decimalText(value) {
    var text = String(value);
    if (!/[eE]/.test(text)) {
      return text;
    }
    var negative = text.charAt(0) === "-";
    if (negative) {
      text = text.slice(1);
    }
    var parts = text.toLowerCase().split("e");
    var exponent = Number(parts[1]);
    var mantissa = parts[0];
    var point = mantissa.indexOf(".");
    var digits = mantissa.replace(".", "");
    point = (point === -1 ? digits.length : point) + exponent;
    var out;
    if (point <= 0) {
      out = "0." + new Array(1 - point).join("0") + digits;
    } else if (point >= digits.length) {
      out = digits + new Array(point - digits.length + 1).join("0");
    } else {
      out = digits.slice(0, point) + "." + digits.slice(point);
    }
    return negative ? "-" + out : out;
  }

  function appendNote(base, note) {
    return base ? base + " | " + note : note;
  }

  function payloadField(payload, taxonomy, field) {
    if (hasOwn(payload, field)) {
      return optionalText(payload, field, "payload." + field);
    }
    return optionalText(taxonomy, field, "payload.taxonomy." + field);
  }

  function datasetField(payload, dataset, field) {
    var supplied = optionalText(payload, field, "payload." + field);
    return supplied || dataset[field];
  }

  function uncertaintyFor(payload, policy) {
    var supplied = checkUncertainty(payload, "payload");
    if (policy.mode === "exact") {
      if (policy.uncertaintyMeters !== null) {
        return Math.max(policy.uncertaintyMeters, supplied || 0);
      }
      return supplied || "";
    }
    var minimum = Math.ceil(111320 / Math.pow(10, policy.decimals));
    return Math.max(minimum, supplied || 0, policy.uncertaintyMeters || 0);
  }

  function buildRow(record, context) {
    var entry = record.entry;
    var payload = entry.payload;
    var taxonomy = payload.taxonomy || {};
    var row = {};
    var source = coordinateSource(entry);
    var latitude = "";
    var longitude = "";
    var uncertainty = "";
    var withheld = optionalText(
      payload,
      "informationWithheld",
      "payload.informationWithheld",
    );
    var generalizations = optionalText(
      payload,
      "dataGeneralizations",
      "payload.dataGeneralizations",
    );
    var georeference = optionalText(
      payload,
      "georeferenceRemarks",
      "payload.georeferenceRemarks",
    );

    if (source && context.locationPolicy.allow) {
      var coordinates =
        context.locationPolicy.mode === "coarse"
          ? context.trust.coarseLocation(
              source,
              context.locationPolicy.decimals,
            )
          : source;
      if (
        !coordinates ||
        !Number.isFinite(coordinates.lat) ||
        !Number.isFinite(coordinates.lon)
      ) {
        fail("coordinates could not be exported under the supplied policy");
      }
      latitude = decimalText(coordinates.lat);
      longitude = decimalText(coordinates.lon);
      uncertainty = uncertaintyFor(payload, context.locationPolicy);
      if (context.locationPolicy.mode === "coarse") {
        var decimals = context.locationPolicy.decimals;
        generalizations = appendNote(
          generalizations,
          "Coordinates rounded to " +
            decimals +
            " decimal places under caller-supplied coarse-location policy.",
        );
        withheld = appendNote(
          withheld,
          "Coordinate precision withheld beyond " +
            decimals +
            " decimal places.",
        );
        georeference = appendNote(
          georeference,
          "Coordinates generalized to " +
            decimals +
            " decimal places; uncertainty is at least " +
            uncertainty +
            " meters.",
        );
      } else {
        georeference = appendNote(
          georeference,
          "Coordinates exported unchanged under caller-supplied exact-coordinate policy.",
        );
      }
    } else if (source) {
      withheld = appendNote(
        withheld,
        "Precise coordinates and location withheld by export policy.",
      );
      generalizations = appendNote(
        generalizations,
        "Coordinates omitted; no exact or coarse location export was authorized.",
      );
      georeference = appendNote(
        georeference,
        "Coordinates withheld by export policy.",
      );
    }

    row.occurrenceID = "urn:vickrey:commitment:" + entry.hash;
    row.basisOfRecord =
      optionalText(payload, "basisOfRecord", "payload.basisOfRecord") ||
      context.defaultBasis;
    row.eventDate = entry.observed_at;
    row.decimalLatitude = latitude;
    row.decimalLongitude = longitude;
    row.coordinateUncertaintyInMeters = uncertainty;
    TAXONOMY_FIELDS.forEach(function (field) {
      row[field] = payloadField(payload, taxonomy, field);
    });
    row.recordedBy = optionalText(payload, "recordedBy", "payload.recordedBy");
    row.occurrenceRemarks = optionalText(
      payload,
      "occurrenceRemarks",
      "payload.occurrenceRemarks",
    );
    row.associatedMedia = mediaText(payload.associatedMedia);
    DATASET_FIELDS.forEach(function (field) {
      row[field] = datasetField(payload, context.dataset, field);
    });
    row.informationWithheld = withheld;
    row.dataGeneralizations = generalizations;
    row.identificationQualifier = optionalText(
      payload,
      "identificationQualifier",
      "payload.identificationQualifier",
    );
    row.identificationVerificationStatus =
      optionalText(
        payload,
        "identificationVerificationStatus",
        "payload.identificationVerificationStatus",
      ) || "unverified";
    row.georeferenceRemarks = georeference;

    var disclosureStatus = context.disclosure
      ? context.disclosure.hash === entry.hash
        ? "verified"
        : "not_applicable"
      : "not_provided";
    var sources = ["local:journal-chain-and-signatures"];
    if (context.checkpointProvided) {
      sources.push("local:signed-checkpoint");
    }
    if (context.correctionsProvided) {
      sources.push("local:append-only-corrections");
    }
    if (disclosureStatus === "verified") {
      sources.push("local:disclosure-entry-and-receipt-binding");
    }
    row["dcterms:provenance"] = [
      "schema=" + SCHEMA,
      "journal_chain=verified",
      "entry_signature=verified",
      "checkpoint=" + context.checkpointStatus,
      "corrections=" +
        context.correctionsStatus +
        ":" +
        context.correctionCount,
      "disclosure=" + disclosureStatus,
      "verification_scope=local_commitment_integrity_only",
      "observation_truth=not_established",
      "capture_time=not_established",
      "observer_identity=not_established",
      "independent_anchoring=not_established",
      "embedded_service_verification=" +
        (disclosureStatus === "verified"
          ? "historical_assertion_only"
          : "not_provided"),
    ].join("; ");
    row["vickrey:commitment"] = entry.hash;
    row["vickrey:devicePublicKey"] = context.publicKeyText;
    row["vickrey:signature"] = entry.signature;
    row["vickrey:journalHead"] = context.head;
    row["vickrey:journalCount"] = context.count;
    row["vickrey:journalVerificationStatus"] = "verified";
    row["vickrey:checkpointVerificationStatus"] = context.checkpointStatus;
    row["vickrey:correctionsVerificationStatus"] = context.correctionsStatus;
    row["vickrey:correctionReferences"] =
      context.correctionByTarget[entry.hash] || "";
    row["vickrey:verificationSources"] = sources.join(" | ");
    row["vickrey:disclosureVerificationStatus"] = disclosureStatus;
    row["vickrey:disclosureVerificationSource"] =
      disclosureStatus === "verified"
        ? context.disclosure.historicalSource
          ? "historical_service_assertion:" +
            context.disclosure.historicalSource
          : "not_provided"
        : "";
    return row;
  }

  function csvCell(value) {
    var text = value === undefined || value === null ? "" : String(value);
    if (!isWellFormed(text)) {
      fail("a CSV cell is not valid Unicode");
    }
    if (/^[=+\-@\t\r]/.test(text)) {
      text = "'" + text;
    }
    if (/[",\r\n]/.test(text)) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function encodeCsv(rows, bom) {
    var lines = [COLUMNS.map(csvCell).join(",")];
    rows.forEach(function (row) {
      lines.push(
        COLUMNS.map(function (column) {
          return csvCell(row[column]);
        }).join(","),
      );
    });
    return (bom ? "\uFEFF" : "") + lines.join("\r\n") + "\r\n";
  }

  /* Returns Unicode CSV text; encode with TextEncoder for UTF-8 bytes. */
  async function buildResearchExport(records, publicKeyText, options) {
    if (!Array.isArray(records)) {
      fail("records must be an array");
    }
    var normalized = normalizeOptions(options);
    var trust = trustModule();
    var entries = [];
    var seen = {};
    records.forEach(function (record, index) {
      if (!isPlainObject(record)) {
        fail("records[" + index + "] is not an object");
      }
      var entry = record.entry;
      checkEntry(entry, "records[" + index + "].entry", false, trust);
      if (seen[entry.hash]) {
        fail("records[" + index + "] duplicates a journal commitment");
      }
      seen[entry.hash] = true;
      entries.push(entry);
    });
    if (entries.length && entries[0].prev !== null) {
      fail("journal chain does not start at null");
    }
    var publicKey = await importDeviceKey(publicKeyText, trust);
    await verifyJournal(entries, publicKey, trust);

    var head = entries.length ? entries[entries.length - 1].hash : "";
    var count = entries.length;
    var checkpointProvided =
      options &&
      options.checkpoint !== undefined &&
      options.checkpoint !== null;
    var checkpointStatus = "not_provided";
    if (checkpointProvided) {
      if (!entries.length) {
        fail("an empty journal cannot have a checkpoint");
      }
      await verifyCheckpoint(options.checkpoint, head, count, publicKey, trust);
      checkpointStatus = "verified";
    }

    var correctionsProvided =
      options &&
      options.corrections !== undefined &&
      options.corrections !== null;
    var corrections = correctionsProvided ? options.corrections : [];
    var correctionStatus = correctionsProvided ? "verified" : "not_provided";
    var correctionByTarget = {};
    if (correctionsProvided) {
      await verifyCorrections(corrections, entries, publicKey, trust);
      corrections.forEach(function (entry) {
        correctionByTarget[entry.payload.supersedes] = entry.hash;
      });
    }

    var disclosure = null;
    if (
      options &&
      options.disclosure !== undefined &&
      options.disclosure !== null
    ) {
      disclosure = await verifyDisclosure(
        options.disclosure,
        publicKeyText,
        entries,
      );
    }

    var context = {
      trust: trust,
      publicKeyText: publicKeyText,
      dataset: normalized.dataset,
      defaultBasis: normalized.defaultBasis,
      locationPolicy: normalized.locationPolicy,
      head: head,
      count: count,
      checkpointProvided: checkpointProvided,
      checkpointStatus: checkpointStatus,
      correctionsProvided: correctionsProvided,
      correctionsStatus: correctionStatus,
      correctionCount: corrections.length,
      correctionByTarget: correctionByTarget,
      disclosure: disclosure,
    };
    var rows = records.map(function (record) {
      return buildRow(record, context);
    });
    return encodeCsv(rows, normalized.bom);
  }

  return {
    BASIS_OF_RECORD: Object.keys(BASIS_OF_RECORD),
    COLUMNS: COLUMNS.slice(),
    DARWIN_CORE_TERMS: DARWIN_CORE_TERMS.slice(),
    PROVENANCE_COLUMNS: PROVENANCE_COLUMNS.slice(),
    SCHEMA: SCHEMA,
    buildResearchExport: buildResearchExport,
    exportRecords: buildResearchExport,
  };
});
