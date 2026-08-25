import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useDiagnostics } from '@/hooks/queries';
import type { BridgeIssue, DiagnosticCheck } from '@/types/api';
import { cn } from '@/utils/cn';

/** The backend normalizes severity; this only collapses it to three buckets. */
function severityOf(issue: BridgeIssue): 'error' | 'warning' | 'ok' {
  const value = issue.severity.toLowerCase();
  if (value === 'error' || value === 'critical') return 'error';
  if (value === 'ok' || value === 'info') return 'ok';
  return 'warning';
}

const SECTIONS = [
  { severity: 'error' as const, title: 'שגיאות', icon: XCircle },
  { severity: 'warning' as const, title: 'אזהרות', icon: AlertTriangle },
  { severity: 'ok' as const, title: 'תקין', icon: CheckCircle2 },
];

const BORDER = {
  error: 'border-rose-200 dark:border-rose-500/30',
  warning: 'border-amber-200 dark:border-amber-500/30',
  ok: 'border-emerald-200 dark:border-emerald-500/30',
};

const ICON_COLOR = {
  error: 'text-rose-600 dark:text-rose-400',
  warning: 'text-amber-600 dark:text-amber-400',
  ok: 'text-emerald-600 dark:text-emerald-400',
};

function IssueCard({ issue }: { issue: BridgeIssue }) {
  const severity = severityOf(issue);
  const Icon = SECTIONS.find((section) => section.severity === severity)?.icon ?? AlertTriangle;

  // Entity ids and the machine code are technical and belong only in the
  // collapsed section.
  const technical = [
    issue.code ? `code: ${issue.code}` : null,
    ...issue.entity_ids,
    issue.detail,
  ]
    .filter(Boolean)
    .join('\n');

  return (
    <Card as="li" className={BORDER[severity]}>
      <div className="flex items-start gap-3">
        <Icon
          aria-hidden="true"
          size={20}
          className={cn('mt-0.5 shrink-0', ICON_COLOR[severity])}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">{issue.title}</h3>
            {issue.component ? <Badge tone="neutral">{issue.component}</Badge> : null}
          </div>

          {issue.message ? (
            <p className="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
              {issue.message}
            </p>
          ) : null}

          {issue.suggested_action ? (
            <div className="mt-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                מה אפשר לעשות
              </p>
              <p className="mt-0.5 text-sm text-slate-700 dark:text-slate-200">
                {issue.suggested_action}
              </p>
            </div>
          ) : null}

          {technical ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-sm text-slate-500 hover:underline dark:text-slate-400">
                פרטים טכניים
              </summary>
              <pre
                dir="ltr"
                className="mt-2 overflow-x-auto rounded-xl bg-slate-50 p-3 text-left text-xs text-slate-700 dark:bg-slate-900/50 dark:text-slate-300"
              >
                {technical}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

function CheckRow({ check }: { check: DiagnosticCheck }) {
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{check.label}</p>
        {check.detail ? (
          <p className="text-xs text-slate-500 dark:text-slate-400">{check.detail}</p>
        ) : null}
      </div>
      {/* `ok` is null for a measurement such as a count, which is neither a
          pass nor a failure — it is shown as a plain figure. */}
      {check.ok === null ? (
        <Badge tone="neutral">{check.value ?? '—'}</Badge>
      ) : (
        <Badge tone={check.ok ? 'ok' : 'warning'} dot>
          {check.ok ? 'תקין' : 'דורש בדיקה'}
        </Badge>
      )}
    </li>
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
        errorMessage="לא הצלחתי לקבל את רשימת התקלות מ-Home Assistant"
        loadingLabel="בודק תקלות…"
        onRetry={() => void query.refetch()}
      >
        {(report) => {
          const issues = report.issues;
          const counts = {
            error: issues.filter((issue) => severityOf(issue) === 'error').length,
            warning: issues.filter((issue) => severityOf(issue) === 'warning').length,
            ok: issues.filter((issue) => severityOf(issue) === 'ok').length,
          };

          return (
            <div className="space-y-8">
              <div className="grid grid-cols-3 gap-3">
                <Card className="p-4 text-center">
                  <p className="text-2xl font-bold text-rose-600 dark:text-rose-400">
                    {counts.error}
                  </p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">שגיאות</p>
                </Card>
                <Card className="p-4 text-center">
                  <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                    {counts.warning}
                  </p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">אזהרות</p>
                </Card>
                <Card className="p-4 text-center">
                  <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                    {report.checks.filter((check) => check.ok !== false).length}
                  </p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">בדיקות תקינות</p>
                </Card>
              </div>

              {issues.length === 0 ? (
                <EmptyState
                  title="לא נמצאו תקלות 🎉"
                  description="הכול עובד כמו שצריך."
                  icon={<CheckCircle2 size={32} />}
                />
              ) : (
                SECTIONS.map((section) => {
                  const sectionIssues = issues.filter(
                    (issue) => severityOf(issue) === section.severity,
                  );
                  if (sectionIssues.length === 0) return null;
                  return (
                    <section key={section.severity} aria-labelledby={`sec-${section.severity}`}>
                      <h2
                        id={`sec-${section.severity}`}
                        className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                      >
                        {section.title} ({sectionIssues.length})
                      </h2>
                      <ul className="space-y-3">
                        {sectionIssues.map((issue) => (
                          <IssueCard key={issue.id} issue={issue} />
                        ))}
                      </ul>
                    </section>
                  );
                })
              )}

              {report.checks.length > 0 ? (
                <section aria-labelledby="checks-heading">
                  <SectionTitle>
                    <span id="checks-heading">בדיקות שבוצעו</span>
                  </SectionTitle>
                  <Card className="p-0">
                    <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                      {report.checks.map((check) => (
                        <CheckRow key={check.id} check={check} />
                      ))}
                    </ul>
                  </Card>
                </section>
              ) : null}
            </div>
          );
        }}
      </QueryBoundary>
    </>
  );
}
