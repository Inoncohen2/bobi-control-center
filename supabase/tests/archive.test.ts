import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { MAX_BODY_BYTES, MAX_BYTES, createArchiveHandler } from "../functions/bobi-archive-next/handler.ts";
import { PDF, SUBJECT_A, SUBJECT_B, TOKEN_A, TOKEN_B, fixture, request, uploadPayload } from "./fixture.ts";

let f: Awaited<ReturnType<typeof fixture>>;
before(async () => { f = await fixture(); });
after(async () => { await f.db.close(); });

test("actual handler + REST backend + SQL upload, owner isolation and signed URL", async () => {
  const saved = await f.handler(request("archive.media.upload", await uploadPayload()));
  assert.equal(saved.status, 200);
  assert.equal(saved.headers.get("cache-control"), "no-store");
  const { media } = await saved.json();
  assert.deepEqual(Object.keys(media).sort(), ["id", "sha256", "size_bytes"]);
  assert.equal(media.size_bytes, PDF.length);
  assert.equal(f.blobs.size, 1);
  const writes = f.calls.filter((call) => call.path.startsWith("/storage/v1/object/") && call.method === "POST").length;
  const duplicate = await f.handler(request("archive.media.upload", await uploadPayload(PDF, "second-key")));
  assert.equal((await duplicate.json()).media.id, media.id);
  assert.equal(f.calls.filter((call) => call.path.startsWith("/storage/v1/object/") && call.method === "POST").length, writes);
  const conflict = await f.handler(request("archive.media.upload", await uploadPayload(new Uint8Array([1, 2]), "second-key")));
  assert.equal(conflict.status, 409);
  assert.equal((await conflict.json()).error, "archive_idempotency_conflict");

  for (const [token, subject] of [[TOKEN_A, SUBJECT_B], [TOKEN_B, SUBJECT_A]]) {
    const denied = await f.handler(request("archive.media.signed_url", { media_id: media.id }, token, subject));
    assert.equal(denied.status, 404);
  }
  const signed = await f.handler(request("archive.media.signed_url", { media_id: media.id, expires_in: 5000 }));
  assert.equal(signed.status, 200);
  assert.equal(f.signedTTLs.at(-1), 900);
  assert.equal((await f.handler(request("archive.media.signed_url", { media_id: media.id, expires_in: 1 }))).status, 200);
  assert.equal(f.signedTTLs.at(-1), 30);
  assert.match((await signed.json()).signed_url, /^https:\/\/archive-dev\.example\/storage\/v1\/object\/sign\/bobi-next-archive\//);
  assert.ok(f.calls.every((call) => call.headers.get("apikey") === "sb_secret_test_fixture" && !call.headers.has("authorization") && !call.headers.has("x-bobi-token")));

  const otherOwner = await f.handler(request("archive.media.upload", await uploadPayload(), TOKEN_A, SUBJECT_B));
  const otherTenant = await f.handler(request("archive.media.upload", await uploadPayload(), TOKEN_B, SUBJECT_A));
  assert.notEqual((await otherOwner.json()).media.id, media.id);
  assert.notEqual((await otherTenant.json()).media.id, media.id);
  assert.equal(f.blobs.size, 3);
});

test("auth is checked before the body and disabled tokens cannot sign or upload", async () => {
  const req = new Request("https://archive-dev.example", {
    method: "POST", headers: { "x-bobi-token": "invalid", "content-type": "application/json" }, body: "{broken",
  });
  assert.equal((await f.handler(req)).status, 401);
  assert.equal(req.bodyUsed, false);
  await f.db.query("update public.bobi_next_archive_installations set enabled = false where installation_id = 'installation-b'");
  assert.equal((await f.handler(request("ping", {}, TOKEN_B))).status, 401);
});

test("reject unsupported operations, forged paths, MIME, digest and base64 before Storage", async () => {
  const start = f.calls.filter((call) => call.path.startsWith("/storage/")).length;
  const payload = await uploadPayload();
  const cases: [string, Record<string, unknown>, number][] = [
    ["voucher.media.upload", payload, 400],
    ["archive.media.upload", { ...payload, storage_uri: "https://attacker.example/file" }, 400],
    ["archive.media.upload", { ...payload, mime_type: "application/x-sh" }, 415],
    ["archive.media.upload", { ...payload, sha256: "0".repeat(64) }, 400],
    ["archive.media.upload", { ...payload, media_base64: "YWJj==" }, 400],
    ["archive.media.upload", { ...payload, media_base64: "Zh==" }, 400],
    ["archive.media.signed_url", { media_id: "../../other" }, 400],
    ["archive.media.signed_url", { media_id: crypto.randomUUID(), expires_in: "900" }, 400],
  ];
  for (const [op, body, status] of cases) assert.equal((await f.handler(request(op, body))).status, status);
  const envelope = new Request("https://archive-dev.example", {
    method: "POST", headers: { "content-type": "application/json", "x-bobi-token": TOKEN_A },
    body: JSON.stringify({ op: "archive.media.upload", payload, external_id: SUBJECT_A, installation_id: "installation-b" }),
  });
  assert.equal((await f.handler(envelope)).status, 400);
  assert.equal(f.calls.filter((call) => call.path.startsWith("/storage/")).length, start);
});

test("stream limits apply even with a false small Content-Length", async () => {
  const req = new Request("https://archive-dev.example", {
    method: "POST", headers: { "content-type": "application/json", "x-bobi-token": TOKEN_A, "content-length": "1" },
    body: "x".repeat(MAX_BODY_BYTES + 1),
  });
  assert.equal((await f.handler(req)).status, 413);
  const tooLarge = await uploadPayload(new Uint8Array(MAX_BYTES + 1), "too-large");
  assert.equal((await f.handler(request("archive.media.upload", tooLarge))).status, 413);
});

test("one concurrent upload owns Storage; a durable retry returns the same media", async () => {
  const isolated = await fixture();
  try {
    let entered!: () => void;
    let resume!: () => void;
    const atPut = new Promise<void>((resolve) => { entered = resolve; });
    const gate = new Promise<void>((resolve) => { resume = resolve; });
    isolated.faults.beforePut = async () => { entered(); await gate; };
    const first = isolated.handler(request("archive.media.upload", await uploadPayload()));
    await atPut;
    const concurrent = await isolated.handler(request("archive.media.upload", await uploadPayload()));
    assert.equal(concurrent.status, 409);
    assert.equal((await concurrent.json()).error, "archive_upload_busy");
    resume();
    assert.equal((await first).status, 200);
    const restartedHandler = createArchiveHandler(isolated.backend);
    const retry = await restartedHandler(request("archive.media.upload", await uploadPayload()));
    assert.equal(retry.status, 200);
    assert.equal(isolated.blobs.size, 1);
  } finally { await isolated.db.close(); }
});

test("crash after put, corruption and storage outage cannot become ready acknowledgements", async () => {
  const isolated = await fixture();
  try {
    const payload = await uploadPayload();
    isolated.faults.failPut = true;
    const failed = await isolated.handler(request("archive.media.upload", payload));
    assert.equal(failed.status, 503);
    assert.ok(!(await failed.text()).includes(TOKEN_A));
    isolated.faults.failPut = false;
    isolated.faults.failCompleteOnce = true;
    assert.equal((await isolated.handler(request("archive.media.upload", payload))).status, 503);
    assert.equal(isolated.blobs.size, 1);
    const pending = await isolated.db.query("select state, lease_owner from public.bobi_next_archive_objects");
    assert.deepEqual(pending.rows, [{ state: "pending", lease_owner: null }]);
    isolated.faults.corruptRead = true;
    assert.equal((await isolated.handler(request("archive.media.upload", payload))).status, 503);
    isolated.faults.corruptRead = false;
    const retry = await createArchiveHandler(isolated.backend)(request("archive.media.upload", payload));
    assert.equal(retry.status, 200);
    const { media } = await retry.json();
    isolated.faults.signOverride = "https://attacker.example/stolen";
    assert.equal((await isolated.handler(request("archive.media.signed_url", { media_id: media.id }))).status, 503);
    assert.equal(isolated.blobs.size, 1);
  } finally { await isolated.db.close(); }
});

test("exact 10 MiB payload is accepted without depending on OCR or file contents", async () => {
  const isolated = await fixture();
  try {
    const result = await isolated.handler(request("archive.media.upload", await uploadPayload(new Uint8Array(MAX_BYTES), "max-size")));
    assert.equal(result.status, 200);
    assert.equal((await result.json()).media.size_bytes, MAX_BYTES);
  } finally { await isolated.db.close(); }
});
