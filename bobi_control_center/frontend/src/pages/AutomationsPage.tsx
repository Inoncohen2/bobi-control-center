/**
 * Home Assistant automations — not Bobi's smart rules, which live on their own
 * screen.
 *
 * Enable, disable, run now, rename. Nothing else: changing an automation's
 * triggers or actions from a web page would mean either arbitrary YAML, which
 * is refused outright, or a schema this application cannot validate — and a
 * change it cannot validate is a change it should not offer.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import { timeAgo } from '@/utils/format';
import type { ManagedItem } from '@/types/api';

const MODE_LABELS: Record<string, string> = {
  single: 'הרצה אחת',
  restart: 'מתחיל מחדש',
  queued: 'בתור',
  parallel: 'במקביל',
};

function AutomationDetail({ item }: { item: ManagedItem }) {
  const mode = String(item.detail.mode ?? '');
  const area = item.detail.area;
  const last = item.detail.last_triggered;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {mode ? <Badge tone="neutral">{MODE_LABELS[mode] ?? mode}</Badge> : null}
      {typeof area === 'string' && area ? <Badge tone="info">{area}</Badge> : null}
      <Badge tone="muted">
        {typeof last === 'string' && last ? `רצה ${timeAgo(last)}` : 'עדיין לא רצה'}
      </Badge>
    </div>
  );
}

export function AutomationsPage() {
  return (
    <ManagedResourcePage
      resource="automations"
      title="אוטומציות Home Assistant"
      description="מה פעיל, מתי רץ לאחרונה, והרצה ידנית."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            עריכת התנאים והפעולות של אוטומציה נעשית ב-Home Assistant. מכאן אפשר להפעיל,
            להשבית, להריץ עכשיו ולשנות שם.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <AutomationDetail item={item} />}
          emptyLabel="אין אוטומציות."
        />
      )}
    </ManagedResourcePage>
  );
}
