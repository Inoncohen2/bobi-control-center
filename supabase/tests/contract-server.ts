/** Loopback-only fixture for the real Python client. Never an Edge entrypoint. */
import { createServer } from "node:http";
import { once } from "node:events";
import { BUCKET } from "../functions/bobi-archive-next/handler.ts";
import { fixture } from "./fixture.ts";

let f: Awaited<ReturnType<typeof fixture>>;
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    const prefix = `/storage/v1/object/sign/${BUCKET}/`;
    if (req.method === "GET" && url.pathname.startsWith(prefix) && url.searchParams.get("token") === "fixture-signed") {
      const bytes = f.blobs.get(url.pathname.slice(prefix.length));
      if (!bytes) { res.writeHead(404).end(); return; }
      res.writeHead(200, { "content-length": bytes.length, "content-type": "application/pdf" }).end(bytes);
      return;
    }
    if (url.pathname !== "/functions/v1/bobi-archive-next") { res.writeHead(404).end(); return; }
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 64 * 1024) { res.writeHead(413).end(); return; }
      chunks.push(chunk);
    }
    const headers = new Headers();
    for (const [name, value] of Object.entries(req.headers)) {
      if (typeof value === "string") headers.set(name, value);
    }
    const response = await f.handler(new Request(`http://127.0.0.1${url.pathname}`, {
      method: req.method ?? "POST", headers, body: Buffer.concat(chunks),
    }));
    res.writeHead(response.status, Object.fromEntries(response.headers)).end(Buffer.from(await response.arrayBuffer()));
  } catch {
    res.writeHead(503).end('{"ok":false,"error":"fixture_unavailable"}');
  }
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
const address = server.address();
if (!address || typeof address === "string") throw new Error("loopback address unavailable");
f = await fixture(`http://127.0.0.1:${address.port}`);
process.stdout.write(`${JSON.stringify({ port: address.port })}\n`);
process.on("SIGTERM", () => {
  server.close(() => { void f.db.close().then(() => process.exit(0)); });
  server.closeAllConnections();
});
