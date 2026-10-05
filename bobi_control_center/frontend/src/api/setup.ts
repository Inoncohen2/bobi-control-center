import { api } from '@/api/client';

export type SetupRole = 'owner' | 'admin' | 'member' | 'guest';
export type AICapability = 'intent' | 'chat' | 'audio' | 'vision' | 'embeddings';

export interface SetupPolicy {
  allowed_capabilities: string[];
  denied_capabilities: string[];
  allowed_domains: string[];
  denied_actions: string[];
  max_without_approval: 10 | 20 | 30 | 40;
  can_approve: boolean;
}

export interface SetupProvider {
  provider_key: string;
  provider_type: string;
  display_name: string;
  enabled: boolean;
  session: string;
  engine: string;
  has_secret_ref: boolean;
  webhook_hmac_ready?: boolean;
}

export interface SetupAIProvider {
  provider_key: string;
  provider_type: string;
  display_name: string;
  model: string;
  enabled: boolean;
  capabilities: AICapability[];
  has_secret_ref: boolean;
}

export interface SetupUser {
  user_key: string;
  display_name: string;
  role: SetupRole;
  enabled: boolean;
  policy: SetupPolicy;
}

export type ArchiveStorageMode = 'local' | 'cloud';

export interface ArchiveSetupSnapshot {
  mode: ArchiveStorageMode;
  ready: boolean;
  cloud: {
    configured: boolean;
    ready: boolean;
    integration_key: string;
    endpoint: string;
    has_secret: boolean;
    reason: string;
    checked_ts: number;
    check_fresh: boolean;
  };
}

export interface ArchiveIntegrationInput {
  integration_key: string;
  integration_type: 'bobi_archive';
  display_name: string;
  endpoint: string;
  enabled: boolean;
  secret_value?: string;
  config: { archive_enabled: true };
}

export interface SetupIntegration {
  integration_key: string;
  integration_type: string;
  display_name: string;
  enabled: boolean;
  endpoint: string;
  has_secret_ref: boolean;
}

export interface SetupSnapshot {
  installation_id: string;
  setup: {
    completed: boolean;
    ready: boolean;
    missing_steps: string[];
  };
  messaging_configured: boolean;
  providers: SetupProvider[];
  users: SetupUser[];
  linked_identities: number;
  ai: {
    active_provider: string;
    configured: boolean;
    providers: SetupAIProvider[];
  };
  archive?: ArchiveSetupSnapshot;
}

export interface HomeScanSummary {
  ok: boolean;
  devices: number;
  available_devices: number;
  entities: number;
  areas: number;
  capabilities: number;
  domains: Array<{ domain: string; entities: number }>;
}

export interface ProviderInput {
  provider_key: string;
  provider_type: string;
  display_name: string;
  enabled?: boolean;
  endpoint?: string;
  session?: string;
  engine?: string;
  secret_ref?: string;
  secret_value?: string;
  config?: Record<string, unknown>;
}

export interface AIProviderInput {
  provider_key: string;
  provider_type: string;
  display_name: string;
  endpoint?: string;
  model: string;
  secret_ref?: string;
  secret_value?: string;
  enabled?: boolean;
  capabilities?: AICapability[];
  config?: Record<string, unknown>;
}

export interface UserInput {
  display_name: string;
  role: SetupRole;
  user_key?: string;
  enabled?: boolean;
}

export interface IdentityInput {
  provider_key: string;
  external_id: string;
  user_key: string;
  identity_label?: string;
}

const ROOT = '/api/next/setup';

export const setupApi = {
  status: () => api.get<SetupSnapshot>(`${ROOT}/status`),
  homeScan: () => api.post<HomeScanSummary>(`${ROOT}/home-scan`),
  saveArchiveIntegration: (body: ArchiveIntegrationInput) =>
    api.post<SetupIntegration>(`${ROOT}/integrations`, body),
  checkArchive: () => api.post<ArchiveSetupSnapshot>(`${ROOT}/archive/check`),
  selectArchiveMode: (mode: ArchiveStorageMode) =>
    api.put<ArchiveSetupSnapshot>(`${ROOT}/archive`, { mode }),
  saveProvider: (body: ProviderInput) => api.post<SetupProvider>(`${ROOT}/providers`, body),
  saveAIProvider: (body: AIProviderInput) =>
    api.post<SetupAIProvider>(`${ROOT}/ai/providers`, body),
  selectAIProvider: (providerKey: string) =>
    api.post<SetupAIProvider>(`${ROOT}/ai/providers/${encodeURIComponent(providerKey)}/select`),
  createUser: (body: UserInput) => api.post<SetupUser>(`${ROOT}/users`, body),
  linkIdentity: (body: IdentityInput) =>
    api.post<{ provider_key: string; user_key: string; identity_label: string }>(
      `${ROOT}/identities`,
      body,
    ),
  updatePolicy: (userKey: string, body: SetupPolicy) =>
    api.put<SetupUser>(`${ROOT}/users/${encodeURIComponent(userKey)}/policy`, body),
  complete: () => api.post<SetupSnapshot>(`${ROOT}/complete`),
};
