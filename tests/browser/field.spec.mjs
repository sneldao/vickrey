import { readFile } from "node:fs/promises";
import { test as base, expect } from "@playwright/test";
import { startServer } from "./server.mjs";
import {
  DB_SCHEMA,
  PASSPHRASE,
  journalProjection,
  openField,
  readDeviceState,
  resetOriginStorage,
  sealSample,
  seedWalk,
  verifyStoredState,
  waitForFieldReady,
  writeDeviceState,
} from "./helpers.mjs";

const test = base.extend({
  server: async ({}, use) => {
    const server = await startServer();
    await use(server);
    await server.close();
  },
  context: async ({ browser, server }, use) => {
    const context = await browser.newContext({
      baseURL: server.origin,
      viewport: { width: 1280, height: 900 },
      acceptDownloads: true,
    });
    await use(context);
    await context.close();
  },
  page: async ({ context }, use) => {
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(`console: ${message.text()}`);
    });
    await use(page);
    expect(errors, `Unexpected browser errors:\n${errors.join("\n")}`).toEqual(
      [],
    );
  },
});

test("golden sample walk retains signed journal, outbox, schedule and checkpoint after reload", async ({
  page,
  server,
}) => {
  await openField(page, server.origin);
  await seedWalk(page);
  const before = await readDeviceState(page);
  const verification = await verifyStoredState(page, before);

  expect(verification.schemaMatches).toBe(true);
  expect(verification.journalCount).toBe(3);
  expect(verification.outboxCount).toBe(3);
  expect(verification.scheduleCount).toBe(3);
  expect(verification.journalVerdict.ok).toBe(true);
  expect(verification.outboxVerdict.ok).toBe(true);
  expect(verification.checkpointVerdict.ok).toBe(true);
  expect(verification.outboxMatchesJournal).toBe(true);
  expect(verification.checkpoint).toMatchObject({
    schema: "vickrey.journal-checkpoint/1",
    count: 3,
    head: JSON.parse(before.values["vickrey.journal"])[2].entry.hash,
  });

  await page.reload();
  await waitForFieldReady(page);
  await expect(page.locator("section.journal .sighting")).toHaveCount(3);
  await expect(page.locator("#outbox-count")).toHaveText("3 waiting");
  const after = await readDeviceState(page);
  expect(after).toEqual(before);
  expect(await verifyStoredState(page, after)).toMatchObject({
    schemaMatches: true,
    journalVerdict: { ok: true },
    outboxVerdict: { ok: true },
    checkpointVerdict: { ok: true },
    outboxMatchesJournal: true,
  });
  expect(server.posts()).toHaveLength(0);
});

test("direct journal forgery fails closed after reload with an empty outbox", async ({
  page,
  server,
}) => {
  await openField(page, server.origin);
  await seedWalk(page);
  const original = await readDeviceState(page);
  const forged = structuredClone(original);
  const journal = JSON.parse(forged.values["vickrey.journal"]);
  journal[0].entry.payload.species = "Forged common blackbird";
  journal[0].entry.payload.detail = "edited directly in IndexedDB";
  forged.values["vickrey.journal"] = JSON.stringify(journal);
  forged.values["vickrey.queue"] = "[]";
  await page.evaluate(() => localStorage.setItem("vickrey.queue", "[]"));
  await writeDeviceState(page, forged);

  await page.reload();
  await expect(page.locator(".integrity-banner")).toContainText(
    "does not verify (hash at entry 1)",
  );
  await expect(page.locator('.verdict[data-tone="mismatch"]')).toContainText(
    "record was edited after it was signed",
  );
  await expect(page.locator('.sighting[data-state="cracked"]')).toHaveCount(1);
  await expect(page.locator("#sync")).toBeDisabled();
  await expect(page.locator("#outbox-count")).toHaveText("0 waiting");
  await page
    .getByRole("button", { name: "Check the seal", exact: true })
    .click();
  await expect(page.locator('.verdict[data-tone="mismatch"]')).toContainText(
    "seal is cracked at entry 1",
  );
  await expect(page.locator("#sync")).toBeDisabled();
  await page.evaluate(() => document.getElementById("sync").click());

  const retained = await readDeviceState(page);
  expect(retained.schema).toBe(DB_SCHEMA);
  expect(JSON.parse(retained.values["vickrey.queue"])).toEqual([]);
  expect(
    JSON.parse(retained.values["vickrey.journal"])[0].entry.payload.species,
  ).toBe("Forged common blackbird");
  expect(retained.checkpoint).toEqual(original.checkpoint);
  expect(server.posts()).toHaveLength(0);
});

