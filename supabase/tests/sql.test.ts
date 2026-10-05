import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { ALLOWED_MIMES, BUCKET, MAX_BYTES } from "../functions/bobi-archive-next/handler.ts";
import { SUBJECT_A, SUBJECT_B, fixture, input } from "./fixture.ts";

let f: Awaited<ReturnType<typeof fixture>>;
before(async () => { f = await fixture(); });
after(async () => { await f.db.close(); });

test("migration installs private bucket, RLS, service-only grants and invoker RPCs", async () => {
  const bucket = (await f.db.query<{ public: boolean; file_size_limit: number; allowed_mime_types: string[] }>(
    "select public, file_size_limit, allowed_mime_types from storage.buckets where id = $1", [BUCKET],
  )).rows[0];
  assert.equal(bucket.public, false);
  assert.equal(Number(bucket.file_size_limit), MAX_BYTES);
  assert.deepEqual([...bucket.allowed_mime_types].sort(), [...ALLOWED_MIMES].sort());
  const tables = (await f.db.query<{ relname: string; relrowsecurity: boolean }>(
    "select relname, relrowsecurity from pg_class where relname like 'bobi_next_archive_%' and relkind = 'r'",
  )).rows;
  assert.equal(tables.length, 3);
  assert.ok(tables.every((table) => table.relrowsecurity));
  for (const table of tables) {
    const grants = (await f.db.query<{ anon: boolean; authenticated: boolean; service: boolean }>(
      "select has_table_privilege('anon', $1, 'SELECT') as anon, has_table_privilege('authenticated', $1, 'SELECT') as authenticated, has_table_privilege('service_role', $1, 'SELECT') as service", [table.relname],
    )).rows[0];
    assert.deepEqual(grants, { anon: false, authenticated: false, service: true });
  }
  const functions = (await f.db.query<{ proname: string; prosecdef: boolean; allowed: boolean }>(`
    select proname, prosecdef, has_function_privilege('anon', oid, 'EXECUTE') as allowed
    from pg_proc where proname like 'bobi_next_archive_%'`)).rows;
  assert.equal(functions.length, 3);
  assert.ok(functions.every((fn) => !fn.prosecdef && !fn.allowed));
});

test("RLS still denies archive access if a future grant is accidentally added", async () => {
  await f.db.exec("grant select on public.bobi_next_archive_installations to anon, authenticated");
  for (const role of ["anon", "authenticated"]) {
    await f.db.transaction(async (tx) => {
      await tx.exec(`set local role ${role}`);
      assert.deepEqual((await tx.query("select * from public.bobi_next_archive_installations")).rows, []);
      await assert.rejects(tx.query("select public.bobi_next_archive_claim($1,$2,$3,$4,$5,$6,$7,$8)", [
        "installation-a", SUBJECT_A, "a".repeat(64), 1, "application/pdf", "a.pdf", "key", crypto.randomUUID(),
      ]), /permission denied for function/);
      // Rollback the transaction aborted by the denied RPC.
      throw new Error("expected rollback");
    }).catch((error: Error) => { assert.equal(error.message, "expected rollback"); });
  }
  await f.db.exec("revoke select on public.bobi_next_archive_installations from anon, authenticated");
});

test("restrictive Storage policy blocks this bucket even with existing broad policies", async () => {
  await f.db.query("insert into storage.objects (bucket_id, name) values ($1, 'private.pdf'), ('legacy-bucket', 'old.pdf')", [BUCKET]);
  for (const role of ["anon", "authenticated"]) {
    await f.db.transaction(async (tx) => {
      await tx.exec(`set local role ${role}`);
      assert.deepEqual((await tx.query("select name from storage.objects order by name")).rows, [{ name: "old.pdf" }]);
      assert.equal((await tx.query("update storage.objects set name = 'stolen.pdf' where bucket_id = $1 returning id", [BUCKET])).rows.length, 0);
      assert.equal((await tx.query("delete from storage.objects where bucket_id = $1 returning id", [BUCKET])).rows.length, 0);
    });
    await assert.rejects(f.db.transaction(async (tx) => {
      await tx.exec(`set local role ${role}`);
      await tx.query("insert into storage.objects (bucket_id, name) values ($1, 'forged.pdf')", [BUCKET]);
    }), /row-level security policy/);
  }
  await f.db.transaction(async (tx) => {
    await tx.exec("set local role service_role");
    assert.equal((await tx.query("select name from storage.objects where bucket_id = $1", [BUCKET])).rows.length, 1);
  });
});

test("lease ownership is tenant/owner bound and stale claims cannot complete or release", async () => {
  const upload = await input(new Uint8Array([7, 8, 9]), "lease-case");
  const oldLease = crypto.randomUUID();
  const claim = await f.backend.claim("installation-a", SUBJECT_A, upload, oldLease);
  assert.equal(claim.status, "claimed");
  const id = claim.media!.id;
  assert.equal((await f.backend.claim("installation-a", SUBJECT_A, upload, crypto.randomUUID())).status, "busy");
  assert.equal(await f.backend.complete("installation-b", SUBJECT_A, id, oldLease), false);
  assert.equal(await f.backend.complete("installation-a", SUBJECT_B, id, oldLease), false);
  await f.backend.release("installation-b", SUBJECT_A, id, oldLease);
  assert.equal((await f.backend.claim("installation-a", SUBJECT_A, upload, crypto.randomUUID())).status, "busy");
  await f.db.query("update public.bobi_next_archive_objects set lease_expires_at = now() - interval '1 second' where id = $1", [id]);
  assert.equal(await f.backend.complete("installation-a", SUBJECT_A, id, oldLease), false);
  const newLease = crypto.randomUUID();
  assert.equal((await f.backend.claim("installation-a", SUBJECT_A, upload, newLease)).status, "claimed");
  await f.backend.release("installation-a", SUBJECT_A, id, oldLease);
  assert.equal(await f.backend.complete("installation-a", SUBJECT_A, id, oldLease), false);
  assert.equal(await f.backend.complete("installation-a", SUBJECT_A, id, newLease), true);
  assert.equal((await f.backend.claim("installation-a", SUBJECT_A, upload, crypto.randomUUID())).status, "ready");
});

test("revocation during upload blocks completion and invalid inputs fail database constraints", async () => {
  const lease = crypto.randomUUID();
  const upload = await input(new Uint8Array([3, 4]), "revoke-case");
  const claim = await f.backend.claim("installation-b", SUBJECT_A, upload, lease);
  assert.equal(claim.status, "claimed");
  await f.db.query("update public.bobi_next_archive_installations set enabled = false where installation_id = 'installation-b'");
  assert.equal(await f.backend.complete("installation-b", SUBJECT_A, claim.media!.id, lease), false);
  assert.equal((await f.backend.claim("installation-b", SUBJECT_A, upload, crypto.randomUUID())).status, "disabled");
  await assert.rejects(f.backend.claim("installation-a", SUBJECT_A, { ...upload, size_bytes: MAX_BYTES + 1 }, lease), /check constraint/);
  await assert.rejects(f.backend.claim("installation-a", "../../other", upload, lease), /check constraint/);
});
