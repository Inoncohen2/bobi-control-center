/**
 * What the control centre has done, newest first.
 *
 * The trail is written on the server, in the app's persistent directory, and
 * survives a restart. It carries no phone number, no LID and no token: those
 * are redacted before a line is written, so there is nothing here that could be
 * recovered by reading the file directly.
 */

import { useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Chip } from '@/components/ui/Field';
import { PageHeader } from '@/components/ui/PageHeader';
import { QueryBoundary } from '@/components/state/QueryBoundary';
import { useAudit } from '@/hooks/queries';
import type { AuditEntry } from '@/types/api';

const RESULT_TONES: Record<string, 'ok' | 'warning' | 'error' | 'neutral'> = {
  committed: 'ok',
  committed_unverified: 'warning',
  failed: 'error',
  refused: 'error',
  previewed: 'neutral',
};

const RESULT_LABELS: Record<string, string> = {
  committed: 'בוצע ואומת',
  committed_unverified: 'בוצע, לא אומת',
  failed: 'לא בוצע',
  refused: 'נדחה',
  previewed: 'תצוגה מקדימה',
};

const RESOURCE_LABELS: Record<string, string> = {
  tasks: 'משימות',
  features: 'תכונות',
  settings: 'הגדרות',
  users: 'משתמשים',
  shabbat: 'שעון שבת',
  rules: 'אוטומציות',
  calendar: 'יומן',
  devices: 'מכשירים',
  system: 'מערכת',
};

type Filter = 'all' | 'changes' | 'problems';

/** Previews are most of the trail and least of the interest; they can be hidden. */
const ALL = { id: 'all' as Filter, label: 'הכול', match: () => true };

const FILTERS: Array<{ id: Filter; label: string; match: (entry: AuditEntry) => boolean }> = [
  ALL,
  { id: 'changes', label: 'שינויים', match: (entry) => entry.stage === 'commit' },
  {
    id: 'problems',
    label: 'תקלות',
    match: (entry) => entry.result === 'failed' || entry.result === 'refused',
  },
];

export function ActivityPage() {
  const query = useAudit();
  const [filter, setFilter] = useState<Filter>('changes');
  const active = FILTERS.find((entry) => entry.id === filter) ?? ALL;

  const records = useMemo(
    () => (query.data?.records ?? []).filter(active.match),
    [query.data, active],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="פעילות"
        description="מה שונה דרך מרכז הניהול, ומה יצא מזה."
        action={
          <Button variant="secondary" onClick={() => void query.refetch()} loading={query.isFetching}>
            <RefreshCw aria-hidden className="h-4 w-4" />
            רענון
          </Button>
        }
      />

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((entry) => (
          <Chip key={entry.id} selected={entry.id === filter} onClick={() => setFilter(entry.id)}>
            {entry.label}
          </Chip>
        ))}
      </div>

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחנו לטעון את יומן הפעילות"
        onRetry={() => void query.refetch()}
      >
        {() =>
          records.length === 0 ? (
            <Card>
              <p className="text-sm text-slate-500 dark:text-slate-400">אין רשומות להצגה.</p>
            </Card>
          ) : (
            <Card>
              <ul className="divide-y divide-slate-200 dark:divide-slate-700">
                {records.map((entry) => (
                  <li key={entry.id} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {RESOURCE_LABELS[entry.resource_type] ?? entry.resource_type} ·{' '}
                          {entry.operation}
                        </p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {entry.timestamp.replace('T', ' ').slice(0, 19)}
                        </p>
                      </div>
                      <Badge tone={RESULT_TONES[entry.result] ?? 'neutral'}>
                        {RESULT_LABELS[entry.result] ?? entry.result}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )
        }
      </QueryBoundary>
    </div>
  );
}