test("an aborted IndexedDB append is atomic and the same record can be retried", async ({
  page,
  server,
}) => {
  await page.addInitScript(() => {
    const originalPut = IDBObjectStore.prototype.put;
    window.__fieldWriteFault = {
      enabled: false,
      baseline: 0,
      attempts: 0,
      aborts: 0,
    };
    IDBObjectStore.prototype.put = function (value, key) {
      if (
        window.__fieldWriteFault.enabled &&
        this.name === "state" &&
        key === "device" &&
        value?.schema === "vickrey.field-state/1"
      ) {
        const length = JSON.parse(
          value.values["vickrey.journal"] || "[]",
        ).length;
        if (length > window.__fieldWriteFault.baseline) {
          window.__fieldWriteFault.attempts += 1;
          const request = originalPut.call(this, value, key);
          window.__fieldWriteFault.aborts += 1;
          request.transaction.abort();
          return request;
        }
      }
      return originalPut.call(this, value, key);
    };
  });
  await openField(page, server.origin);
  await seedWalk(page);
  const before = await readDeviceState(page);
  const projectionBefore = await journalProjection(page);
  await page.evaluate((baseline) => {
    window.__fieldWriteFault.baseline = baseline;
    window.__fieldWriteFault.enabled = true;
  }, JSON.parse(before.values["vickrey.journal"]).length);

  await page.locator('[data-act="sample"]').click();
  await page
    .getByRole("button", { name: "Confirm & seal", exact: true })
    .click();
  await expect(page.locator(".capture-card .action-error")).toBeVisible();
  expect(await page.evaluate(() => window.__fieldWriteFault)).toMatchObject({
    attempts: 1,
    aborts: 1,
  });
  expect(await readDeviceState(page)).toEqual(before);
  expect(await journalProjection(page)).toEqual(projectionBefore);
  await expect(page.locator("section.journal .sighting")).toHaveCount(3);
  await expect(page.locator("#outbox-count")).toHaveText("3 waiting");

  await page.evaluate(() => {
    window.__fieldWriteFault.enabled = false;
  });
  await page
    .getByRole("button", { name: "Confirm & seal", exact: true })
    .click();
  await expect(page.locator(".sealed-note")).toContainText("Sealed.");
  await expect(page.locator("section.journal .sighting")).toHaveCount(4);
  await expect(page.locator("#outbox-count")).toHaveText("4 waiting");
  const after = await readDeviceState(page);
  const verification = await verifyStoredState(page, after);
  expect(verification).toMatchObject({
    journalCount: 4,
    outboxCount: 4,
    scheduleCount: 4,
    journalVerdict: { ok: true },
    outboxVerdict: { ok: true },
    checkpointVerdict: { ok: true },
    outboxMatchesJournal: true,
  });
  expect(verification.checkpoint.count).toBe(4);
  expect(JSON.parse(after.values["vickrey.journal"]).slice(0, 3)).toEqual(
    JSON.parse(before.values["vickrey.journal"]),
  );
  const planBefore = JSON.parse(before.values["vickrey.anchor_plan"]);
  const planAfter = JSON.parse(after.values["vickrey.anchor_plan"]);
  for (const [hash, draw] of Object.entries(planBefore))
    expect(planAfter[hash]).toBe(draw);
});

