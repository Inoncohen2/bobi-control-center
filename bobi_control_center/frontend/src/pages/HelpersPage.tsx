/**
 * Home Assistant helpers, through Bobi's bridge.
 *
 * `input_boolean`, `input_number`, `input_select`, `input_text`,
 * `input_datetime`, `timer` and `counter` — none of which is ever named as a
 * service from here. The bridge publishes each helper as a canonical item with
 * a kind and its limits; this screen renders that, exactly as it renders a
 * setting or a Shabbat time. A timer's verbs (`start`, `pause`, `cancel`) and a
 * counter's (`increment`, `decrement`, `reset`) appear only because the bridge
 * named them on that item.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

/** Hebrew for the helper kinds the bridge reports. */
const KIND_LABELS: Record<string, string> = {
  input_boolean: 'מתג',
  input_number: 'מספר',
  input_select: 'בחירה',
  input_text: 'טקסט',
  input_datetime: 'תאריך ושעה',
  timer: 'טיימר',
  counter: 'מונה',
  schedule: 'לוח זמנים',
};

function HelperDetail({ item }: { item: ManagedItem }) {
  const kind = String(item.detail.helper_kind ?? '');
  if (!kind) return null;
  return (
    <div className="mt-1.5">
      <Badge tone="neutral">{KIND_LABELS[kind] ?? kind}</Badge>
    </div>
  );
}

export function HelpersPage() {
  return (
    <ManagedResourcePage
      resource="helpers"
      title="עזרים"
      description="המתגים, המונים והטיימרים שבובי מנהל."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            כל שינוי כאן עובר תצוגה מקדימה, ובובי קורא את הערך בחזרה כדי לוודא שהוא נקלט.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <HelperDetail item={item} />}
          emptyLabel="בובי לא פרסם עזרים."
        />
      )}
    </ManagedResourcePage>
  );
}
