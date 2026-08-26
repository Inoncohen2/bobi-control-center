/** Fixtures in the backend's **canonical** shape — what React actually receives. */

import type {
  BridgeCapabilities,
  DeviceLimits,
  BridgeDevice,
  BridgeDevices,
  BridgeDiagnostics,
  BridgeProbe,
  BridgeRules,
  BridgeShabbat,
  BridgeStatus,
  BridgeTasks,
  BridgeUsers,
  ConnectionInfo,
  ManagementStatus,
  PreviewResponse,
  CommitResponse,
  TaskSnapshot,
  ManagedItem,
  ResourceSnapshot,
} from '@/types/api';

export function makeConnection(overrides: Partial<ConnectionInfo> = {}): ConnectionInfo {
  return {
    adapter: 'home_assistant',
    connected: true,
    writes_enabled: false,
    phase: 2,
    app_version: '3.0.0',
    detail: 'מחובר לגשר של בובי',
    ...overrides,
  };
}

export function makeStatus(overrides: Partial<BridgeStatus> = {}): BridgeStatus {
  return {
    health: { status: 'healthy', ok: true, reason: 'כל הרכיבים הידועים תקינים' },
    ok: true,
    version: '1.2.3',
    uptime: '4 ימים',
    whatsapp: {
      connected: true,
      status: 'WORKING',
      label: 'תקין',
      detail: null,
      extra: {},
    },
    ai: {
      enabled: true,
      fast_paths_enabled: true,
      fast_paths_count: 3,
      fast_paths: ['lighting', 'climate', 'shabbat'],
      label: 'פעיל',
      detail: '3 מסלולים מהירים',
      extra: {},
    },
    users: { total: 3, active: 2, admins: 1, names: [], extra: {} },
    config: { ok: true, status: 'OK', label: 'תקין', detail: null, extra: {} },
    features: [
      { id: 'shabbat', label: 'שעון שבת', enabled: true, detail: null },
      { id: 'vision', label: 'עיבוד תמונות', enabled: false, detail: null },
    ],
    // Derived by the backend from the sections above, as the real bridge sends
    // no component list of its own.
    components: [
      {
        id: 'bobi',
        name: 'בובי',
        label: 'פעיל',
        state: 'healthy',
        ok: true,
        detail: null,
      },
      { id: 'whatsapp', name: 'WhatsApp', label: 'תקין', state: 'WORKING', ok: true, detail: null },
      {
        id: 'ai',
        name: 'בינה מלאכותית',
        label: 'פעיל',
        state: null,
        ok: true,
        detail: '3 מסלולים מהירים',
      },
      { id: 'config', name: 'תצורה', label: 'תקין', state: 'OK', ok: true, detail: null },
    ],
    counts: { devices: 18, rules: 6, issues: 2 },
    details: { profile: 'household' },
    writes_enabled: false,
    ...overrides,
  };
}

/** Every limit null, so a fixture only states the ones it cares about. */
export function makeLimits(overrides: Partial<DeviceLimits> = {}): DeviceLimits {
  return {
    min: null,
    max: null,
    step: null,
    min_temp: null,
    max_temp: null,
    temp_step: null,
    preset_modes: [],
    fan_modes: [],
    swing_modes: [],
    hvac_modes: [],
    min_kelvin: null,
    max_kelvin: null,
    min_brightness: null,
    max_brightness: null,
    intensity_min: null,
    intensity_max: null,
    scent_slots: [],
    timer_max_seconds: null,
    extra: {},
    ...overrides,
  };
}

export function makeDevice(overrides: Partial<BridgeDevice> = {}): BridgeDevice {
  return {
    id: 'light.demo_kitchen',
    name: 'אור מטבח',
    area: 'מטבח',
    group: 'תאורה',
    domain: 'light',
    state: 'off',
    available: true,
    aliases: ['אור מטבח', 'האור במטבח'],
    capabilities: ['turn_on', 'turn_off'],
    semantic_scopes: ['lighting'],
    controllable: true,
    logical_controllable: true,
    entity_id: 'light.demo_kitchen',
    handler: 'lighting_handler',
    limits: null,
    last_changed: new Date().toISOString(),
    extra: {},
    ...overrides,
  };
}

