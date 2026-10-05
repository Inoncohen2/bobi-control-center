/** Installation-authenticated archive protocol; no voucher or HA operations. */
export const MAX_BYTES = 10 * 1024 * 1024;
export const MAX_BODY_BYTES = Math.ceil(MAX_BYTES / 3) * 4 + 16 * 1024;
export const BUCKET = "bobi-next-archive";
export const ALLOWED_MIMES = new Set([
  "application/pdf", "text/plain", "text/csv", "application/json",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif",
  "audio/ogg", "audio/opus", "audio/mpeg", "audio/mp4", "audio/aac",
  "audio/wav", "audio/x-wav", "audio/webm",
]);

export class ArchiveError extends Error {
  status: number;
  constructor(status: number, code: string) {
    super(code);
    this.status = status;
  }
}

export interface ArchiveObject {
  id: string;
  object_path: string;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  filename: string;
}

export interface UploadInput {
  sha256: string;
  size_bytes: number;
  mime_type: string;
  filename: string;
  idempotency_key: string;
}

export interface Claim {
  status: "claimed" | "ready" | "busy" | "conflict" | "disabled";
  media?: ArchiveObject;
}

export interface ArchiveBackend {
  authenticate(tokenHash: string): Promise<string | null>;
  claim(installation: string, subject: string, input: UploadInput, lease: string): Promise<Claim>;
  complete(installation: string, subject: string, id: string, lease: string): Promise<boolean>;
  release(installation: string, subject: string, id: string, lease: string): Promise<void>;
  find(installation: string, subject: string, id: string): Promise<ArchiveObject | null>;
  put(path: string, mime: string, bytes: Uint8Array): Promise<void>;
  read(path: string): Promise<Uint8Array>;
  sign(path: string, expiresIn: number): Promise<string>;
}

export async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", Uint8Array.from(bytes));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Bound actual streamed bytes as well as Content-Length. */
export async function boundedBytes(response: Request | Response, limit: number): Promise<Uint8Array> {
  const length = response.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > limit)) {
    throw new ArchiveError(413, "archive_too_large");
  }
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new ArchiveError(413, "archive_too_large");
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ArchiveError(400, "archive_request_invalid");
  }
  return value as Record<string, unknown>;
}

function onlyKeys(value: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(value).some((key) => !keys.includes(key))) {
    throw new ArchiveError(400, "archive_request_invalid");
  }
}

function string(value: unknown, pattern: RegExp): string {
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new ArchiveError(400, "archive_request_invalid");
  }
  return value;
}

function decodeBase64(value: unknown): Uint8Array {
  if (typeof value !== "string" || !value.length || value.length % 4 !== 0) {
    throw new ArchiveError(400, "archive_media_invalid");
  }
  if (value.length > Math.ceil(MAX_BYTES / 3) * 4) {
    throw new ArchiveError(413, "archive_too_large");
  }
  // Avoid a repeated-group regexp on multi-megabyte attachments: V8 can
  // exhaust its regexp stack even on a valid file at the allowed limit.
  if (/[^A-Za-z0-9+/=]/.test(value)) throw new ArchiveError(400, "archive_media_invalid");
  let decoded: string;
  try { decoded = atob(value); }
  catch { throw new ArchiveError(400, "archive_media_invalid"); }
  if (btoa(decoded) !== value) throw new ArchiveError(400, "archive_media_invalid");
  if (decoded.length > MAX_BYTES) throw new ArchiveError(413, "archive_too_large");
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}

function reply(status: number, payload: Record<string, unknown>): Response {
  return Response.json(payload, { status, headers: { "cache-control": "no-store" } });
}

async function checkScope(media: ArchiveObject, installation: string, subject: string): Promise<void> {
  const tenant = await sha256(new TextEncoder().encode(installation));
  if (media.object_path !== `${tenant}/${subject}/${media.sha256}`) {
    throw new ArchiveError(503, "archive_integrity_failed");
  }
}

