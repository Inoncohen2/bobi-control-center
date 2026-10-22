# Bobi Guardian Vault — Phase 1

This is the encrypted storage primitive only. It does not yet authenticate Home
Assistant integrations or perform re-authentication.

## Security contract

- The encryption key is provisioned separately as `BOBI_VAULT_KEY`, generated
  with `cryptography.fernet.Fernet.generate_key()`.
- The key is not generated automatically, stored beside the vault, returned from
  any API, or written to logs. Missing/invalid key means the vault stays locked.
- The vault file is authenticated encrypted ciphertext, atomically replaced,
  and created with owner-only permissions where supported.
- The only public-facing operation planned for the API is listing metadata.
  Secret retrieval is an internal service method for a future narrowly scoped
  credential broker; no generic endpoint may return secret values.
- Do not send passwords or MFA codes through the LLM. A future UI must submit
  secrets directly to a protected backend endpoint, and that endpoint must not
  log request bodies.
- This protects secrets at rest against accidental file disclosure. It does not
  protect against a fully compromised Home Assistant host or a compromised
  running process. For stronger isolation, provision the key from an external
  secret manager or hardware-backed service.

## Not yet enabled

This module is not wired to live integration flows, does not alter Home
Assistant configuration, and must not be treated as automatic recovery. The
next phase adds an authenticated, admin-only management API and tests; later
work adds per-integration adapters only where official re-auth flows exist.
