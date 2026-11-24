import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APPS_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../apps",
);
const MIME = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
};

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 2_000_000) throw new Error("mock request too large");
  }
  return body ? JSON.parse(body) : {};
}

export async function startServer() {
  const requests = [];
  const receipts = new Map();
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url || "/", "http://127.0.0.1");
      const method = request.method || "GET";
      let postedBody;
      if (method === "POST") {
        postedBody = await readJson(request);
        requests.push({ method, path: url.pathname, body: postedBody });
      } else {
        requests.push({ method, path: url.pathname });
      }

      if (url.pathname === "/__test__/blank") {
        response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        response.end("<!doctype html><title>Origin storage reset</title>");
        return;
      }

      if (url.pathname === "/mock/ledger/" && method === "GET") {
        json(response, 200, { observations: [] });
        return;
      }
      if (url.pathname === "/mock/ledger/health" && method === "GET") {
        json(response, 200, { status: "ok", context: false });
        return;
      }
      if (
        url.pathname === "/mock/ledger/observations/recent" &&
        method === "GET"
      ) {
        json(response, 200, { observations: [] });
        return;
      }
      if (
        url.pathname === "/mock/ledger/observations/similar" &&
        method === "GET"
      ) {
        json(response, 200, { observations: [] });
        return;
      }
      if (url.pathname === "/mock/ledger/ingest" && method === "POST") {
        json(response, 200, {
          status: "VERIFIED",
          block_id: `mock-${postedBody.blockId}`,
          milestone_index: 1,
          mode: "public",
          shielded: false,
        });
        return;
      }
      if (url.pathname === "/mock/zanchor/health" && method === "GET") {
        json(response, 200, {
          node: "ok",
          network: "regtest",
          mode: "B",
          shielded: true,
        });
        return;
      }
      if (url.pathname === "/mock/zanchor/anchor" && method === "POST") {
        const receipt = {
          commitment: postedBody.commitment,
          receipt_id: `test-${postedBody.commitment.slice(0, 16)}`,
          txid: "mock-txid",
          height: null,
          status: "queued",
          mode: "B",
          shielded: true,
        };
        receipts.set(receipt.receipt_id, receipt);
        json(response, 200, receipt);
        return;
      }
      if (
        url.pathname.startsWith("/mock/zanchor/receipts/") &&
        method === "GET"
      ) {
        const receipt = receipts.get(
          url.pathname.slice("/mock/zanchor/receipts/".length),
        );
        json(
          response,
          receipt ? 200 : 404,
          receipt || { detail: "unknown test receipt" },
        );
        return;
      }
      if (url.pathname.startsWith("/mock/")) {
        json(response, 404, { detail: "unknown mock endpoint" });
        return;
      }
      if (method !== "GET" && method !== "HEAD") {
        json(response, 405, { detail: "method not allowed" });
        return;
      }

      const pathname = decodeURIComponent(url.pathname);
      let filename = path.resolve(APPS_ROOT, `.${pathname}`);
      if (
        filename !== APPS_ROOT &&
        !filename.startsWith(`${APPS_ROOT}${path.sep}`)
      ) {
        json(response, 403, { detail: "outside apps directory" });
        return;
      }
      let info = await stat(filename);
      if (info.isDirectory()) {
        filename = path.join(filename, "index.html");
        info = await stat(filename);
      }
      if (!info.isFile()) {
        json(response, 404, { detail: "not found" });
        return;
      }
      response.writeHead(200, {
        "content-type":
          MIME[path.extname(filename)] || "application/octet-stream",
        "content-length": info.size,
        "cache-control": "no-store",
      });
      if (method === "HEAD") {
        response.end();
        return;
      }
      createReadStream(filename).pipe(response);
    } catch (error) {
      if (!response.headersSent) {
        json(response, error.code === "ENOENT" ? 404 : 500, {
          detail: error instanceof Error ? error.message : String(error),
        });
      } else {
        response.destroy(error);
      }
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return {
    origin: `http://127.0.0.1:${address.port}`,
    posts() {
      return requests.filter((entry) => entry.method === "POST");
    },
    async close() {
      await new Promise((resolve) => {
        server.close(resolve);
        server.closeAllConnections();
      });
    },
  };
}