export function makeDevices(overrides: Partial<BridgeDevices> = {}): BridgeDevices {
  return {
    scope: 'all',
    include_unavailable: true,
    count: 3,
    devices: [
      makeDevice(),
      makeDevice({
        id: 'climate.demo_living_room',
        name: 'מזגן סלון',
        entity_id: 'climate.demo_living_room',
        area: 'סלון',
        domain: 'climate',
        group: 'מיזוג',
        semantic_scopes: ['climate', 'temperature'],
        aliases: ['מזגן סלון', 'המזגן בסלון'],
        handler: 'climate_handler',
        state: 'off',
        limits: makeLimits({
          min: 16,
          max: 30,
          step: 1,
          min_temp: 16,
          max_temp: 30,
          temp_step: 1,
          fan_modes: ['low', 'high'],
          hvac_modes: ['off', 'cool'],
        }),
      }),
      makeDevice({
        id: 'camera.demo_girls',
        name: 'מצלמת ליה',
        entity_id: 'camera.demo_girls',
        area: 'חדר בנות',
        domain: 'camera',
        group: 'מצלמות',
        semantic_scopes: ['cameras'],
        aliases: ['מצלמת ליה'],
        handler: 'camera_handler',
        state: 'unavailable',
        available: false,
        controllable: false,
      }),
    ],
    areas: ['חדר בנות', 'מטבח', 'סלון'],
    groups: ['מיזוג', 'מצלמות', 'תאורה'],
    ...overrides,
  };
}

export function makeCapabilities(
  overrides: Partial<BridgeCapabilities> = {},
): BridgeCapabilities {
  return {
    count: 2,
    capabilities: [
      {
        id: 'lighting',
        label: 'שליטה בתאורה',
        example: 'תדליק את אור הסלון',
        risk: 'low',
        handler: 'lighting_handler',
        local: true,
        local_after_parse: false,
        group: 'שליטה בבית',
        extra: {},
      },
      {
        id: 'vision',
        label: 'עיבוד תמונות',
        example: 'מה רואים בתמונה הזו',
        risk: 'high',
        handler: 'vision_handler',
        local: false,
        local_after_parse: false,
        group: 'בינה מלאכותית',
        extra: {},
      },
    ],
    toggles: [
      {
        id: 'master_ai',
        label: 'AI fallback',
        enabled: true,
        state: 'on',
        entity_id: 'input_boolean.demo_ai',
      },
    ],
    ...overrides,
  };
}

export function makeUsers(overrides: Partial<BridgeUsers> = {}): BridgeUsers {
  return {
    count: 2,
    users: [
      {
        id: 'user_a',
        name: 'ינון',
        role: 'admin',
        enabled: true,
        whatsapp_connected: true,
        calendar: 'יומן ינון',
        task_list: 'משימות ינון',
        permissions: ['control_devices', 'manage_bobi'],
        areas: ['סלון'],
        extra: {},
      },
      {
        id: 'user_b',
        name: 'הודיה',
        role: 'member',
        enabled: true,
        whatsapp_connected: true,
        calendar: null,
        task_list: null,
        permissions: ['control_devices'],
        areas: [],
        extra: {},
      },
    ],
    ...overrides,
  };
}

export function makeShabbat(overrides: Partial<BridgeShabbat> = {}): BridgeShabbat {
  return {
    candle_lighting: '18:52',
    havdalah: '19:51',
    parasha: 'פרשת ראה',
    pre_shabbat_offset_minutes: 20,
    profiles: [
      {
        id: 'pre_off',
        kind: 'pre_off',
        label: 'כיבוי לפני שבת',
        active: true,
        time: null,
        offset_minutes: 20,
        // The backend resolves the bridge's tokens, keeping both halves.
        devices: [{ id: 'kitchen_light', label: 'אור מטבח' }],
        extra: {},
      },
    ],
    ac_temperatures: [
      { id: 'living_room_ac', label: 'מזגן סלון', temperature: 24, text: '24' },
    ],
    has_draft: false,
    draft_owners: [],
    writes_enabled: false,
    extra: {},
    ...overrides,
  };
}

export function makeRules(overrides: Partial<BridgeRules> = {}): BridgeRules {
  return {
    count: 2,
    rules: [
      {
        id: 'rule_a',
        name: 'אור מטבח בערב',
        description: 'מדליק את אור המטבח בשעה 18:00.',
        enabled: true,
        kind: 'schedule',
        trigger: null,
        schedule: '18:00 · ראשון–חמישי',
        targets: ['אור מטבח'],
        last_triggered: new Date().toISOString(),
        entity_id: null,
        extra: {},
      },
      {
        id: 'rule_b',
        name: 'רובי בימי שני',
        description: null,
        enabled: false,
        kind: 'schedule',
        trigger: null,
        schedule: '10:00 · שני',
        targets: [],
        last_triggered: null,
        entity_id: null,
        extra: {},
      },
    ],
    ...overrides,
  };
}

