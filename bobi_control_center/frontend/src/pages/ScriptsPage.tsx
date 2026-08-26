/**
 * Scripts, run with the parameters their own schema declares.
 *
 * The bridge publishes a script's `fields` — each with a kind and its limits —
 * and those are the only inputs a run may carry. There is no free-form body: a
 * script cannot be handed an arbitrary payload from here, because a payload
 * this application cannot validate is a payload it should not send.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

function ScriptDetail({ item }: { item: ManagedItem }) {
  const last = item.detail.last_run;
  const fields = Array.isArray(item.detail.fields) ? item.detail.fields : [];

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <Badge tone="muted">
        {typeof last === 'string' && last
          ? `רץ לאחרונה: ${last.replace('T', ' ').slice(0, 16)}`
          : 'עדיין לא רץ'}
      </Badge>
      {fields.length > 0 ? <Badge tone="info">{fields.length} פרמטרים</Badge> : null}
    </div>
  );
}

export function ScriptsPage() {
  return (
    <ManagedResourcePage
      resource="scripts"
      title="סקריפטים"
      description="מה אפשר להריץ, ומה זה עושה."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            סקריפט רץ רק עם הפרמטרים שבובי הצהיר עליהם. אי אפשר לשלוח מכאן פקודה חופשית.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <ScriptDetail item={item} />}
          emptyLabel="בובי לא פרסם סקריפטים."
        />
      )}
    </ManagedResourcePage>
  );
}
