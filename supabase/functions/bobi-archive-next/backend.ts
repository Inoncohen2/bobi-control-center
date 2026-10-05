/** Supabase REST transport. No SDK/runtime dependency and no caller URLs. */
import { ArchiveError, BUCKET, MAX_BYTES, boundedBytes } from "./handler.ts";
import type { ArchiveBackend, ArchiveObject, Claim, UploadInput } from "./handler.ts";

type Fetch = typeof fetch;

function object(value: unknown): ArchiveObject {
  const row = value as ArchiveObject | null;
  if (!row || typeof row.id !== "string" || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(row.id) || typeof row.object_path !== "string" ||
      !/^[a-f0-9]{64}\/bobi2_[a-f0-9]{48}\/[a-f0-9]{64}$/.test(row.object_path) ||
      !/^[a-f0-9]{64}$/.test(row.sha256) || !Number.isInteger(row.size_bytes) ||
      row.size_bytes < 1 || row.size_bytes > MAX_BYTES ||
      typeof row.filename !== "string" || typeof row.mime_type !== "string") {
    throw new ArchiveError(503, "archive_backend_invalid");
  }
  return row;
}

export function serviceKey(get: (name: string) => string | undefined): string {
  const modern = get("SUPABASE_SECRET_KEYS");
  if (modern) {
    try {
      const key: unknown = JSON.parse(modern).default;
      if (typeof key === "string" && key.startsWith("sb_secret_")) return key;
    } catch { /* Configuration errors never expose environment values. */ }
    throw new ArchiveError(503, "archive_configuration_invalid");
  }
  const legacy = get("SUPABASE_SERVICE_ROLE_KEY");
  if (!legacy) throw new ArchiveError(503, "archive_configuration_invalid");
  return legacy;
}

export class SupabaseArchiveBackend implements ArchiveBackend {
  private base: URL;
  private headers: Record<string, string>;
  private transport: Fetch;

  constructor(url: string, key: string, transport: Fetch = fetch) {
    this.base = new URL(url);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(this.base.hostname) ||
      (this.base.hostname === "kong" && this.base.port === "8000");
    if ((this.base.protocol !== "https:" && !(this.base.protocol === "http:" && local)) ||
        this.base.username || this.base.password || this.base.pathname !== "/" || this.base.search || this.base.hash ||
        !(key.startsWith("sb_secret_") || /^eyJ[^.]+\.[^.]+\.[^.]+$/.test(key))) {
      throw new ArchiveError(503, "archive_configuration_invalid");
    }
    this.headers = { apikey: key };
    // Opaque modern keys belong only in apikey, not Authorization: Bearer.
    if (!key.startsWith("sb_secret_")) this.headers.authorization = `Bearer ${key}`;
    this.transport = transport;
  }

  private async call(path: string, init: RequestInit = {}): Promise<Response> {
    return await this.transport(new URL(path, this.base), {
      ...init,
      headers: { ...this.headers, ...init.headers },
      redirect: "error",
      signal: AbortSignal.timeout(15_000),
    });
  }

  private async json(path: string, payload?: Record<string, unknown>): Promise<unknown> {
    const response = await this.call(path, payload ? {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
    } : {});
    if (!response.ok) throw new ArchiveError(503, "archive_unavailable");
    try {
      return JSON.parse(new TextDecoder().decode(await boundedBytes(response, 32 * 1024)));
    } catch { throw new ArchiveError(503, "archive_backend_invalid"); }
  }

  async authenticate(tokenHash: string): Promise<string | null> {
    const query = new URLSearchParams({ select: "installation_id", token_sha256: `eq.${tokenHash}`, enabled: "eq.true", limit: "1" });
    const rows = await this.json(`/rest/v1/bobi_next_archive_installations?${query}`);
    if (!Array.isArray(rows) || rows.length > 1) throw new ArchiveError(503, "archive_backend_invalid");
    if (!rows.length) return null;
    if (typeof rows[0]?.installation_id !== "string" || !/^[A-Za-z0-9._-]{1,128}$/.test(rows[0].installation_id)) {
      throw new ArchiveError(503, "archive_backend_invalid");
    }
    return rows[0].installation_id;
  }