test("encrypted backup restores the key, signed journal, outbox and checkpoint onto an empty origin", async ({
  page,
  server,
}) => {
  await openField(page, server.origin);
  await sealSample(page);
  const source = await readDeviceState(page);
  expect(await verifyStoredState(page, source)).toMatchObject({
    journalCount: 1,
    outboxCount: 1,
    scheduleCount: 1,
    journalVerdict: { ok: true },
    outboxVerdict: { ok: true },
    checkpointVerdict: { ok: true },
  });

  await page.locator('details[data-open-key="backup-export"] summary').click();
  await page.locator("#backup-pass").fill(PASSPHRASE);
  await page.locator("#backup-pass2").fill(PASSPHRASE);
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download encrypted backup", exact: true })
    .click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^vickrey-backup-.*\.json$/);
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  const envelope = JSON.parse(await readFile(downloadPath, "utf8"));
  expect(envelope).toMatchObject({
    schema: "vickrey.backup/2",
    kdf: "PBKDF2-SHA256",
    iterations: 600_000,
  });
  expect(envelope.ciphertext).toEqual(expect.any(String));
  expect(JSON.stringify(envelope)).not.toContain("Common blackbird");
  await download.delete();

  await resetOriginStorage(page, server.origin);
  await openField(page, server.origin);
  await expect(page.locator("section.journal .sighting")).toHaveCount(0);
  const emptyDevice = await readDeviceState(page);
  expect(emptyDevice.values["vickrey.device_key"]).not.toBe(
    source.values["vickrey.device_key"],
  );

  await page.locator('details[data-open-key="backup-restore"] summary').click();
  await page.locator("#backup-file").setInputFiles({
    name: download.suggestedFilename(),
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(envelope)),
  });
  await page.locator("#restore-pass").fill(PASSPHRASE);
  await page.locator("#restore-consent").check();
  const navigation = page.waitForNavigation({ waitUntil: "domcontentloaded" });
  await page
    .getByRole("button", { name: "Restore onto this device", exact: true })
    .click();
  await navigation;
  await waitForFieldReady(page);
  await expect(page.locator("section.journal .sighting")).toHaveCount(1);
  await expect(page.locator(".sighting-name")).toHaveText("Common blackbird");
  await expect(page.locator("#outbox-count")).toHaveText("1 waiting");

  const restored = await readDeviceState(page);
  expect(restored).toEqual(source);
  expect(await verifyStoredState(page, restored)).toMatchObject({
    schemaMatches: true,
    publicKey: JSON.parse(source.values["vickrey.device_key"]).pk,
    journalCount: 1,
    outboxCount: 1,
    scheduleCount: 1,
    journalVerdict: { ok: true },
    outboxVerdict: { ok: true },
    checkpointVerdict: { ok: true },
    outboxMatchesJournal: true,
  });
});

test("keyboard skip link, focus, selection and drafts survive an asynchronous rerender", async ({
  page,
  server,
}) => {
  let releaseProbe;
  const probeGate = new Promise((resolve) => {
    releaseProbe = resolve;
  });
  await page.route(`${server.origin}/mock/ledger/`, async (route) => {
    await probeGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ observations: [] }),
    });
  });
  await openField(page, server.origin);

  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", {
    name: "Skip to field client",
    exact: true,
  });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();
  const skipBox = await skipLink.boundingBox();
  expect(skipBox.height).toBeGreaterThanOrEqual(44);
  expect(skipBox.y).toBeGreaterThanOrEqual(0);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#app$/);
  await expect(page.locator("#app")).toBeFocused();

  await page.locator('details[data-open-key="model"] summary').click();
  await page
    .locator('#model-form input[name="endpoint"]')
    .fill("http://127.0.0.1:11434/draft");
  const modelInput = page.locator('#model-form input[name="model"]');
  await modelInput.fill("draft-model-name");
  await modelInput.evaluate((node) => node.setSelectionRange(2, 7));
  await page.locator("#export-location").selectOption("coarse");
  await page.locator("#export-location-consent").check();
  await modelInput.focus();
  await modelInput.evaluate((node) =>
    node.setAttribute("data-browser-gate-old", "yes"),
  );

  releaseProbe();
  await expect(page.locator("[data-browser-gate-old]")).toHaveCount(0);
  await expect(modelInput).toBeFocused();
  await expect(modelInput).toHaveValue("draft-model-name");
  expect(
    await modelInput.evaluate((node) => [
      node.selectionStart,
      node.selectionEnd,
    ]),
  ).toEqual([2, 7]);
  await expect(page.locator('#model-form input[name="endpoint"]')).toHaveValue(
    "http://127.0.0.1:11434/draft",
  );
  await expect(page.locator("#export-location")).toHaveValue("coarse");
  await expect(page.locator("#export-location-consent")).toBeChecked();
});

