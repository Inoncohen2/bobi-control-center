/** Bridge-shaped fixtures for component tests. */

import type {
  BridgeCapabilities,
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
} from '@/types/api';

export function makeConnection(overrides: Partial<ConnectionInfo> = {}): ConnectionInfo {
  return {
    adapter: 'home_assistant',
    connected: true,
    writes_enabled: false,
    phase: 2,
    detail: 'מחובר לגשר של בובי',
    ...overrides,
  };
}

export function makeStatus(overrides: Partial<BridgeStatus> = {}): BridgeStatus {
  return {
    ok: true,
    version: '1.2.3',
    uptime: '4 ימים',
    components: [
      { id: 'bobi', name: 'בובי', state: 'online', label: 'פעיל', detail: null, ok: true },
      {
        id: 'whatsapp',
        name: 'WhatsApp',
        state: 'online',
        label: 'מחובר',
        detail: null,
        ok: true,
      },
    ],
    counts: { devices: 18, rules: 6, issues: 2 },
    writes_enabled: false,
    ...overrides,
  };
}

export function makeDevice(overrides: Partial<BridgeDevice> = {}): BridgeDevice {
  return {
    entity_id: 'light.demo_kitchen',
    name: 'אור מטבח',
    canonical: 'אור מטבח',
    semantic_scopes: ['lighting'],
    aliases: ['אור מטבח', 'האור במטבח'],
    domain: 'light',
    group: 'תאורה',
    area: 'מטבח',
    state: 'off',
    controllable: true,
    logical_controllable: true,
    handler: 'lighting_handler',
    capabilities: ['turn_on', 'turn_off'],
    limits: null,
    last_changed: new Date().toISOString(),
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
        entity_id: 'climate.demo_living_room',
        canonical: 'מזגן סלון',
        name: 'מזגן סלון',
        area: 'סלון',
        domain: 'climate',
        group: 'מיזוג',
        semantic_scopes: ['climate', 'temperature'],
        aliases: ['מזגן סלון', 'המזגן בסלון'],
        handler: 'climate_handler',
        state: 'off',
      }),
      makeDevice({
        entity_id: 'camera.demo_girls',
        canonical: 'מצלמת ליה',
        name: 'מצלמת ליה',
        area: 'חדר בנות',
        domain: 'camera',
        group: 'מצלמות',
        semantic_scopes: ['cameras'],
        aliases: ['מצלמת ליה'],
        handler: 'camera_handler',
        state: 'unavailable',
        controllable: false,
      }),
    ],
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
        handler: 'lighting_handler',
        local: true,
        local_after_parse: false,
        risk: 'low',
        label: 'שליטה בתאורה',
        example: 'תדליק את אור הסלון',
        group: 'שליטה בבית',
      },
      {
        id: 'vision',
        handler: 'vision_handler',
        local: false,
        local_after_parse: false,
        risk: 'high',
        label: 'עיבוד תמונות',
        example: 'מה רואים בתמונה הזו',
        group: 'בינה מלאכותית',
      },
    ],
    toggles: [
      {
        id: 'master_ai',
        name: 'AI fallback',
        label: 'AI fallback',
        state: 'on',
        enabled: true,
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
      },
    ],
    ...overrides,
  };
}

export function makeShabbat(overrides: Partial<BridgeShabbat> = {}): BridgeShabbat {
  return {
    candle_lighting: '18:52',
    havdalah: '19:51',
    pre_shabbat_offset_minutes: 20,
    pre_off_profile: {
      id: 'pre_off',
      name: 'כיבוי לפני שבת',
      label: 'כיבוי לפני שבת',
      active: true,
      devices: ['kitchen_light'],
      time: null,
      offset_minutes: 20,
    },
    pre_on_profile: null,
    night_off_profile: null,
    morning_on_profile: null,
    ac_temperatures: { living_room_ac: 24 },
    device_labels: { kitchen_light: 'אור מטבח', living_room_ac: 'מזגן סלון' },
    has_draft: false,
    writes_enabled: false,
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
        label: null,
        description: 'מדליק את אור המטבח בשעה 18:00.',
        enabled: true,
        kind: 'schedule',
        trigger: null,
        schedule: '18:00 · ראשון–חמישי',
        targets: ['אור מטבח'],
        last_triggered: new Date().toISOString(),
        entity_id: null,
      },
      {
        id: 'rule_b',
        name: 'רובי בימי שני',
        label: null,
        description: null,
        enabled: false,
        kind: 'schedule',
        trigger: null,
        schedule: '10:00 · שני',
        targets: [],
        last_triggered: null,
        entity_id: null,
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
        summary: null,
        status: 'needs_action',
        completed: false,
        due: null,
        owner: 'ינון',
        list_name: 'משימות ינון',
      },
      {
        id: 'task_2',
        title: 'לחדש ביטוח',
        summary: null,
        status: 'completed',
        completed: true,
        due: null,
        owner: 'ינון',
        list_name: 'משימות ינון',
      },
    ],
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
        id: 'issue_camera',
        severity: 'error',
        title: 'מצלמת ליה אינה זמינה',
        label: null,
        message: 'המצלמה לא משדרת כבר כשעתיים.',
        description: null,
        component: 'מצלמות',
        entity_id: 'camera.demo_girls',
        entity_ids: [],
        suggested_action: 'לנתק ולחבר את שקע המצלמה.',
        detail: 'state=unavailable',
      },
    ],
    checks: [
      { id: 'check_bridge', name: 'גשר בובי', label: 'גשר בובי', ok: true, detail: 'זמין' },
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
      targets: [],
      area: 'חדר הורים',
      value: null,
      time: '01:30',
      date: null,
    },
    schedule_valid: true,
    schedule_reason: 'תוזמן ל-01:30',
    schedule_kind: 'one_time',
    text: 'כבה מזגן הורים ב-1:30 בלילה',
    error: null,
    probe_only: true,
    would_execute: false,
    ...overrides,
  };
}
