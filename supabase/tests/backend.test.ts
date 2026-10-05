import assert from "node:assert/strict";
import { test } from "node:test";
import { SupabaseArchiveBackend, serviceKey } from "../functions/bobi-archive-next/backend.ts";
import { BUCKET, MAX_BYTES } from "../functions/bobi-archive-next/handler.ts";

test("modern keys are apikey-only; legacy JWTs get bearer as well", async () => {
  assert.equal(serviceKey((name) => name === "SUPABASE_SECRET_KEYS" ? '{"default":"sb_secret_fixture"}' : undefined), "sb_secret_fixture");
  assert.throws(() => serviceKey(() => "invalid"), /archive_configuration_invalid/);
  for (const key of ["sb_secret_fixture", "eyJfixture.e30.signature"]) {
    let headers!: Headers;
    const backend = new SupabaseArchiveBackend("https://archive-dev.example", key, async (_url, init) => {
      headers = new Headers(init?.headers);
      return Response.json([]);
    });
    assert.equal(await backend.authenticate("a".repeat(64)), null);
    assert.equal(headers.get("apikey"), key);
    assert.equal(headers.get("authorization"), key.startsWith("sb_secret_") ? null : `Bearer ${key}`);
  }
  assert.throws(() => new SupabaseArchiveBackend("http://remote.example", "sb_secret_fixture"), /archive_configuration_invalid/);
  assert.throws(() => new SupabaseArchiveBackend("https://name:secret@archive-dev.example", "sb_secret_fixture"), /archive_configuration_invalid/);
});

test("signed URL is limited to the exact private object and TTL is sent to Storage", async () => {
  const path = `${"a".repeat(64)}/bobi2_${"b".repeat(48)}/${"c".repeat(64)}`;
  let body = "";
  const backend = new SupabaseArchiveBackend("https://archive-dev.example", "sb_secret_fixture", async (_url, init) => {
    body = String(init?.body);
    return Response.json({ signedURL: `/object/sign/${BUCKET}/${path}?token=fixture` });
  });
  assert.equal(await backend.sign(path, 900), `https://archive-dev.example/storage/v1/object/sign/${BUCKET}/${path}?token=fixture`);
  assert.deepEqual(JSON.parse(body), { expiresIn: 900 });
  const bad = new SupabaseArchiveBackend("https://archive-dev.example", "sb_secret_fixture", async () => Response.json({ signedURL: `/object/sign/${BUCKET}/other?token=fixture` }));
  await assert.rejects(bad.sign(path, 30), /archive_backend_invalid/);
});

test("download bytes and response JSON are bounded; upstream errors do not escape", async () => {
  const backend = new SupabaseArchiveBackend("https://archive-dev.example", "sb_secret_fixture", async () => new Response(new Uint8Array(MAX_BYTES + 1)));
  await assert.rejects(backend.read("private-path"), /archive_too_large/);
  const bad = new SupabaseArchiveBackend("https://archive-dev.example", "sb_secret_fixture", async () => new Response("secret-upstream-response", { status: 500 }));
  await assert.rejects(bad.authenticate("a".repeat(64)), /^Error: archive_unavailable$/);
});
