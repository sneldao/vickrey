import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");
const integrity = require("./integrity.js");
const disclosure = require("./disclosure.js");
const researchExport = require("./export.js");

globalThis.VickreyTrust = trust;
globalThis.VickreyIntegrity = integrity;

const clone = (value) => JSON.parse(JSON.stringify(value));
const safetyPrefix = (value) =>
  /^[=+\-@\t\r]/.test(value) ? "'" + value : value;

function parseCsv(csv) {
  const bom = csv.charCodeAt(0) === 0xfeff;
  const text = bom ? csv.slice(1) : csv;
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"' && cell === "") {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\r" || char === "\n") {
      if (char === "\r" && text[i + 1] === "\n") {
        i++;
      }
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      assert.notEqual(char, '"', "quote inside an unquoted CSV cell");
      cell += char;
    }
  }

  assert.equal(quoted, false, "unterminated quoted CSV cell");
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return { bom, rows };
}

function objects(csv) {
  const { rows } = parseCsv(csv);
  assert.deepEqual(rows[0], researchExport.COLUMNS);
  return rows.slice(1).map((values) => {
    assert.equal(values.length, researchExport.COLUMNS.length);
    return Object.fromEntries(
      researchExport.COLUMNS.map((key, index) => [key, values[index]]),
    );
  });
}

async function fixture() {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const publicKeyText = await trust.exportPublicKey(publicKey);
  const first = await trust.sealObservation({
    privateKey,
    observedAt: "2026-10-11T08:00:00.000Z",
    location: { lat: 47.32456, lon: -1.87654 },
    modelId: "gemma3:4b",
    payload: {
      taxonomy: {
        kingdom: "Animalia",
        phylum: "Chordata",
        class: "Aves",
        order: "Passeriformes",
        family: "Muscicapidae",
        genus: "Erithacus",
        scientificName: "Erithacus rubecula",
      },
      vernacularName: "European robin",
      recordedBy: 'Ada, "Lin"',
      occurrenceRemarks: "Seen, resting\r\non a branch",
      associatedMedia: [
        "https://example.test/robin.jpg",
        "https://example.test/robin-notes.txt",
      ],
      identificationQualifier: "cf.",
      identificationVerificationStatus: "unverified",
      georeferenceRemarks: "Handheld GPS",
      review: { decision: "confirmed", suggested_species: "European robin" },
    },
  });
  const second = await trust.sealObservation({
    privateKey,
    prev: first.hash,
    observedAt: "2026-10-11T08:04:00.000Z",
    modelId: "gemma3:4b",
    payload: {
      kind: "bird",
      species: "Robin",
      confidence: 0.95,
      detail: "A model suggestion, not a taxonomic assertion.",
      review: { decision: "confirmed", suggested_species: "Robin" },
    },
  });
  const records = [{ entry: first }, { entry: second }];
  const checkpoint = await integrity.sealCheckpoint(second.hash, 2, privateKey);
  const correction = await integrity.sealCorrection({
    privateKey,
    prev: null,
    supersedes: first.hash,
    payload: {
      reason: "Identification reviewed",
      correction: { scientificName: "Erithacus rubecula" },
    },
  });
  const bundle = await disclosure.buildDisclosure(first, publicKeyText, {
    receipt: {
      receipt_id: "rec_export_test",
      commitment: first.hash,
      status: "confirmed",
      mode: "B",
      shielded: true,
      txid: "f".repeat(64),
      height: 101,
      anchored_at: "2026-10-28T00:00:00Z",
    },
    verification: {
      receipt_id: "rec_export_test",
      commitment: first.hash,
      txid: "f".repeat(64),
      height: 101,
      confirmations: 5,
      network: "regtest",
      transaction_verified: true,
      commitment_verified: true,
      binding: "encrypted_memo",
      verification_source: "service_wallet",
      reason: "commitment_in_encrypted_memo",
    },
  });
  return {
    privateKey,
    publicKey,
    publicKeyText,
    first,
    second,
    records,
    checkpoint,
    correction,
    bundle,
  };
}

async function simpleRecord(payload, location = null) {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const entry = await trust.sealObservation({
    privateKey,
    observedAt: "2026-11-02T10:30:00Z",
    location,
    payload,
  });
  return {
    entry,
    records: [{ entry }],
    publicKeyText: await trust.exportPublicKey(publicKey),
    privateKey,
  };
}