export function makeTasks(overrides: Partial<BridgeTasks> = {}): BridgeTasks {
  return {
    count: 2,
    tasks: [
      {
        id: 'task_1',
        title: 'לקבוע תור לרופא',
        owner: 'ינון',
        completed: false,
        status: 'needs_action',
        due: null,
        list_name: 'משימות ינון',
        extra: {},
      },
      {
        id: 'task_2',
        title: 'לחדש ביטוח',
        owner: 'ינון',
        completed: true,
        status: 'completed',
        due: null,
        list_name: 'משימות ינון',
        extra: {},
      },
    ],
    owners: ['ינון'],
    ...overrides,
  };
}

export function makeDiagnostics(
  overrides: Partial<BridgeDiagnostics> = {},
): BridgeDiagnostics {
  return {
    ok: false,
    issue_count: 1,
    issues: [
      {
        id: 'device_unavailable:camera.demo_girls',
        severity: 'error',
        title: 'מצלמת ליה אינה זמינה',
        message: 'המצלמה לא משדרת כבר כשעתיים.',
        component: 'device',
        code: 'device_unavailable',
        entity_ids: ['camera.demo_girls'],
        suggested_action: 'לנתק ולחבר את שקע המצלמה.',
        detail: 'state=unavailable',
        extra: {},
      },
    ],
    checks: [
      { id: 'whatsapp', label: 'WhatsApp', ok: true, value: 'WORKING', detail: null },
      // A measurement, not a pass/fail: `ok` is null.
      { id: 'catalog_count', label: 'מכשירים בקטלוג', ok: null, value: '18', detail: null },
    ],
    ...overrides,
  };
}

export function makeProbe(overrides: Partial<BridgeProbe> = {}): BridgeProbe {
  return {
    handled: true,
    status: 'ok',
    terminal: true,
    skill: 'local_schedule',
    understanding: {
      intent: 'device_control',
      action: 'turn_off',
      domain: 'climate',
      target: 'מזגן הורים',
      area: 'חדר הורים',
      time: '01:30',
    },
    schedule_valid: true,
    schedule_reason: 'תוזמן ל-01:30',
    // Mirrors the kind the real bridge returns for a late-night clock time.
    schedule_kind: 'next_night_clock',
    text: 'כבה מזגן הורים ב-1:30 בלילה',
    error: null,
    warnings: [],
    probe_only: true,
    would_execute: false,
    raw: {},
    ...overrides,
  };
}

// --- management (Phase 3A) -------------------------------------------------
/**
 * Management off — the default, and what the live install reports today.
 *
 * Every screen must be usable in this state, so it is what the shared route
 * table serves unless a test deliberately turns management on.
 */
export function makeManagementOff(
  overrides: Partial<ManagementStatus> = {},
): ManagementStatus {
  return {
    available: false,
    reason: 'ניהול עדיין לא הופעל ב-Home Assistant',
    contract_version: null,
    resources: [],
    writes_enabled: false,
    requires_preview: true,
    requires_confirmation: true,
    requires_read_after_write: true,
    ...overrides,
  };
}

/**
 * The contract as Home Assistant publishes it — bridge available, **master
 * write switch off**, which is the real state today.
 */
export function makeManagementOn(
  overrides: Partial<ManagementStatus> = {},
): ManagementStatus {
  return {
    available: true,
    reason: null,
    contract_version: '3a',
    resources: [
      {
        id: 'tasks',
        label: 'משימות',
        available: true,
        detail: null,
        operations: [
          { id: 'add', label: 'הוספת משימה', destructive: false },
          { id: 'edit', label: 'שינוי תוכן', destructive: false },
          { id: 'complete', label: 'סימון כבוצעה', destructive: false },
          { id: 'reopen', label: 'החזרה לפעילה', destructive: false },
          { id: 'delete', label: 'מחיקה', destructive: true },
        ],
        targets: [
          { id: 'user_1', label: 'ינון', risk: null, enabled: null },
          { id: 'user_2', label: 'הודיה', risk: null, enabled: null },
        ],
      },
      {
        id: 'features',
        label: 'תכונות',
        available: true,
        detail: null,
        operations: [{ id: 'set', label: 'הפעלה או כיבוי', destructive: false }],
        targets: [
          { id: 'morning_auto', label: 'סיכום בוקר אוטומטי', risk: 'low', enabled: false },
          { id: 'home_status_auto', label: 'מצב הבית האוטומטי', risk: 'low', enabled: true },
        ],
      },
    ],
    writes_enabled: false,
    requires_preview: true,
    requires_confirmation: true,
    requires_read_after_write: true,
    ...overrides,
  };
}

