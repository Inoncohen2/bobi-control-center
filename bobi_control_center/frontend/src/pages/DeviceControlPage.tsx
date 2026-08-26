/**
 * Devices, with controls where Bobi says there may be controls.
 *
 * A device gets a write control only when the bridge marked it `controllable`
 * and named the operations it accepts. Everything else is a reading. The
 * capabilities list decides what is offered — a light that does not advertise
 * brightness gets no brightness control, and asking for one anyway is refused
 * by the backend rather than sent to Home Assistant to sort out.
 *
 * Devices are addressed by Bobi's canonical id. No `light.*`, `climate.*` or
 * any other entity id reaches this screen.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

/** Hebrew for the capability tokens the bridge publishes. */
const CAPABILITY_LABELS: Record<string, string> = {
  on_off: 'הדלקה וכיבוי',
  brightness: 'עוצמה',
  color_temp: 'גוון אור',
  temperature: 'טמפרטורה',
  hvac_mode: 'מצב',
  fan_mode: 'מאוורר',
  swing_mode: 'סבסוב',
  preset_mode: 'תוכנית',
  start: 'הפעלה',
  pause: 'השהיה',
  stop: 'עצירה',
  return_home: 'חזרה לעמדה',
  intensity: 'עוצמת ריח',
  scent_slot: 'תא ריח',
  timer: 'טיימר',
  snapshot: 'תמונה',
};

export const CAMERA_CLASS = 'camera';

export function capabilities(item: ManagedItem): string[] {
  return Array.isArray(item.detail.capabilities)
    ? (item.detail.capabilities as unknown[]).map(String)
    : [];
}

export function DeviceDetail({ item }: { item: ManagedItem }) {
  const list = capabilities(item);
  const deviceClass = String(item.detail.device_class ?? '');

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {deviceClass ? <Badge tone="info">{deviceClass}</Badge> : null}
      {list.map((capability) => (
        <Badge key={capability} tone="neutral">
          {CAPABILITY_LABELS[capability] ?? capability}
        </Badge>
      ))}
    </div>
  );
}

export function DeviceControlPage() {
  return (
    <ManagedResourcePage
      resource="devices"
      title="מכשירים"
      description="מה דולק, ומה אפשר לשנות."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            כל פעולה על מכשיר עוברת תצוגה מקדימה, ובובי קורא את המצב בחזרה כדי לוודא שהיא נקלטה.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          filter={(item) => String(item.detail.device_class ?? '') !== CAMERA_CLASS}
          renderDetail={(item) => <DeviceDetail item={item} />}
          emptyLabel="בובי לא פרסם מכשירים."
        />
      )}
    </ManagedResourcePage>
  );
}