const coarsePolicy = { allow: true, mode: "coarse", decimals: 2 };

test("accepted export maps explicit values and cryptographic provenance", async () => {
  const context = await fixture();
  const csv = await researchExport.buildResearchExport(
    context.records,
    context.publicKeyText,
    {
      datasetID: "field-dataset-1",
      institutionCode: "VK",
      datasetName: 'Field "Notes"',
      locationPolicy: coarsePolicy,
      checkpoint: context.checkpoint,
      corrections: [context.correction],
      disclosure: context.bundle,
    },
  );
  const rows = objects(csv);
  assert.equal(rows.length, 2);
  assert.deepEqual(
    rows.map((row) => row.occurrenceID),
    [
      `urn:vickrey:commitment:${context.first.hash}`,
      `urn:vickrey:commitment:${context.second.hash}`,
    ],
  );

  const first = rows[0];
  assert.equal(first.basisOfRecord, "HumanObservation");
  assert.equal(first.eventDate, "2026-10-11T08:00:00.000Z");
  assert.equal(first.decimalLatitude, "47.32");
  assert.equal(first.decimalLongitude, "'-1.88");
  assert.equal(first.coordinateUncertaintyInMeters, "1114");
  assert.equal(first.kingdom, "Animalia");
  assert.equal(first.phylum, "Chordata");
  assert.equal(first.class, "Aves");
  assert.equal(first.order, "Passeriformes");
  assert.equal(first.family, "Muscicapidae");
  assert.equal(first.genus, "Erithacus");
  assert.equal(first.scientificName, "Erithacus rubecula");
  assert.equal(first.vernacularName, "European robin");
  assert.equal(first.recordedBy, 'Ada, "Lin"');
  assert.equal(first.occurrenceRemarks, "Seen, resting\r\non a branch");
  assert.equal(
    first.associatedMedia,
    "https://example.test/robin.jpg | https://example.test/robin-notes.txt",
  );
  assert.equal(first.datasetID, "field-dataset-1");
  assert.equal(first.institutionCode, "VK");
  assert.equal(first.datasetName, 'Field "Notes"');
  assert.match(first.informationWithheld, /Coordinate precision withheld/);
  assert.match(first.dataGeneralizations, /rounded to 2 decimal places/);
  assert.equal(first.identificationQualifier, "cf.");
  assert.equal(first.identificationVerificationStatus, "unverified");
  assert.match(first.georeferenceRemarks, /Handheld GPS/);
  assert.match(
    first.georeferenceRemarks,
    /uncertainty is at least 1114 meters/,
  );
  assert.match(first["dcterms:provenance"], /journal_chain=verified/);
  assert.match(
    first["dcterms:provenance"],
    /observation_truth=not_established/,
  );
  assert.match(
    first["dcterms:provenance"],
    /independent_anchoring=not_established/,
  );
  assert.equal(first["vickrey:commitment"], context.first.hash);
  assert.equal(
    first["vickrey:devicePublicKey"],
    safetyPrefix(context.publicKeyText),
  );
  assert.equal(
    first["vickrey:signature"],
    safetyPrefix(context.first.signature),
  );
  assert.equal(first["vickrey:journalHead"], context.second.hash);
  assert.equal(first["vickrey:journalCount"], "2");
  assert.equal(first["vickrey:journalVerificationStatus"], "verified");
  assert.equal(first["vickrey:checkpointVerificationStatus"], "verified");
  assert.equal(first["vickrey:correctionsVerificationStatus"], "verified");
  assert.equal(first["vickrey:correctionReferences"], context.correction.hash);
  assert.match(
    first["vickrey:verificationSources"],
    /local:journal-chain-and-signatures/,
  );
  assert.match(first["vickrey:verificationSources"], /local:signed-checkpoint/);
  assert.match(
    first["vickrey:verificationSources"],
    /local:append-only-corrections/,
  );
  assert.match(
    first["vickrey:verificationSources"],
    /local:disclosure-entry-and-receipt-binding/,
  );
  assert.equal(first["vickrey:disclosureVerificationStatus"], "verified");
  assert.equal(
    first["vickrey:disclosureVerificationSource"],
    "historical_service_assertion:service_wallet",
  );

  const second = rows[1];
  for (const field of researchExport.DARWIN_CORE_TERMS.slice(6, 14)) {
    assert.equal(second[field], "", `${field} must not be invented`);
  }
  assert.equal(second.decimalLatitude, "");
  assert.equal(second.decimalLongitude, "");
  assert.equal(second.coordinateUncertaintyInMeters, "");
  assert.equal(second.identificationVerificationStatus, "unverified");
  assert.equal(second["vickrey:correctionReferences"], "");
  assert.equal(
    second["vickrey:disclosureVerificationStatus"],
    "not_applicable",
  );
  assert.equal(second["vickrey:disclosureVerificationSource"], "");
});