/** The management snapshot: both open and completed tasks, with bridge uids. */
export function makeTaskSnapshot(overrides: Partial<TaskSnapshot> = {}): TaskSnapshot {
  return {
    count: 2,
    tasks: [
      {
        uid: 'u-1',
        summary: 'לקבוע תור לרופא',
        status: 'needs_action',
        completed: false,
        due: null,
        owner_id: 'user_1',
        owner: 'ינון',
      },
      {
        uid: 'u-2',
        summary: 'לחדש ביטוח רכב',
        status: 'completed',
        completed: true,
        due: null,
        owner_id: 'user_2',
        owner: 'הודיה',
      },
    ],
    owners: [
      { id: 'user_1', label: 'ינון', risk: null, enabled: null },
      { id: 'user_2', label: 'הודיה', risk: null, enabled: null },
    ],
    writes_enabled: false,
    ...overrides,
  };
}

export function makePreview(overrides: Partial<PreviewResponse> = {}): PreviewResponse {
  return {
    preview_id: 'pv_test',
    operation: 'add',
    resource_type: 'tasks',
    resource_id: null,
    title: 'הוספת משימה',
    changes: [
      { label: 'משתמש', before: 'ינון', after: 'ינון' },
      { label: 'משימה', before: null, after: 'לקבוע תור לרופא' },
    ],
    explanation: 'המשימה תתווסף לרשימה של המשתמש.',
    destructive: false,
    warning: null,
    confirm_word: null,
    confirm_label: 'בצע שינוי',
    valid: true,
    errors: [],
    expires_at: new Date(Date.now() + 300_000).toISOString(),
    would_execute: false,
    ...overrides,
  };
}

export function makeCommit(overrides: Partial<CommitResponse> = {}): CommitResponse {
  return {
    preview_id: 'pv_test',
    operation: 'add',
    resource_type: 'tasks',
    result: {
      status: 'committed',
      message: 'השינוי בוצע ואומת',
      resource_id: 'u-9',
      reason: 'ok',
      verification: { verified: true, method: 'read_after_write', detail: null },
    },
    audit: {
      id: 'au_test',
      timestamp: new Date().toISOString(),
      stage: 'commit',
      operation: 'add',
      resource_type: 'tasks',
      resource_id: 'u-9',
      requested_change: { title: 'לקבוע תור לרופא' },
      result: 'committed',
      verified: true,
      source: 'web',
    },
    ...overrides,
  };
}

// --- the 3.0 families ------------------------------------------------------

export function makeManagedItem(overrides: Partial<ManagedItem> = {}): ManagedItem {
  return {
    id: 'morning_enabled',
    label: 'סיכום בוקר אוטומטי',
    group: 'morning',
    kind: 'toggle',
    value: true,
    display: 'פעיל',
    description: null,
    risk: 'low',
    controllable: true,
    operations: ['set'],
    options: [],
    constraints: null,
    unavailable_reason: null,
    detail: {},
    ...overrides,
  };
}

export function makeResourceSnapshot(
  overrides: Partial<ResourceSnapshot> = {},
): ResourceSnapshot {
  const items = overrides.items ?? [makeManagedItem()];
  return {
    resource: 'settings',
    available: true,
    reason: null,
    writes_enabled: true,
    groups: [{ id: 'morning', label: 'סיכום בוקר', description: null, items }],
    items,
    detail: {},
    ...overrides,
  };
}

/** A contract that advertises one of the 3.0 families as available. */
export function makeManagementWith(
  resource: string,
  overrides: Partial<ManagementStatus> = {},
): ManagementStatus {
  const base = makeManagementOn();
  return {
    ...base,
    resources: [
      ...base.resources,
      {
        id: resource,
        label: resource,
        available: true,
        detail: null,
        operations: [{ id: 'set', label: 'שינוי', destructive: false }],
        targets: [],
      },
    ],
    ...overrides,
  };
}
