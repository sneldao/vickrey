import { expect } from "@playwright/test";

export const DB_NAME = "vickrey-field";
export const DB_SCHEMA = "vickrey.field-state/1";
export const PASSPHRASE = "browser-gate-test-passphrase";

export function fieldUrl(origin) {
  const query = new URLSearchParams({
    ledger: `${origin}/mock/ledger`,
    commons: `${origin}/mock/ledger`,
    zanchor: `${origin}/mock/zanchor`,
    explorer: `${origin}/explorer/`,
    anchor: "shielded",
  });
  return `${origin}/field/?${query}`;
}

export async function waitForFieldReady(page) {
  await expect(page.locator("#app .network-status")).toBeVisible();
  await expect(page.locator('[data-act="sample"]')).toBeEnabled();
  await expect(page.locator(".integrity-banner")).toHaveCount(0);
  await expect(page.locator(".service-line")).toContainText(
    "Anchor service online",
  );
}

export async function openField(page, origin) {
  await page.goto(fieldUrl(origin));
  await waitForFieldReady(page);
}

export async function seedWalk(page) {
  await page
    .getByRole("button", { name: "Load the sample walk", exact: true })
    .click();
  await expect(page.locator("section.journal .sighting")).toHaveCount(3);
  await expect(page.locator('[data-act="seed"]')).toHaveCount(0);
}

export async function sealSample(page) {
  await page.locator('[data-act="sample"]').click();
  await expect(
    page.getByRole("button", { name: "Confirm & seal", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm & seal", exact: true })
    .click();
  await expect(page.locator(".sealed-note")).toContainText("Sealed.");
  await expect(page.locator("section.journal .sighting")).toHaveCount(1);
}

export async function readDeviceState(page) {
  return page.evaluate(async (dbName) => {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open(dbName);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      const transaction = db.transaction("state", "readonly");
      const request = transaction.objectStore("state").get("device");
      const state = await new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      return state;
    } finally {
      db.close();
    }
  }, DB_NAME);
}

export async function writeDeviceState(page, state) {
  await page.evaluate(
    async ({ dbName, next }) => {
      const db = await new Promise((resolve, reject) => {
        const request = indexedDB.open(dbName);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        await new Promise((resolve, reject) => {
          const transaction = db.transaction("state", "readwrite");
          transaction.objectStore("state").put(structuredClone(next), "device");
          transaction.oncomplete = resolve;
          transaction.onerror = () => reject(transaction.error);
          transaction.onabort = () => reject(transaction.error);
        });
      } finally {
        db.close();
      }
    },
    { dbName: DB_NAME, next: state },
  );
}

export async function verifyStoredState(page, state) {
  return page.evaluate(
    async ({ schema, snapshot }) => {
      const values = snapshot.values;
      const journal = JSON.parse(values["vickrey.journal"]);
      const outbox = JSON.parse(values["vickrey.queue"]);
      const plan = JSON.parse(values["vickrey.anchor_plan"]);
      const deviceKey = JSON.parse(values["vickrey.device_key"]);
      const publicKey = await VickreyTrust.importPublicKey(deviceKey.pk);
      const journalVerdict = await VickreyTrust.verifyChain(
        journal.map((record) => record.entry),
        publicKey,
      );
      const outboxVerdict = await VickreyTrust.verifyChain(outbox, publicKey);
      const checkpointVerdict = journal.length
        ? await VickreyIntegrity.verifyCheckpoint(
            snapshot.checkpoint,
            journal[journal.length - 1].entry.hash,
            journal.length,
            publicKey,
          )
        : { ok: snapshot.checkpoint === null };
      const sealedByHash = new Map(
        journal.map((record) => [record.entry.hash, record.entry]),
      );
      return {
        schemaMatches: snapshot.schema === schema,
        publicKey: deviceKey.pk,
        journalCount: journal.length,
        outboxCount: outbox.length,
        scheduleCount: Object.keys(plan).length,
        checkpoint: snapshot.checkpoint,
        journalVerdict,
        outboxVerdict,
        checkpointVerdict,
        outboxMatchesJournal: outbox.every(
          (entry) =>
            VickreyTrust.canonical(sealedByHash.get(entry.hash)) ===
            VickreyTrust.canonical(entry),
        ),
      };
    },
    { schema: DB_SCHEMA, snapshot: state },
  );
}

export async function resetOriginStorage(page, origin) {
  await page.goto(`${origin}/__test__/blank`);
  await page.evaluate(async (dbName) => {
    if (new URL(location.href).pathname !== "/__test__/blank") {
      throw new Error("storage reset must run on the same-origin blank page");
    }
    localStorage.clear();
    await new Promise((resolve, reject) => {
      const request = indexedDB.deleteDatabase(dbName);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
      request.onblocked = () =>
        reject(new Error("test database deletion was blocked"));
    });
  }, DB_NAME);
  const databases = await page.evaluate(() => indexedDB.databases());
  expect(databases.map((entry) => entry.name)).not.toContain(DB_NAME);
}

export async function journalProjection(page) {
  return page.evaluate(() => ({
    rows: document.querySelector(".sightings")?.innerHTML || "",
    count: document.querySelector("#outbox-count")?.textContent,
    hint: document.querySelector("section.outbox > .hint")?.textContent,
    deviceKey: document.querySelector("section.journal .device")?.textContent,
  }));
}