test("taxonomy and coordinates are not invented and are private by default", async () => {
  const first = await simpleRecord(
    {
      kind: "bird",
      species: "Robin",
      detail: "Do not promote this to a scientific name.",
    },
    { lat: 47.32456, lon: -1.87654 },
  );
  const secondEntry = await trust.sealObservation({
    privateKey: first.privateKey,
    prev: first.entry.hash,
    observedAt: "2026-11-02T10:31:00Z",
    payload: {
      kind: "plant",
      species: "Male fern",
      decimalLatitude: 51.5074,
      decimalLongitude: -0.1278,
    },
  });
  const records = [...first.records, { entry: secondEntry }];
  const csv = await researchExport.buildResearchExport(
    records,
    first.publicKeyText,
    {
      locationPolicy: { allow: false },
    },
  );
  const rows = objects(csv);
  assert.equal(rows.length, 2);
  for (const row of rows) {
    for (const field of researchExport.DARWIN_CORE_TERMS.slice(6, 14)) {
      assert.equal(
        row[field],
        "",
        `${field} must not be inferred from species/kind`,
      );
    }
    assert.equal(row.decimalLatitude, "");
    assert.equal(row.decimalLongitude, "");
    assert.equal(row.coordinateUncertaintyInMeters, "");
    assert.equal(row.occurrenceRemarks, "");
    assert.equal(row.associatedMedia, "");
    assert.equal(row.identificationVerificationStatus, "unverified");
    assert.match(
      row.informationWithheld,
      /Precise coordinates and location withheld/,
    );
    assert.match(row.dataGeneralizations, /Coordinates omitted/);
    assert.match(row.georeferenceRemarks, /Coordinates withheld/);
  }
  assert.doesNotMatch(csv, /Robin|Male fern|47\.32456|51\.5074/);
});

test("exact coordinates require an explicit policy and copy only supplied values", async () => {
  const context = await simpleRecord(
    { species: "No taxonomy implied" },
    { lat: 12.25, lon: -8.5 },
  );
  const csv = await researchExport.buildResearchExport(
    context.records,
    context.publicKeyText,
    {
      locationPolicy: { allow: true, mode: "exact" },
    },
  );
  const [row] = objects(csv);
  assert.equal(row.decimalLatitude, "12.25");
  assert.equal(row.decimalLongitude, "'-8.5");
  assert.equal(row.coordinateUncertaintyInMeters, "");
  assert.equal(row.informationWithheld, "");
  assert.equal(row.dataGeneralizations, "");
  assert.match(row.georeferenceRemarks, /exported unchanged/);
  assert.equal(row.scientificName, "");

  const tiny = await simpleRecord({}, { lat: 0.0000001, lon: -0.0000002 });
  const [tinyRow] = objects(
    await researchExport.buildResearchExport(tiny.records, tiny.publicKeyText, {
      locationPolicy: { allow: true, mode: "exact" },
    }),
  );
  assert.equal(tinyRow.decimalLatitude, "0.0000001");
  assert.equal(tinyRow.decimalLongitude, "'-0.0000002");

  const noLocation = await simpleRecord({ species: "Fern" });
  const [blank] = objects(
    await researchExport.buildResearchExport(
      noLocation.records,
      noLocation.publicKeyText,
      { locationPolicy: coarsePolicy },
    ),
  );
  assert.equal(blank.decimalLatitude, "");
  assert.equal(blank.decimalLongitude, "");
  assert.equal(blank.coordinateUncertaintyInMeters, "");
  assert.equal(blank.dataGeneralizations, "");
});

