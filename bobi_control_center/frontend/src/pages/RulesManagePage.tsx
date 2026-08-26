/**
 * Bobi's smart rules.
 *
 * These are Bobi's own rules, not Home Assistant automations: nothing here
 * creates an `automation.*`, and the internal list Bobi stores them in is never
 * named or shown. Parsing and conflict detection stay on Bobi's side — when the
 * bridge reports a conflict this screen shows it, and when the bridge calls it
 * blocking the change is refused rather than argued with.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

const DAY_LABELS: Record<string, string> = {
  sun: 'א׳',
  mon: 'ב׳',
  tue: 'ג׳',
  wed: 'ד׳',
  thu: 'ה׳',
  fri: 'ו׳',
  sat: 'שבת',
};

const TYPE_LABELS: Record<string, string> = {
  once: 'חד־פעמי',
  weekly: 'שבועי',
};

function RuleDetail({ item }: { item: ManagedItem }) {
  const days = Array.isArray(item.detail.days) ? (item.detail.days as string[]) : [];
  const type = String(item.detail.rule_type ?? '');
  const time = item.detail.time;
  const nextDue = item.detail.next_due;
  const action = item.detail.action;
  const conflicts = Array.isArray(item.detail.conflicts) ? item.detail.conflicts : [];

  return (
    <div className="mt-1.5 space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        {type ? <Badge tone="info">{TYPE_LABELS[type] ?? type}</Badge> : null}
        {days.map((day) => (
          <Badge key={day} tone="neutral">
            {DAY_LABELS[day] ?? day}
          </Badge>
        ))}
        {typeof time === 'string' && time ? <Badge tone="neutral">{time}</Badge> : null}
        {typeof nextDue === 'string' && nextDue ? (
          <Badge tone="neutral">{nextDue.replace('T', ' ')}</Badge>
        ) : null}
      </div>
      {typeof action === 'string' && action ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">{action}</p>
      ) : null}
      {conflicts.length > 0 ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          בובי מצא חפיפה עם אוטומציה קיימת.
        </p>
      ) : null}
    </div>
  );
}

export function RulesManagePage() {
  return (
    <ManagedResourcePage
      resource="rules"
      title="אוטומציות"
      description="הכללים החכמים של בובי."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            בדיקת ההתנגשויות נעשית אצל בובי. אם הוא אומר שהשינוי מתנגש — הוא לא יבוצע.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <RuleDetail item={item} />}
          emptyLabel="אין אוטומציות."
        />
      )}
    </ManagedResourcePage>
  );
}