export function createArchiveHandler(backend: ArchiveBackend): (request: Request) => Promise<Response> {
  return async (request) => {
    try {
      if (request.method !== "POST") return reply(405, { ok: false, error: "method_not_allowed" });
      const token = request.headers.get("x-bobi-token") ?? "";
      if (token.length < 32 || token.length > 512 || !/^[\x21-\x7e]+$/.test(token)) {
        throw new ArchiveError(401, "unauthorized");
      }
      // Authenticate before reading the body. Caller-supplied installation IDs
      // never select a tenant, and plaintext installation tokens never persist.
      const installation = await backend.authenticate(await sha256(new TextEncoder().encode(token)));
      if (!installation) throw new ArchiveError(401, "unauthorized");
      if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
        throw new ArchiveError(415, "archive_content_type_invalid");
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await boundedBytes(request, MAX_BODY_BYTES)));
      } catch (error) {
        if (error instanceof ArchiveError) throw error;
        throw new ArchiveError(400, "archive_request_invalid");
      }
      const body = record(parsed);
      onlyKeys(body, ["op", "external_id", "payload"]);
      const payload = record(body.payload ?? {});
      if (body.op === "ping") {
        onlyKeys(payload, []);
        return reply(200, { ok: true, provider: "bobi-archive-next", archive_enabled: true });
      }
      const subject = string(body.external_id, /^bobi2_[a-f0-9]{48}$/);
      if (body.op === "archive.media.upload") {
        onlyKeys(payload, ["media_base64", "filename", "mime_type", "sha256", "idempotency_key"]);
        const digest = string(payload.sha256, /^[a-f0-9]{64}$/);
        const idempotencyKey = string(payload.idempotency_key, /^[A-Za-z0-9._:-]{1,128}$/);
        const mime = typeof payload.mime_type === "string" ? payload.mime_type.trim().toLowerCase() : "";
        if (!ALLOWED_MIMES.has(mime)) throw new ArchiveError(415, "archive_mime_not_allowed");
        if (typeof payload.filename !== "string" || payload.filename.length > 255) {
          throw new ArchiveError(400, "archive_request_invalid");
        }
        const filename = payload.filename.replace(/\\/g, "/").split("/").pop()?.replace(/[\x00-\x1f\x7f]/g, "_").trim() || "attachment";
        const bytes = decodeBase64(payload.media_base64);
        if (await sha256(bytes) !== digest) throw new ArchiveError(400, "archive_sha256_mismatch");
        const input = { sha256: digest, size_bytes: bytes.length, mime_type: mime, filename, idempotency_key: idempotencyKey };
        const lease = crypto.randomUUID();
        const claim = await backend.claim(installation, subject, input, lease);
        if (claim.status === "disabled") throw new ArchiveError(401, "unauthorized");
        if (claim.status === "conflict") throw new ArchiveError(409, "archive_idempotency_conflict");
        if (claim.status === "busy") throw new ArchiveError(409, "archive_upload_busy");
        const media = claim.media;
        if (!media || media.sha256 !== digest || media.size_bytes !== bytes.length) {
          throw new ArchiveError(503, "archive_integrity_failed");
        }
        await checkScope(media, installation, subject);
        if (claim.status === "claimed") {
          try {
            // No overwrite: a crash after upload is recovered by verifying the
            // same immutable object, not by deleting or replacing another claim.
            await backend.put(media.object_path, media.mime_type, bytes);
            const stored = await backend.read(media.object_path);
            if (stored.length !== media.size_bytes || await sha256(stored) !== digest) {
              throw new ArchiveError(503, "archive_integrity_failed");
            }
            if (!await backend.complete(installation, subject, media.id, lease)) {
              throw new ArchiveError(409, "archive_upload_busy");
            }
          } catch (error) {
            await backend.release(installation, subject, media.id, lease).catch(() => {});
            throw error;
          }
        }
        return reply(200, { ok: true, media: { id: media.id, sha256: media.sha256, size_bytes: media.size_bytes } });
      }
      if (body.op === "archive.media.signed_url") {
        onlyKeys(payload, ["media_id", "expires_in"]);
        const id = string(payload.media_id, /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/);
        const requested = payload.expires_in ?? 300;
        if (typeof requested !== "number" || !Number.isInteger(requested)) {
          throw new ArchiveError(400, "archive_request_invalid");
        }
        const media = await backend.find(installation, subject, id);
        if (!media) throw new ArchiveError(404, "archive_not_found");
        if (media.id !== id) throw new ArchiveError(503, "archive_integrity_failed");
        await checkScope(media, installation, subject);
        const expiresIn = Math.max(30, Math.min(requested, 900));
        return reply(200, { ok: true, signed_url: await backend.sign(media.object_path, expiresIn) });
      }
      throw new ArchiveError(400, "archive_operation_not_supported");
    } catch (error) {
      // Never return transport bodies, URLs, headers, tokens, or stack traces.
      if (error instanceof ArchiveError) return reply(error.status, { ok: false, error: error.message });
      return reply(503, { ok: false, error: "archive_unavailable" });
    }
  };
}
