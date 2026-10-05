# Bobi Next private archive provider

Development implementation, **not deployed**. It is independent of production
`bobi-storage`, voucher tables and voucher media. No workflow applies migrations
or deploys functions. The default Bobi archive provider remains local.

`bobi-archive-next` accepts the existing `BobiStorageClient` JSON envelope with
`x-bobi-token`. It implements only `ping`, `archive.media.upload` and
`archive.media.signed_url`. Receiving media, OCR and AI do not authorize saving:
the Bobi conversation authority/policy checks must run before this adapter.

| Boundary | Behavior |
| --- | --- |
| Installation | A separate high-entropy token per installation; only its SHA-256 is stored in Supabase. Enabled token lookup chooses the installation, never request metadata. |
| Owner | Bobi supplies its opaque `bobi2_…` subject after local user/policy resolution. The installation token is trusted to select owners within that installation. |
| Binary storage | Private `bobi-next-archive` bucket; immutable installation-hash/subject/SHA paths; no filename/path override or public URL. |
| Integrity | Claimed SHA, stored byte count and read-after-upload SHA must match before the SQL object becomes ready. |
| Retry | Atomic SQL claim and five-minute lease; every idempotency key stays bound to its digest. Existing bytes are verified, never overwritten. |
| Access | New tables and RPCs allow only `service_role`; RLS has no client policies. A restrictive Storage policy protects this bucket even if legacy permissive policies exist. |
| Retrieval | Exact installation + subject + object ID + ready state; signed URL TTL 30–900 seconds, same project and exact private path. Revocation cannot revoke URLs already signed; their bounded TTL applies. |
| Secrets | Service keys stay inside the Edge environment. Only the installation token belongs in Bobi's encrypted secret vault. Modern keys use `apikey` only; legacy JWT service keys also use Bearer. |

Limits: 10 MiB decoded media; bounded streamed JSON/body and download bytes;
explicit document, image and audio MIME allowlist. Cloud selection fails closed;
there is no automatic local fallback after a cloud error. Search, category,
soft deletion and restore metadata remain in Bobi's SQLite ArchiveStore.

## Isolated checks

```sh
npm ci --prefix supabase --ignore-scripts
npm test --prefix supabase
cd bobi_control_center/backend
BOBI_ARCHIVE_PROVIDER_CONTRACT=1 python -m pytest -q tests/test_bobi_next_archive_provider_contract.py
```

Node 22+ is required. PGlite evaluates the actual migration/RLS/claim functions in
embedded Postgres. The actual TypeScript handler and REST backend run against
that database with mocked Storage HTTP. CI also checks the Edge entrypoint with
Deno 2.9.6. The Python test uses the real client,
ArchiveCapture and ArchiveStore over loopback. These are isolated contract tests,
not a hosted Supabase, WAHA, Home Assistant or Deno runtime E2E proof.

## Controlled development rollout (still pending)

1. Select a separate development Supabase project/branch explicitly. The current
   production project has no development branch; do not apply these files there.
2. Review the migration generated with Supabase CLI `2.119.0`. Use the connected
   Supabase tools to apply it to that development target, then deploy only
   `bobi-archive-next`. Keep `verify_jwt=false`: the function itself checks the
   per-installation token before reading the body. No Supabase key goes to Bobi.
3. A trusted administrator generates a token with at least 32 random bytes and
   registers its SHA-256 in `bobi_next_archive_installations`, alongside the
   installation ID from Bobi SetupStore. Never place plaintext tokens in SQL,
   source, command arguments, migration files, logs, issue text or CI secrets.
   Token provisioning/onboarding automation is a separate remaining task.
4. Configure the development Bobi archive endpoint/token, explicitly enable its
   archive capability and select cloud mode. Keep the voucher integration separate.
5. Verify hosted upload/read/hash, private-bucket denial, owner/installation
   isolation, duplicate requests, interrupted uploads, disabled token, outage and
   signed URL expiry. Run actual Deno/Storage tests before claiming cloud parity.
6. Any production Supabase schema/function deployment still requires the user's
   explicit permission. No HA cutover, app release or production version bump is
   part of this provider change.

Official references: [private Storage buckets](https://supabase.com/docs/guides/storage/buckets/fundamentals),
[new API keys](https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys),
[Edge secrets](https://supabase.com/docs/guides/functions/secrets),
[Storage REST contract](https://github.com/supabase/storage-js/blob/main/src/packages/StorageFileApi.ts).