test("CSV quoting, Unicode and formula injection defenses follow RFC4180", async () => {
  const context = await simpleRecord(
    {
      recordedBy: "=1+1",
      occurrenceRemarks: "+SUM(A1:A2)",
      associatedMedia: "@command",
      identificationQualifier: "-argument",
      identificationVerificationStatus: "\tcalc",
      dataGeneralizations: "\rline",
      georeferenceRemarks: 'plain "quoted", line\nnext',
      vernacularName: "éclair",
    },
    { lat: 1.25, lon: -2.5 },
  );
  const csv = await researchExport.buildResearchExport(
    context.records,
    context.publicKeyText,
    {
      datasetName: 'Dataset, "quoted"\r\nname',
      locationPolicy: { allow: true, mode: "exact" },
    },
  );
  const [row] = objects(csv);
  assert.equal(row.recordedBy, "'=1+1");
  assert.equal(row.occurrenceRemarks, "'+SUM(A1:A2)");
  assert.equal(row.associatedMedia, "'@command");
  assert.equal(row.identificationQualifier, "'-argument");
  assert.equal(row.identificationVerificationStatus, "'\tcalc");
  assert.equal(row.dataGeneralizations, "'\rline");
  assert.equal(row.decimalLongitude, "'-2.5");
  assert.equal(
    row.georeferenceRemarks,
    'plain "quoted", line\nnext | Coordinates exported unchanged under caller-supplied exact-coordinate policy.',
  );
  assert.equal(row.vernacularName, "éclair");
  assert.equal(row.datasetName, 'Dataset, "quoted"\r\nname');
  assert.ok(csv.includes('"plain ""quoted"", line\nnext | '));
  assert.ok(csv.includes('"Dataset, ""quoted""\r\nname"'));
  assert.ok(csv.includes("'\rline"));
  assert.ok(csv.includes("\r\n"));
});

test("broken chains, duplicate records and wrong device keys fail closed", async () => {
  const context = await fixture();
  const tampered = clone(context.records);
  tampered[0].entry.payload.taxonomy.genus = "Tampered";
  await assert.rejects(
    () => researchExport.buildResearchExport(tampered, context.publicKeyText),
    /journal chain does not verify \(hash/,
  );

  const other = await trust.generateKeyPair();
  const otherPublicKeyText = await trust.exportPublicKey(other.publicKey);
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(context.records, otherPublicKeyText),
    /journal chain does not verify \(signature/,
  );

  const brokenLink = clone(context.records);
  brokenLink[1].entry.prev = "0".repeat(64);
  brokenLink[1].entry.hash = await trust.commitment({
    prev: brokenLink[1].entry.prev,
    observed_at: brokenLink[1].entry.observed_at,
    location: brokenLink[1].entry.location,
    model_id: brokenLink[1].entry.model_id,
    payload: brokenLink[1].entry.payload,
  });
  brokenLink[1].entry.signature = await trust.signCommitment(
    context.privateKey,
    brokenLink[1].entry.hash,
  );
  await assert.rejects(
    () => researchExport.buildResearchExport(brokenLink, context.publicKeyText),
    /journal chain does not verify \(link/,
  );

  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        [context.records[0], context.records[0]],
        context.publicKeyText,
      ),
    /duplicates a journal commitment/,
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        [...context.records].reverse(),
        context.publicKeyText,
      ),
    /journal chain does not start at null/,
  );
});