for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile-320", width: 320, height: 740 },
  { name: "mobile-375", width: 375, height: 812 },
]) {
  test(`${viewport.name} has no document overflow and visible controls meet 44px targets`, async ({
    page,
    server,
  }) => {
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await openField(page, server.origin);
    await seedWalk(page);
    for (const summary of await page
      .locator("details[data-open-key] > summary")
      .all()) {
      await summary.click();
    }

    const measurements = await page.evaluate(() => {
      const selector = [
        "a[href]",
        "button",
        "input:not([type=file]):not([type=checkbox]):not([type=radio])",
        "select",
        "textarea",
        "summary",
        "label.file",
        "label.consent",
        "[role=button]",
        "[role=link]",
      ].join(",");
      const round = (value) => Math.round(value * 100) / 100;
      const cssPath = (node) => {
        const parts = [];
        for (let element = node; element; element = element.parentElement) {
          let part = element.tagName.toLowerCase();
          if (element.id) {
            parts.unshift(`#${CSS.escape(element.id)}`);
            break;
          }
          if (element.hasAttribute("data-act")) {
            part += `[data-act="${element.getAttribute("data-act")}"]`;
          }
          if (element.hasAttribute("data-open-key")) {
            part += `[data-open-key="${element.getAttribute("data-open-key")}"]`;
          }
          const siblings = element.parentElement
            ? [...element.parentElement.children].filter(
                (child) => child.tagName === element.tagName,
              )
            : [];
          if (siblings.length > 1)
            part += `:nth-of-type(${siblings.indexOf(element) + 1})`;
          parts.unshift(part);
        }
        return parts.join(" > ");
      };
      const controls = [...document.querySelectorAll(selector)]
        .map((node) => {
          const style = getComputedStyle(node);
          const rect = node.getBoundingClientRect();
          return {
            node,
            display: style.display,
            visibility: style.visibility,
            opacity: style.opacity,
            rect,
          };
        })
        .filter(
          ({ display, visibility, opacity, rect }) =>
            display !== "none" &&
            visibility !== "hidden" &&
            opacity !== "0" &&
            rect.width > 0 &&
            rect.height > 0,
        )
        .map(({ node, rect }) => ({
          selector: cssPath(node),
          label: (
            node.getAttribute("aria-label") ||
            node.innerText ||
            node.tagName
          )
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, 120),
          width: round(rect.width),
          height: round(rect.height),
          left: round(rect.left),
          right: round(rect.right),
        }));
      return {
        innerWidth,
        documentClientWidth: document.documentElement.clientWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        bodyClientWidth: document.body.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        undersized: controls.filter(
          (control) => control.width < 44 || control.height < 44,
        ),
        offscreen: controls.filter(
          (control) => control.left < -0.5 || control.right > innerWidth + 0.5,
        ),
      };
    });

    expect(
      measurements.documentScrollWidth,
      `document scroll width ${measurements.documentScrollWidth}px exceeds ${viewport.width}px`,
    ).toBeLessThanOrEqual(viewport.width);
    expect(
      measurements.bodyScrollWidth,
      `body scroll width ${measurements.bodyScrollWidth}px exceeds ${viewport.width}px`,
    ).toBeLessThanOrEqual(viewport.width);
    expect(
      measurements.offscreen,
      `Controls outside the horizontal viewport:\n${JSON.stringify(measurements.offscreen, null, 2)}`,
    ).toEqual([]);
    expect(
      measurements.undersized,
      `Sub-44px visible controls:\n${JSON.stringify(measurements.undersized, null, 2)}`,
    ).toEqual([]);
  });
}

test("print media retains closed journal proofs and produces a printable PDF", async ({
  page,
  server,
}) => {
  await openField(page, server.origin);
  await seedWalk(page);
  const state = await readDeviceState(page);
  const journal = JSON.parse(state.values["vickrey.journal"]);
  const deviceKey = JSON.parse(state.values["vickrey.device_key"]).pk;
  await expect(page.locator("details.proof-wrap[open]")).toHaveCount(0);
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("section.journal")).toBeVisible();

  for (const record of journal) {
    const entry = record.entry;
    const row = page.locator(`#s-${entry.hash.slice(0, 12)}`);
    const proof = row.locator(".proof");
    await expect(row.locator(".sighting-name")).toHaveText(
      entry.payload.species,
    );
    await expect(proof).toContainText(entry.hash);
    await expect(proof).toContainText(entry.signature);
    await expect(proof).toContainText(deviceKey);
    const rendering = await proof.evaluate((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return {
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity,
        contentVisibility: style.contentVisibility,
        width: rect.width,
        height: rect.height,
      };
    });
    expect(rendering.display).not.toBe("none");
    expect(rendering.visibility).toBe("visible");
    expect(rendering.opacity).not.toBe("0");
    expect(rendering.contentVisibility).not.toBe("hidden");
    expect(rendering.width).toBeGreaterThan(0);
    expect(rendering.height).toBeGreaterThan(0);
    const fields = await proof.locator("dd").evaluateAll((nodes) =>
      nodes.map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          text: node.textContent,
          width: rect.width,
          height: rect.height,
        };
      }),
    );
    expect(fields.length).toBeGreaterThanOrEqual(7);
    for (const field of fields) {
      expect(field.width).toBeGreaterThan(0);
      expect(field.height).toBeGreaterThan(0);
    }
  }

  const pdf = await page.pdf({
    format: "A4",
    printBackground: true,
    preferCSSPageSize: true,
  });
  expect(pdf.byteLength).toBeGreaterThan(5_000);
});
