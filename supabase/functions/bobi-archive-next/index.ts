import { SupabaseArchiveBackend, serviceKey } from "./backend.ts";
import { createArchiveHandler } from "./handler.ts";

// This small declaration keeps the dependency-free Edge entrypoint typechecked
// in Node CI as well; Supabase provides the actual Deno implementation.
declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Promise<Response>): unknown;
};

let handler: (request: Request) => Promise<Response>;
try {
  handler = createArchiveHandler(new SupabaseArchiveBackend(
    Deno.env.get("SUPABASE_URL") ?? "",
    serviceKey((name) => Deno.env.get(name)),
  ));
} catch {
  handler = async () => Response.json({ ok: false, error: "archive_configuration_invalid" }, {
    status: 503, headers: { "cache-control": "no-store" },
  });
}
Deno.serve(handler);
