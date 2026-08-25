/** Minimal API-shaped fixtures for component tests. */

import type {
  Advanced,
  Automation,
  Device,
  ShabbatConfig,
  SystemStatus,
  TimeRange,
} from '@/types/api';

export const advanced: Advanced = {
  entity_id: null,
  object_id: null,
  integration: null,
  notes: [],
  raw: {},
};

export function makeDevice(overrides: Partial<Device> = {}): Device {
  return {
    id: 'kitchen_light',
    display_name: 'אור מטבח',
    room: 'מטבח',
    category: 'light',
    state: 'off',
    state_label: 'כבוי',
    available: true,
    aliases: ['אור מטבח', 'האור במטבח'],
    capabilities: ['turn_on', 'turn_off'],
    icon: 'lightbulb',
    advanced,
    ...overrides,
  };
}

export function makeAutomation(overrides: Partial<Automation> = {}): Automation {
  return {
    id: 'kitchen_light_evening',
    name: 'אור מטבח בערב',
    enabled: true,
    automation_type: 'time_window',
    targets: [{ id: 'kitchen_light', name: 'אור מטבח', room: 'מטבח' }],
    actions: [{ type: 'turn_on', label: 'להדליק', value: null }],
    days: [0, 1, 2, 3, 4],
    start_time: '18:00',
    end_time: '22:00',
    times: [],
    run_date: null,
    conditions: [],
    owner: 'ינון',
    created_by: 'ינון',
    source: 'web',
    last_triggered: null,
    crosses_midnight: false,
    summary: 'בימים ראשון עד חמישי בין 18:00 ל-22:00 להדליק את אור מטבח',
    advanced,
    ...overrides,
  };
}

export function makeRange(overrides: Partial<TimeRange> = {}): TimeRange {
  return {
    id: 'r1',
    start: '17:42',
    end: '23:30',
    crosses_midnight: false,
    enabled: true,
    day: 'friday',
    ...overrides,
  };
}

export function makeShabbatConfig(overrides: Partial<ShabbatConfig> = {}): ShabbatConfig {
  return {
    enabled: true,
    times: {
      parasha: 'פרשת ראה',
      candle_lighting: '18:52',
      havdalah: '19:51',
      friday_date: 'שישי, 28 באוגוסט',
      saturday_date: 'שבת, 29 באוגוסט',
      city: 'תל אביב',
    },
    schedules: [
      {
        id: 'sch_kitchen_light',
        device_id: 'kitchen_light',
        device_name: 'אור מטבח',
        room: 'מטבח',
        icon: 'lightbulb',
        enabled: true,
        ranges: [makeRange()],
        note: null,
        advanced,
      },
      {
        id: 'sch_living_room_ac',
        device_id: 'living_room_ac',
        device_name: 'מזגן סלון',
        room: 'סלון',
        icon: 'air-vent',
        enabled: true,
        // Crosses midnight — the badge must appear for this one only.
        ranges: [makeRange({ id: 'r2', start: '22:00', end: '01:00', crosses_midnight: true })],
        note: null,
        advanced,
      },
    ],
    templates: [],
    active_template_id: null,
    updated_at: null,
    has_draft: false,
    ...overrides,
  };
}

export function makeStatus(overrides: Partial<SystemStatus> = {}): SystemStatus {
  return {
    name: 'בובי',
    version: '1.0.0-phase1',
    adapter: 'mock',
    read_only: true,
    generated_at: new Date().toISOString(),
    components: [
      { id: 'bobi', name: 'בובי', state: 'online', label: 'פעיל', detail: null },
      { id: 'whatsapp', name: 'WhatsApp', state: 'online', label: 'מחובר', detail: null },
      { id: 'ai', name: 'AI', state: 'online', label: 'פעיל', detail: null },
      {
        id: 'home_assistant',
        name: 'Home Assistant',
        state: 'online',
        label: 'מחובר',
        detail: null,
      },
    ],
    stats: [
      { id: 'automations', label: 'אוטומציות פעילות', value: 8, hint: null, severity: 'ok' },
      { id: 'schedules', label: 'תזמונים', value: 13, hint: null, severity: 'ok' },
      { id: 'notifications', label: 'הודעות חכמות', value: 7, hint: null, severity: 'ok' },
      { id: 'tasks', label: 'משימות פתוחות', value: 5, hint: null, severity: 'ok' },
      {
        id: 'attention',
        label: 'בעיות שדורשות תשומת לב',
        value: 1,
        hint: null,
        severity: 'warning',
      },
    ],
    activity: [
      {
        id: 'act_0',
        time: '08:42',
        timestamp: new Date().toISOString(),
        title: 'בובי שלח תזכורת לפגישה',
        detail: 'פגישת צוות',
        icon: 'bell',
        severity: 'ok',
      },
    ],
    attention: [
      {
        id: 'att_camera',
        title: 'מצלמת ליה אינה זמינה',
        description: 'בובי לא מצליח להתחבר למצלמה.',
        severity: 'warning',
        component: 'מצלמות',
        technical_details: 'camera.demo_lia_room · state=unavailable',
        action_label: 'למסך התקלות',
        action_href: '/diagnostics',
      },
    ],
    ...overrides,
  };
}
