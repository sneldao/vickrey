import { readFile } from "node:fs/promises";
import { test as base, expect } from "@playwright/test";
import { startServer } from "./server.mjs";

const upstream = process.env.RECEIPTS_UPSTREAM?.trim();
const privateMarker = "LOCAL_SEALED_NOTE_9f3b71_PRIVATE_MARKER";
const stages = [
  "health",
  "claim",
  "remote_evidence",
  "field_evidence",
  "verdict",
  "settlement",
  "receipt",
];
async function runWorkflow(page) {
  await page.locator("#run-button").click();
  await expect(page.locator("#workflow")).toHaveAttribute("aria-busy", "true");
  await expect(page.locator("#workflow")).toHaveAttribute("aria-busy", "false");
}

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
      permissions: ["clipboard-read", "clipboard-write"],
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

test.describe("Reality Receipts against the real FastAPI demo", () => {
  test.skip(!upstream, "RECEIPTS_UPSTREAM is not configured");

  test("same-origin golden path preserves local evidence and loads a public receipt after reload", async ({
    page,
    server,
  }) => {
    await page.goto("/receipts/");
    await page.locator("#observation-note").fill(privateMarker);
    await page
      .locator("#claim")
      .fill(`Public notice check ${crypto.randomUUID()}.`);

    let finalStatus = "incomplete";
    for (let attempt = 0; attempt < 48; attempt += 1) {
      await runWorkflow(page);
      const statuses = await page
        .locator(".stage")
        .evaluateAll((nodes) =>
          Object.fromEntries(
            nodes.map((node) => [node.dataset.stage, node.dataset.state]),
          ),
        );
      expect(statuses.health).toBe("success");
      expect(statuses.claim).toBe("success");
      expect(statuses.remote_evidence).toBe("success");
      if (statuses.field_evidence !== "skipped") {
        expect(statuses).toEqual(
          Object.fromEntries(stages.map((stage) => [stage, "success"])),
        );
        finalStatus = "complete";
        break;
      }
      expect(statuses.field_evidence).toBe("skipped");
      for (const stage of ["verdict", "settlement", "receipt"]) {
        expect(statuses[stage]).toBe("blocked");
      }
      await expect(page.locator("#workflow-error")).toHaveAttribute(
        "data-active",
        "false",
      );
      await expect(page.locator("#receipt-content")).toBeHidden();
      finalStatus = await page
        .locator('[data-stage="remote_evidence"] .stage-detail')
        .textContent();
    }
    expect(finalStatus).toBe("complete");

    const downloadsPromise = page.waitForEvent("download");
    await page.locator("#download-button").click();
    const download = await downloadsPromise;
    expect(download.suggestedFilename()).toMatch(
      /^reality-receipts-.*\.local-sealed\.json$/,
    );
    const record = JSON.parse(await readFile(await download.path(), "utf8"));
    expect(record.sealed_entry.payload.public_summary).toBe(privateMarker);
    expect(record.public_metadata).not.toHaveProperty("public_summary");
    await download.delete();

    const requests = server.receiptsRequests();
    expect(requests.length).toBeGreaterThan(0);
    expect(
      requests.every(
        (request) =>
          request.path === "/healthz" || request.path.startsWith("/v1/"),
      ),
    ).toBe(true);
    expect(
      requests
        .filter((request) => request.path === "/healthz")
        .every((request) => !request.authorizationPresent),
    ).toBe(true);
    const submissions = requests.filter(
      (request) =>
        request.method === "POST" &&
        /\/v1\/challenges\/[^/]+\/submissions$/.test(request.path),
    );
    expect(submissions).toHaveLength(1);
    const submission = JSON.parse(submissions[0].body.toString("utf8"));
    expect(Object.keys(submission).sort()).toEqual([
      "commitment",
      "public_metadata",
    ]);
    expect(Object.keys(submission.public_metadata).sort()).toEqual([
      "captured_at",
      "observation_status",
      "public_location",
    ]);
    expect(submissions[0].authorizationPresent).toBe(true);
    expect(submissions[0].idempotencyKeyPresent).toBe(true);
    expect(JSON.stringify(submission)).not.toContain(privateMarker);
    expect(JSON.stringify(submission)).not.toContain("public_summary");
    expect(JSON.stringify(submission)).not.toContain("observer_public_key");
    expect(
      requests.some((request) => request.body.includes(privateMarker)),
    ).toBe(false);

    const publicRequests = requests.filter((request) =>
      /\/v1\/receipts\/[^/]+$/.test(request.path),
    );
    expect(publicRequests.length).toBeGreaterThan(0);
    expect(
      publicRequests.every((request) => !request.authorizationPresent),
    ).toBe(true);
    const challengeId = await page
      .locator("#receipt-content")
      .evaluate(
        (node) =>
          [...node.querySelectorAll(".receipt-dl > div")]
            .find(
              (row) => row.querySelector("dt")?.textContent === "Challenge ID",
            )
            .querySelector("dd").textContent,
      );
    expect(challengeId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    await expect(page.locator("#receipt-content")).toContainText(
      "Raw observation received",
    );
    await expect(page.locator("#receipt-content")).toContainText("No");
    await expect(page.locator("#receipt-content")).not.toContainText(
      privateMarker,
    );

    const shareUrl = await page.locator("#receipt-share").getAttribute("href");
    const parsedShareUrl = new URL(shareUrl);
    expect(parsedShareUrl.pathname).toBe("/receipts/");
    expect(parsedShareUrl.searchParams.get("challenge")).toBe(challengeId);
    await page.goto(shareUrl);
    await expect(page.locator("#receipt-content")).toBeVisible();
    await expect(page.locator("#receipt-title")).toBeFocused();
    await expect(page.locator("#receipt-content")).toContainText(
      "Simulated settlement",
    );
    await expect(page.locator("#receipt-content")).not.toContainText(
      privateMarker,
    );

    await page.locator("#lookup-id").fill(challengeId);
    await page.locator("#lookup-button").click();
    await expect(page.locator("#receipt-content")).toBeVisible();
    await expect(page.locator("#receipt-title")).toBeFocused();
    await page.locator("#copy-link-button").click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
      challengeId,
    );
  });

  test("320px layout has no overflow, usable targets and keyboard focus, and the receipt prints cleanly", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 320, height: 740 });
    await page.goto("/receipts/");
    await page.locator("#observation-note").fill(privateMarker);
    await page
      .locator("#claim")
      .fill(`Public notice check ${crypto.randomUUID()}.`);
    await page.locator(".credential-details > summary").click();
    await page.locator(".audit-details > summary").click();

    const measurements = await page.evaluate(() => {
      const controls = [
        ...document.querySelectorAll(
          'a[href], button, input:not([type="file"]), select, textarea, summary, [role="button"], [role="link"]',
        ),
      ]
        .filter((node) => {
          const style = getComputedStyle(node);
          const rect = node.getBoundingClientRect();
          return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            style.opacity !== "0" &&
            rect.width > 0 &&
            rect.height > 0
          );
        })
        .map((node) => {
          const rect = node.getBoundingClientRect();
          return {
            label:
              node.getAttribute("aria-label") ||
              node.innerText ||
              node.getAttribute("id") ||
              node.tagName,
            width: Math.round(rect.width * 100) / 100,
            height: Math.round(rect.height * 100) / 100,
            left: Math.round(rect.left * 100) / 100,
            right: Math.round(rect.right * 100) / 100,
          };
        });
      return {
        viewport: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
        controls,
      };
    });
    expect(measurements.documentWidth).toBeLessThanOrEqual(
      measurements.viewport,
    );
    expect(measurements.bodyWidth).toBeLessThanOrEqual(measurements.viewport);
    expect(
      measurements.controls.filter(
        (control) =>
          control.width < 44 ||
          control.height < 44 ||
          control.left < -0.5 ||
          control.right > measurements.viewport + 0.5,
      ),
    ).toEqual([]);

    const skipLink = page.getByRole("link", {
      name: "Skip to Reality Receipts",
      exact: true,
    });
    await page.reload();
    await page.keyboard.press("Tab");
    await expect(skipLink).toBeFocused();
    const skipBox = await skipLink.boundingBox();
    expect(skipBox.height).toBeGreaterThanOrEqual(44);
    expect(skipBox.y).toBeGreaterThanOrEqual(0);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#main$/);
    await expect(page.locator("#main")).toBeFocused();

    await page.locator("#observation-note").fill(privateMarker);
    await page
      .locator("#claim")
      .fill(`Public notice check ${crypto.randomUUID()}.`);
    let completed = false;
    for (let attempt = 0; attempt < 48; attempt += 1) {
      await runWorkflow(page);
      const state = await page
        .locator('[data-stage="field_evidence"]')
        .getAttribute("data-state");
      if (state !== "skipped") {
        await expect(page.locator('.stage[data-state="error"]')).toHaveCount(0);
        await expect(page.locator("#receipt-content")).toBeVisible();
        completed = true;
        break;
      }
      await page.locator("#reset-button").click();
    }
    expect(completed).toBe(true);
    expect(
      await page.locator("#receipt-content").evaluate((node) => {
        const rect = node.getBoundingClientRect();
        return rect.right <= innerWidth && rect.left >= 0;
      }),
    ).toBe(true);

    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".site-header")).toBeHidden();
    await expect(page.locator(".composer")).toBeHidden();
    await expect(page.locator(".workflow")).toBeHidden();
    await expect(page.locator(".receipt-actions")).toBeHidden();
    await expect(page.locator("#receipt-content")).toBeVisible();
    await expect(page.locator("#receipt-content")).toContainText(
      "Simulated settlement",
    );
    await expect(page.locator("#receipt-content")).toContainText(
      "Remote context is not cryptographic proof.",
    );
    const pdf = await page.pdf({
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
    });
    expect(pdf.byteLength).toBeGreaterThan(5_000);
    const receiptText = await page.locator("#receipt-content").textContent();
    expect(receiptText).not.toContain(privateMarker);
  });
});
