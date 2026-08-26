/**
 * The household calendar.
 *
 * Events are addressed by the bridge's own event id and belong to `user_1` or
 * `user_2`; no Home Assistant `calendar.*` entity id appears anywhere in this
 * screen or in the response behind it. Deleting an event is destructive and
 * asks for the confirmation word like every other destructive change.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

/** Names come from the bridge; these are the fallbacks when it sent none. */
const USER_LABELS: Record<string, string> = {
  user_1: 'משתמש 1',
  user_2: 'משתמש 2',
};

function when(value: unknown): string | null {
  return typeof value === 'string' && value ? value.replace('T', ' ').slice(0, 16) : null;
}

function EventDetail({ item }: { item: ManagedItem }) {
  const start = when(item.detail.start);
  const end = when(item.detail.end);
  const owner = String(item.detail.user_id ?? '');
  const location = item.detail.location;
  const recurring = item.detail.recurring === true;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {owner ? <Badge tone="info">{USER_LABELS[owner] ?? owner}</Badge> : null}
      {start ? (
        <Badge tone="neutral">{end ? `${start} – ${end.slice(-5)}` : start}</Badge>
      ) : null}
      {typeof location === 'string' && location ? (
        <Badge tone="neutral">{location}</Badge>
      ) : null}
      {recurring ? <Badge tone="warning">אירוע חוזר</Badge> : null}
    </div>
  );
}

export function CalendarPage() {
  return (
    <ManagedResourcePage
      resource="calendar"
      title="יומן"
      description="מה מתוכנן, ולמי."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            מחיקת אירוע היא פעולה בלתי הפיכה ותדרוש אישור מפורש.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <EventDetail item={item} />}
          emptyLabel="אין אירועים קרובים."
        />
      )}
    </ManagedResourcePage>
  );
}
