# Bobi Guardian Vault — Phase 1

Phase 1 adds an encrypted storage primitive and a small admin-only API to Bobi
Control Center. It does not yet authenticate Home Assistant integrations or
perform re-authentication, and it is not deployed to the live Home Assistant.

## Security contract

- The encryption key must be provisioned separately as `BOBI_VAULT_KEY`, using
  a key generated with `cryptography.fernet.Fernet.generate_key()`.
- The key is never generated automatically, stored beside the ciphertext,
  returned from an API, or written to logs. Missing/invalid key leaves the vault
  locked. No key is configured in this PR.
- Vault entries use authenticated encryption. The encrypted file is written
  atomically and with owner-only permissions where supported.
- `GET /api/bobi/vault/status` reports whether the vault is unlocked.
  `GET /api/bobi/vault/entries` returns metadata only. An admin can add a
  credential via `POST /api/bobi/vault/entries`; the response never includes
  its value. Overwriting existing names is rejected. Deletion is not exposed
  until a separate approval flow exists.
- Requests are protected by Bobi's existing ingress/external authentication and
  admin-role checks. Request validation responses report field names only, not
  submitted values.
- Do not send passwords or MFA codes through the LLM or WhatsApp chat. A future
  credential-entry UI must submit them directly to this protected backend
  endpoint and must not log request bodies.
- This protects against accidental disclosure of the ciphertext file. It does
  not protect against a fully compromised Home Assistant host or a compromised
  running process. A key kept in an environment variable must be provisioned
  through a separate secure deployment mechanism.

## Not yet enabled

This module is not wired to live integration flows, and the running add-on has
not been updated. No Home Assistant configuration or integration was changed.
The next phase must safely provision the key, validate this API on a test
instance, and add integration-specific recovery adapters only where official
re-authentication flows exist.
