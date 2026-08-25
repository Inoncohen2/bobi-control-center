import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useDiagnostics } from '@/hooks/queries';
import type { DiagnosticIssue, Severity } from '@/types/api';
import { formatDateTime, timeAgo } from '@/utils/format';

const SECTIONS: Array<{ severity: Severity; title: string; icon: typeof CheckCircle2 }> = [
  { severity: 'error', title: 'שגיאות', icon: XCircle },
  { severity: 'warning', title: 'אזהרות', icon: AlertTriangle },
  { severity: 'ok', title: 'תקין', icon: CheckCircle2 },
];

const BORDER: Record<Severity, string> = {
  error: 'border-rose-200 dark:border-rose-500/30',
  warning: 'border-amber-200 dark:border-amber-500/30',
  ok: 'border-emerald-200 dark:border-emerald-500/30',
};

const ICON_COLOR: Record<Severity, string> = {
  error: 'text-rose-600 dark:text-rose-400',
  warning: 'text-amber-600 dark:text-amber-400',
  ok: 'text-emerald-600 dark:text-emerald-400',
};

function IssueCard({ issue }: { issue: DiagnosticIssue }) {
  const Icon = SECTIONS.find((section) => section.severity === issue.severity)?.icon ?? AlertTriangle;

  return (
    <Card as="li" className={BORDER[issue.severity]}>
      <div className="flex items-start gap-3">
        <Icon
          aria-hidden="true"
          size={20}
          className={`mt-0.5 shrink-0 ${ICON_COLOR[issue.severity]}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {/* Phrased for a household member, not an engineer. */}
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">{issue.title}</h3>
            <Badge tone="neutral">{issue.component}</Badge>
          </div>

          <p className="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
            {issue.description}
          </p>

          {issue.suggested_action ? (
            <div className="mt-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">מה אפשר לעשות</p>
              <p className="mt-0.5 text-sm text-slate-700 dark:text-slate-200">
                {issue.suggested_action}
              </p>
            </div>
          ) : null}

          <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400 dark:text-slate-500">
            <div className="flex gap-1">
              <dt>נראה לראשונה:</dt>
              <dd>{formatDateTime(issue.first_seen)}</dd>
            </div>
            <div className="flex gap-1">
              <dt>לאחרונה:</dt>
              <dd>{timeAgo(issue.last_seen)}</dd>
            </div>
            <div className="flex gap-1">
              <dt>מספר פעמים:</dt>
              <dd>{issue.occurrences}</dd>
            </div>
          </dl>

          {issue.technical_details ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-sm text-slate-500 hover:underline dark:text-slate-400">
                פרטים טכניים
              </summary>
              <pre
                dir="ltr"
                className="mt-2 overflow-x-auto rounded-xl bg-slate-50 p-3 text-left text-xs text-slate-700 dark:bg-slate-900/50 dark:text-slate-300"
              >
                {issue.technical_details}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

export function DiagnosticsPage() {
  const query = useDiagnostics();

  return (
    <>
      <PageHeader title="תקלות" description="מה לא עובד כרגע, ומה אפשר לעשות בקשר לזה." />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את התקלות"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.issues.length === 0}
        empty={
          <EmptyState
            title="לא נמצאו תקלות 🎉"
            description="הכול עובד כמו שצריך."
            icon={<CheckCircle2 size={32} />}
          />
        }
      >
        {(report) => (
          <div className="space-y-8">
            <div className="grid grid-cols-3 gap-3">
              <Card className="p-4 text-center">
                <p className="text-2xl font-bold text-rose-600 dark:text-rose-400">
                  {report.error_count}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-400">שגיאות</p>
              </Card>
              <Card className="p-4 text-center">
                <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                  {report.warning_count}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-400">אזהרות</p>
              </Card>
              <Card className="p-4 text-center">
                <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                  {report.ok_count}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-400">תקין</p>
              </Card>
            </div>

            {SECTIONS.map((section) => {
              const issues = report.issues.filter((issue) => issue.severity === section.severity);
              if (issues.length === 0) return null;
              return (
                <section key={section.severity} aria-labelledby={`section-${section.severity}`}>
                  <h2
                    id={`section-${section.severity}`}
                    className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                  >
                    {section.title} ({issues.length})
                  </h2>
                  <ul className="space-y-3">
                    {issues.map((issue) => (
                      <IssueCard key={issue.id} issue={issue} />
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
