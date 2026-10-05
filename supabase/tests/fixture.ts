import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";
import { SupabaseArchiveBackend } from "../functions/bobi-archive-next/backend.ts";
import { BUCKET, createArchiveHandler, sha256 } from "../functions/bobi-archive-next/handler.ts";
import type { UploadInput } from "../functions/bobi-archive-next/handler.ts";

export const TOKEN_A = "a".repeat(40);
export const TOKEN_B = "b".repeat(40);
export const SUBJECT_A = `bobi2_${"a".repeat(48)}`;
export const SUBJECT_B = `bobi2_${"b".repeat(48)}`;
export const PDF = new TextEncoder().encode("%PDF-1.4\narchive contract fixture\n%%EOF");
export const MIGRATION = new URL("../migrations/20261005042146_bobi_next_archive_provider.sql", import.meta.url);

export async function database(): Promise<PGlite> {
  const db = new PGlite();
  // Minimal Storage table shapes only. Real Postgres evaluates the migration,
  // constraints, roles, RLS, functions and transactions; Storage HTTP is mocked.
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema storage;
    create table storage.buckets (id text primary key, name text, public boolean,
      file_size_limit bigint, allowed_mime_types text[]);
    create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text, name text);
    alter table storage.objects enable row level security;
    grant usage on schema public, storage to anon, authenticated, service_role;
    grant all on storage.objects to anon, authenticated, service_role;
    create policy legacy_open on storage.objects for all to anon, authenticated using (true) with check (true);
  `);
  await db.exec(await readFile(MIGRATION, "utf8"));
  await db.query("insert into public.bobi_next_archive_installations (installation_id, token_sha256) values ($1, $2), ($3, $4)", [
    "installation-a", await sha256(new TextEncoder().encode(TOKEN_A)),
    "installation-b", await sha256(new TextEncoder().encode(TOKEN_B)),
  ]);
  return db;
}

export async function uploadPayload(bytes: Uint8Array = PDF, key = "fixture-key"): Promise<Record<string, unknown>> {
  return {
    media_base64: Buffer.from(bytes).toString("base64"), filename: "insurance.pdf", mime_type: "application/pdf",
    sha256: await sha256(bytes), idempotency_key: key,
  };
}

export async function input(bytes: Uint8Array = PDF, key = "fixture-key"): Promise<UploadInput> {
  return { sha256: await sha256(bytes), size_bytes: bytes.length, filename: "insurance.pdf", mime_type: "application/pdf", idempotency_key: key };
}

export function request(op: string, payload: Record<string, unknown>, token = TOKEN_A, subject = SUBJECT_A): Request {
  return new Request("https://archive-dev.example/functions/v1/bobi-archive-next", {
    method: "POST", headers: { "x-bobi-token": token, "content-type": "application/json" },
    body: JSON.stringify({ op, external_id: subject, payload }),
  });
}

export async function fixture(base = "https://archive-dev.example") {
  const db = await database();
  const blobs = new Map<string, Uint8Array>();
  const calls: { path: string; method: string; headers: Headers }[] = [];
  const signedTTLs: number[] = [];
  const faults: {
    beforePut?: () => Promise<void>;
    failPut?: boolean;
    corruptRead?: boolean;
    failCompleteOnce?: boolean;
    signOverride?: string;
  } = {};
  const transport: typeof fetch = async (url, init) => {
    const req = new Request(url, init);
    const u = new URL(req.url);
    calls.push({ path: u.pathname, method: req.method, headers: req.headers });
    if (req.redirect !== "error") throw new Error("redirect protection missing");
    const params = u.searchParams;
    const eq = (name: string) => params.get(name)?.replace(/^eq\./, "") ?? null;
    if (u.pathname === "/rest/v1/bobi_next_archive_installations") {
      if (params.get("enabled") !== "eq.true") throw new Error("enabled scope missing");
      const result = await db.query("select installation_id from public.bobi_next_archive_installations where token_sha256 = $1 and enabled", [eq("token_sha256")]);
      return Response.json(result.rows);
    }
    if (u.pathname === "/rest/v1/bobi_next_archive_objects") {
      if (params.get("state") !== "eq.ready") throw new Error("ready scope missing");
      const result = await db.query(`select id, object_path, sha256, size_bytes, mime_type, filename
        from public.bobi_next_archive_objects where installation_id = $1 and external_id = $2 and id = $3 and state = 'ready'`,
      [eq("installation_id"), eq("external_id"), eq("id")]);
      return Response.json(result.rows);
    }
    if (u.pathname.startsWith("/rest/v1/rpc/")) {
      const p = await req.json();
      let result;
      if (u.pathname.endsWith("bobi_next_archive_claim")) {
        result = await db.query("select public.bobi_next_archive_claim($1,$2,$3,$4,$5,$6,$7,$8) as result", [
          p.p_installation, p.p_subject, p.p_sha256, p.p_size, p.p_mime, p.p_filename, p.p_key, p.p_lease,
        ]);
      } else if (u.pathname.endsWith("bobi_next_archive_complete")) {
        if (faults.failCompleteOnce) { faults.failCompleteOnce = false; return Response.json({ error: "simulated crash" }, { status: 503 }); }
        result = await db.query("select public.bobi_next_archive_complete($1,$2,$3,$4) as result", [p.p_installation, p.p_subject, p.p_id, p.p_lease]);
      } else if (u.pathname.endsWith("bobi_next_archive_release")) {
        result = await db.query("select public.bobi_next_archive_release($1,$2,$3,$4) as result", [p.p_installation, p.p_subject, p.p_id, p.p_lease]);
      } else throw new Error("unrecognized RPC");
      return Response.json((result.rows[0] as { result: unknown }).result);
    }
    const sign = `/storage/v1/object/sign/${BUCKET}/`;
    if (u.pathname.startsWith(sign)) {
      const path = u.pathname.slice(sign.length);
      if (!blobs.has(path)) return Response.json({}, { status: 404 });
      signedTTLs.push((await req.json()).expiresIn);
      return Response.json({ signedURL: faults.signOverride ?? `/object/sign/${BUCKET}/${path}?token=fixture-signed` });
    }
    const prefix = `/storage/v1/object/${BUCKET}/`;
    if (u.pathname.startsWith(prefix)) {
      const path = u.pathname.slice(prefix.length);
      if (req.method === "POST") {
        await faults.beforePut?.();
        if (faults.failPut) return Response.json({ leaked: TOKEN_A }, { status: 503 });
        if (req.headers.get("x-upsert") !== "false") throw new Error("overwrite attempted");
        if (blobs.has(path)) return Response.json({ statusCode: "409" }, { status: 400 });
        blobs.set(path, new Uint8Array(await req.arrayBuffer()));
        return Response.json({ Key: `${BUCKET}/${path}` });
      }
      const bytes = blobs.get(path);
      if (!bytes) return new Response(null, { status: 404 });
      return new Response(Buffer.from(faults.corruptRead ? [0, 1, 2] : bytes));
    }
    throw new Error(`unrecognized fixture route: ${u.pathname}`);
  };
  const backend = new SupabaseArchiveBackend(base, "sb_secret_test_fixture", transport);
  return { db, blobs, calls, faults, signedTTLs, backend, handler: createArchiveHandler(backend) };
}
