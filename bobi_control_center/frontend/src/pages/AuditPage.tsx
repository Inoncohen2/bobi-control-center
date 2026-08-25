import { History } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useAudit } from '@/hooks/queries';
import type { AuditEntry } from '@/types/api';
import { SOURCE_LABELS, formatDateTime, timeAgo } from '@/utils/format';

const RESOURCE_LABELS: Record<string, string> = {
  automation: 'אוטומציה',
  capability: 'יכולת',
  shabbat: 'שעון שבת',
  shabbat_template: 'תבנית שבת',
  notification: 'התראה',
  user: 'משתמש',
  task: 'משימה',
  tests: 'בדיקות',
  system: 'מערכת',
};

function Row({ entry }: { entry: AuditEntry }) {
  const hasDiff = entry.before !== null || entry.after !== null;

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm text-slate-900 dark:text-slate-100">
          <span className="font-medium">{entry.user}</span> {entry.operation_label}{' '}
          {RESOURCE_LABELS[entry.resource_type] ?? entry.resource_type}
          {entry.resource_label ? (
            <span className="font-medium"> „{entry.resource_label}”</span>
          ) : null}
        </p>
        <div className="flex items-center gap-2">
          <Badge tone="muted">{SOURCE_LABELS[entry.source] ?? entry.source}</Badge>
          <time
            dateTime={entry.timestamp}
            title={formatDateTime(entry.timestamp)}
            className="text-xs text-slate-400 dark:text-slate-500"
          >
            {timeAgo(entry.timestamp)}
          </time>
        </div>
      </div>

      {hasDiff ? (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-xs text-slate-500 hover:underline dark:text-slate-400">
            מה השתנה
          </summary>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs text-slate-400">לפני</p>
              <pre
                dir="ltr"
                className="overflow-x-auto rounded-lg bg-slate-50 p-2 text-left text-xs text-slate-600 dark:bg-slate-900/50 dark:text-slate-300"
              >
                {entry.before ? JSON.stringify(entry.before, null, 2) : '—'}
              </pre>
            </div>
            <div>
              <p className="mb-1 text-xs text-slate-400">אחרי</p>
              <pre
                dir="ltr"
                className="overflow-x-auto rounded-lg bg-slate-50 p-2 text-left text-xs text-slate-600 dark:bg-slate-900/50 dark:text-slate-300"
              >
                {entry.after ? JSON.stringify(entry.after, null, 2) : '—'}
              </pre>
            </div>
          </div>
        </details>
      ) : null}
    </li>
  );
}

export function AuditPage() {
  const query = useAudit();

  return (
    <>
      <PageHeader
        title="יומן פעולות"
        description="כל שינוי שנעשה בבובי — מי, מה, ומאיפה."
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את יומן הפעולות"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.entries.length === 0}
        empty={
          <EmptyState
            title="עדיין לא נרשמו פעולות"
            description="כל שינוי שתעשו יופיע כאן."
            icon={<History size={32} />}
          />
        }
      >
        {(log) => (
          <Card className="p-0">
            <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
              {log.entries.map((entry) => (
                <Row key={entry.id} entry={entry} />
              ))}
            </ul>
          </Card>
        )}
      </QueryBoundary>
    </>
  );
}