test("checkpoints and corrections are verified rather than trusted as labels", async () => {
  const context = await fixture();
  const options = {
    checkpoint: context.checkpoint,
    corrections: [context.correction],
  };
  assert.equal(
    objects(
      await researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        options,
      ),
    ).length,
    2,
  );

  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          ...options,
          checkpoint: { ...context.checkpoint, count: 1 },
        },
      ),
    /checkpoint does not cover/,
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          ...options,
          checkpoint: { ...context.checkpoint, hash: "0".repeat(64) },
        },
      ),
    /checkpoint commitment does not recompute/,
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          ...options,
          checkpoint: {
            ...context.checkpoint,
            signature: trust.bytesToBase64url(new Uint8Array(64)),
          },
        },
      ),
    /checkpoint signature does not verify/,
  );

  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          corrections: {},
        },
      ),
    /corrections must be an array/,
  );
  const tamperedCorrection = clone(context.correction);
  tamperedCorrection.payload.reason = "Tampered after signing";
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          corrections: [tamperedCorrection],
        },
      ),
    /corrections chain does not verify \(hash/,
  );
  const unknownTarget = clone(context.correction);
  unknownTarget.payload.supersedes = "0".repeat(64);
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          corrections: [unknownTarget],
        },
      ),
    /unknown or already corrected/,
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          corrections: [context.correction, context.correction],
        },
      ),
    /duplicates a commitment/,
  );
  const other = await trust.generateKeyPair();
  const foreignCorrection = await integrity.sealCorrection({
    privateKey: other.privateKey,
    prev: null,
    supersedes: context.second.hash,
    payload: { reason: "Foreign key", correction: { species: "Other" } },
  });
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          corrections: [foreignCorrection],
        },
      ),
    /corrections chain does not verify \(signature/,
  );
});

test("disclosures verify locally and embedded service claims stay historical", async () => {
  const context = await fixture();
  const historical = clone(context.bundle);
  historical.verification.transaction_verified = false;
  historical.verification.commitment_verified = false;
  const csv = await researchExport.buildResearchExport(
    context.records,
    context.publicKeyText,
    {
      disclosure: historical,
    },
  );
  const [first, second] = objects(csv);
  assert.equal(first["vickrey:disclosureVerificationStatus"], "verified");
  assert.equal(
    first["vickrey:disclosureVerificationSource"],
    "historical_service_assertion:service_wallet",
  );
  assert.match(
    first["dcterms:provenance"],
    /independent_anchoring=not_established/,
  );
  assert.match(
    first["dcterms:provenance"],
    /embedded_service_verification=historical_assertion_only/,
  );
  assert.doesNotMatch(
    csv,
    /transaction_verified=true|commitment_verified=true/,
  );
  assert.equal(
    second["vickrey:disclosureVerificationStatus"],
    "not_applicable",
  );

  const wrongKey = clone(context.bundle);
  const other = await trust.generateKeyPair();
  wrongKey.public_key = await trust.exportPublicKey(other.publicKey);
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          disclosure: wrongKey,
        },
      ),
    /disclosure public key does not match/,
  );
  const tampered = clone(context.bundle);
  tampered.entry.payload.taxonomy.genus = "Tampered";
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          disclosure: tampered,
        },
      ),
    /disclosure does not verify locally/,
  );
  const malformed = clone(context.bundle);
  malformed.verification = [];
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          disclosure: malformed,
        },
      ),
    /disclosure.verification must be an object/,
  );

  const outsider = await trust.sealObservation({
    privateKey: context.privateKey,
    observedAt: "2026-11-03T00:00:00Z",
    payload: { species: "Outsider" },
  });
  const outsiderBundle = await disclosure.buildDisclosure(
    outsider,
    context.publicKeyText,
    {
      receipt: { receipt_id: "rec_outsider", commitment: outsider.hash },
      verification: { verification_source: "service_wallet" },
    },
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport(
        context.records,
        context.publicKeyText,
        {
          disclosure: outsiderBundle,
        },
      ),
    /disclosure entry is not in the supplied journal/,
  );
});

test("output is deterministic, chain ordered and optionally BOM-prefixed", async () => {
  const context = await fixture();
  const options = {
    metadata: {
      datasetID: "dataset-1",
      institutionCode: "VK",
      datasetName: "Field notes",
    },
    locationPolicy: coarsePolicy,
    checkpoint: context.checkpoint,
    corrections: [context.correction],
    disclosure: context.bundle,
  };
  const first = await researchExport.buildResearchExport(
    context.records,
    context.publicKeyText,
    options,
  );
  const second = await researchExport.buildResearchExport(
    clone(context.records),
    context.publicKeyText,
    clone(options),
  );
  assert.equal(first, second);
  assert.deepEqual(
    objects(first).map((row) => row["vickrey:commitment"]),
    [context.first.hash, context.second.hash],
  );
  const withBom = await researchExport.buildResearchExport(
    context.records,
    context.publicKeyText,
    {
      ...options,
      bom: true,
    },
  );
  assert.equal(withBom, "\uFEFF" + first);
  assert.equal(parseCsv(withBom).bom, true);
  assert.deepEqual(objects(withBom), objects(first));
});