  async claim(installation: string, subject: string, input: UploadInput, lease: string): Promise<Claim> {
    const result = await this.json("/rest/v1/rpc/bobi_next_archive_claim", {
      p_installation: installation, p_subject: subject, p_sha256: input.sha256,
      p_size: input.size_bytes, p_mime: input.mime_type, p_filename: input.filename,
      p_key: input.idempotency_key, p_lease: lease,
    }) as Claim;
    if (!result || !["claimed", "ready", "busy", "conflict", "disabled"].includes(result.status)) {
      throw new ArchiveError(503, "archive_backend_invalid");
    }
    if (result.status === "claimed" || result.status === "ready") result.media = object(result.media);
    return result;
  }

  async complete(installation: string, subject: string, id: string, lease: string): Promise<boolean> {
    const result = await this.json("/rest/v1/rpc/bobi_next_archive_complete", {
      p_installation: installation, p_subject: subject, p_id: id, p_lease: lease,
    });
    if (typeof result !== "boolean") throw new ArchiveError(503, "archive_backend_invalid");
    return result;
  }

  async release(installation: string, subject: string, id: string, lease: string): Promise<void> {
    await this.json("/rest/v1/rpc/bobi_next_archive_release", {
      p_installation: installation, p_subject: subject, p_id: id, p_lease: lease,
    });
  }

  async find(installation: string, subject: string, id: string): Promise<ArchiveObject | null> {
    const query = new URLSearchParams({
      select: "id,object_path,sha256,size_bytes,mime_type,filename",
      installation_id: `eq.${installation}`, external_id: `eq.${subject}`, id: `eq.${id}`, state: "eq.ready", limit: "1",
    });
    const rows = await this.json(`/rest/v1/bobi_next_archive_objects?${query}`);
    if (!Array.isArray(rows) || rows.length > 1) throw new ArchiveError(503, "archive_backend_invalid");
    return rows.length ? object(rows[0]) : null;
  }

  async put(path: string, mime: string, bytes: Uint8Array): Promise<void> {
    const response = await this.call(`/storage/v1/object/${BUCKET}/${path}`, {
      method: "POST", headers: { "content-type": mime, "cache-control": "max-age=0", "x-upsert": "false" },
      body: Uint8Array.from(bytes),
    });
    if (response.ok || response.status === 409) return;
    // Some Storage versions return HTTP 400 with the duplicate's 409 in JSON.
    if (response.status === 400) {
      try {
        const error = JSON.parse(new TextDecoder().decode(await boundedBytes(response, 4096)));
        if (String(error.statusCode) === "409") return;
      } catch { /* Fail closed; no raw upstream error is returned. */ }
    }
    throw new ArchiveError(503, "archive_unavailable");
  }

  async read(path: string): Promise<Uint8Array> {
    const response = await this.call(`/storage/v1/object/${BUCKET}/${path}`);
    if (!response.ok) throw new ArchiveError(503, "archive_unavailable");
    return await boundedBytes(response, MAX_BYTES);
  }

  async sign(path: string, expiresIn: number): Promise<string> {
    const result = await this.json(`/storage/v1/object/sign/${BUCKET}/${path}`, { expiresIn }) as { signedURL?: unknown };
    const prefix = `/object/sign/${BUCKET}/${path}`;
    if (typeof result?.signedURL !== "string" || !result.signedURL.startsWith(`${prefix}?`)) {
      throw new ArchiveError(503, "archive_backend_invalid");
    }
    const url = new URL(`/storage/v1${result.signedURL}`, this.base);
    if (url.origin !== this.base.origin || url.pathname !== `/storage/v1${prefix}` || !url.searchParams.get("token")) {
      throw new ArchiveError(503, "archive_backend_invalid");
    }
    return url.href;
  }
}
