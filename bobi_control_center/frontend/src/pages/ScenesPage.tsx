/**
 * Scenes: what each one changes, and a way to activate it.
 *
 * Editing a scene's contents is not offered. A scene is a set of device states,
 * and building one from a web page would mean addressing devices directly —
 * which is exactly what the architecture routes through Bobi's bridge instead.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

function SceneDetail({ item }: { item: ManagedItem }) {
  const area = item.detail.area;
  const affects = Array.isArray(item.detail.affects) ? item.detail.affects : [];

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {typeof area === 'string' && area ? <Badge tone="info">{area}</Badge> : null}
      {affects.length > 0 ? <Badge tone="neutral">{affects.length} מכשירים</Badge> : null}
    </div>
  );
}

export function ScenesPage() {
  return (
    <ManagedResourcePage
      resource="scenes"
      title="סצנות"
      description="מצבים מוכנים מראש."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            הפעלת סצנה משנה כמה מכשירים בבת אחת, ולכן היא עוברת תצוגה מקדימה כמו כל שינוי אחר.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <SceneDetail item={item} />}
          emptyLabel="בובי לא פרסם סצנות."
        />
      )}
    </ManagedResourcePage>
  );
}