test("malformed records, policies and metadata reject the whole export", async () => {
  const context = await fixture();
  const validKey = context.publicKeyText;
  const invalidInputs = [
    [null, validKey, /records must be an array/],
    [{}, validKey, /records must be an array/],
    [[null], validKey, /records\[0\] is not an object/],
    [[{}], validKey, /entry is not an object/],
    [
      [{ entry: { ...context.first, hash: "bad" } }],
      validKey,
      /64-hex commitment/,
    ],
    [[{ entry: { ...context.first, signature: "!" } }], validKey, /base64url/],
    [
      [{ entry: { ...context.first, observed_at: "2026-02-30T00:00:00Z" } }],
      validKey,
      /real calendar date/,
    ],
    [
      [{ entry: { ...context.first, payload: [] } }],
      validKey,
      /payload is not an object/,
    ],
    [
      [{ entry: { ...context.first, location: { lat: "47", lon: "2" } } }],
      validKey,
      /finite number/,
    ],
    [
      [
        {
          entry: {
            ...context.first,
            payload: { ...context.first.payload, decimalLatitude: 1 },
          },
        },
      ],
      validKey,
      /both decimalLatitude/,
    ],
    [
      [
        {
          entry: {
            ...context.first,
            payload: { ...context.first.payload, taxonomy: { genus: 7 } },
          },
        },
      ],
      validKey,
      /taxonomy.genus must be text/,
    ],
    [
      [
        {
          entry: {
            ...context.first,
            payload: { ...context.first.payload, associatedMedia: {} },
          },
        },
      ],
      validKey,
      /associatedMedia/,
    ],
    [
      [
        {
          entry: {
            ...context.first,
            payload: { ...context.first.payload, basisOfRecord: "toString" },
          },
        },
      ],
      validKey,
      /basisOfRecord/,
    ],
    [context.records, "!", /base64url/],
    [context.records, validKey, /options must be an object/, "bad-options"],
    [
      context.records,
      validKey,
      /options.bom must be a boolean/,
      { bom: "true" },
    ],
    [
      context.records,
      validKey,
      /options.metadata must be an object/,
      { metadata: [] },
    ],
    [
      context.records,
      validKey,
      /unknown field/,
      { locationPolicy: { allow: true, mode: "coarse", typo: 2 } },
    ],
    [
      context.records,
      validKey,
      /locationPolicy.allow must be a boolean/,
      { locationPolicy: { mode: "coarse" } },
    ],
    [
      context.records,
      validKey,
      /mode must be/,
      { locationPolicy: { allow: true, mode: "maybe" } },
    ],
    [
      context.records,
      validKey,
      /decimals must be an integer from 0 to 3/,
      { locationPolicy: { allow: true, mode: "coarse", decimals: 6 } },
    ],
    [
      context.records,
      validKey,
      /uncertaintyMeters must be a positive safe integer/,
      { locationPolicy: { allow: true, mode: "exact", uncertaintyMeters: 0 } },
    ],
  ];
  for (const [records, key, pattern, options] of invalidInputs) {
    await assert.rejects(
      () => researchExport.buildResearchExport(records, key, options),
      pattern,
    );
  }

  const malformedUnicode = clone(context.records);
  malformedUnicode[0].entry.payload.recordedBy = "\ud800";
  await assert.rejects(
    () => researchExport.buildResearchExport(malformedUnicode, validKey),
    /not valid Unicode/,
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport([], validKey, {
        checkpoint: context.checkpoint,
      }),
    /empty journal cannot have a checkpoint/,
  );
  await assert.rejects(
    () =>
      researchExport.buildResearchExport([], validKey, {
        disclosure: context.bundle,
      }),
    /disclosure entry is not in the supplied journal/,
  );

  const empty = await researchExport.buildResearchExport([], validKey);
  assert.deepEqual(parseCsv(empty).rows, [researchExport.COLUMNS]);
});
