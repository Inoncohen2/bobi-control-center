/**
 * The household calendar.
 *
 * Events are addressed by the bridge's own event id and belong to `user_1` or
 * `user_2`; no Home Assistant `calendar.*` entity id appears anywhere in this
 * screen or in the response behind it.
 *
 * Existing events are readings, and that is Home Assistant's limit rather than
 * a decision made here: it publishes no service that deletes or updates a
 * calendar event — that path is websocket-only and a bridge script cannot
 * reach it — so the bridge advertises nothing on an event rather than
 * announcing something no bridge could carry out. Adding one is the write that
 * does exist, and it is the form below.
 */

import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader } from '@/components/ui/Card';
import { SelectField, TextField } from '@/components/ui/Field';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem, ManagedTarget } from '@/types/api';

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

/**
 * Add one event.
 *
 * Which calendars may be written to comes from the contract's own targets, so
 * a household that gains or loses one needs no change here. Nothing is sent
 * while typing: the button opens the same preview → confirm → commit dialog
 * every other change goes through, and the backend refuses a payload missing a
 * title or a time before a preview exists.
 */
function NewEventForm({
  targets,
  onCreate,
}: {
  targets: ManagedTarget[];
  onCreate: (payload: Record<string, unknown>) => void;
}) {
  const [userId, setUserId] = useState(targets[0]?.id ?? '');
  const [summary, setSummary] = useState('');
  const [date, setDate] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [location, setLocation] = useState('');

  const complete = Boolean(userId && summary.trim() && date && from && to);

  return (
    <Card>
      <CardHeader title="אירוע חדש" description="ייווצר ביומן שתבחרו." />
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label="יומן"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          options={targets.map((target) => ({
            value: target.id,
            label: target.label ?? USER_LABELS[target.id] ?? target.id,
          }))}
        />
        <TextField
          label="כותרת"
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
        />
        <TextField
          label="תאריך"
          type="date"
          value={date}
          onChange={(event) => setDate(event.target.value)}
        />
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="משעה"
            type="time"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
          />
          <TextField
            label="עד שעה"
            type="time"
            value={to}
            onChange={(event) => setTo(event.target.value)}
          />
        </div>
        <TextField
          label="מיקום (לא חובה)"
          value={location}
          onChange={(event) => setLocation(event.target.value)}
        />
      </div>
      <div className="mt-3 flex justify-end">
        <Button
          disabled={!complete}
          onClick={() => {
            onCreate({
              user_id: userId,
              summary: summary.trim(),
              start: `${date}T${from}:00`,
              end: `${date}T${to}:00`,
              ...(location.trim() ? { location: location.trim() } : {}),
            });
            setSummary('');
            setLocation('');
          }}
        >
          בדוק שינוי
        </Button>
      </div>
    </Card>
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
            אפשר להוסיף אירוע. שינוי או מחיקה של אירוע קיים אינם נתמכים על ידי
            Home Assistant, ולכן הם לא מוצעים כאן.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, requestNew, writesEnabled, targets, operations }) => (
        <div className="space-y-4">
          {writesEnabled && operations.includes('create') && targets.length > 0 ? (
            <NewEventForm targets={targets} onCreate={(payload) => requestNew('create', payload)} />
          ) : null}
          <ResourceEditor
            snapshot={snapshot}
            onChange={request}
            writesEnabled={writesEnabled}
            renderDetail={(item) => <EventDetail item={item} />}
            emptyLabel="אין אירועים קרובים."
          />
        </div>
      )}
    </ManagedResourcePage>
  );
}
