import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, ChevronLeft, PlugZap, XCircle } from 'lucide-react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '@/components/state/QueryBoundary';
import { useConnection, useDiagnostics, useStatus } from '@/hooks/queries';
import type { AiStatus, BridgeIssue, FeatureFlag, StatusComponent, UsersSummary } from '@/types/api';
import { countLabel } from '@/utils/format';
import { cn } from '@/utils/cn';

/** `ok` is resolved by the backend, so tone follows it directly. */
function componentTone(component: StatusComponent): BadgeTone {
  if (component.ok === true) return 'ok';
  if (component.ok === false) return 'warning';
  return 'muted';
}

function HealthCard({ component }: { component: StatusComponent }) {
  return (
    <Card className="p-4">
      <p className="text-sm text-slate-500 dark:text-slate-400">{component.name}</p>
      <div className="mt-1.5">
        <Badge tone={componentTone(component)} dot>
          {component.label}
        </Badge>
      </div>
      {component.detail ? (
        <p className="mt-2 text-xs leading-relaxed text-slate-400 dark:text-slate-500">
          {component.detail}
        </p>
      ) : null}
    </Card>
  );
}

function StatCard({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <Card className={cn('p-4', warn && value > 0 && 'border-amber-300 dark:border-amber-500/40')}>
      <p
        className={cn(
          'text-3xl font-bold tabular-nums',
          warn && value > 0
            ? 'text-amber-600 dark:text-amber-400'
            : 'text-slate-900 dark:text-slate-50',
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-sm font-medium text-slate-600 dark:text-slate-300">{label}</p>
    </Card>
  );
}

/**
 * The AI fallback's fast paths.
 *
 * The bridge may report them as a count or as the path names themselves, and
 * the backend normalizes both into a count plus a (possibly empty) list.
 */
function FastPathsCard({ ai }: { ai: AiStatus }) {
  const headline =
    ai.fast_paths_count !== null
      ? String(ai.fast_paths_count)
      : ai.fast_paths_enabled === true
        ? 'פעיל'
        : ai.fast_paths_enabled === false
          ? 'כבוי'
          : '—';

  return (
    <Card className="p-4">
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">מסלולים מהירים</p>
      <p className="mt-1 text-3xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
        {headline}
      </p>
      <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
        פקודות שבובי מזהה בעצמו, בלי לפנות ל-AI
      </p>
      {ai.fast_paths.length > 0 ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {ai.fast_paths.map((path) => (
            <Badge key={path} tone="neutral">
              <span dir="ltr">{path}</span>
            </Badge>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function UsersCard({ users }: { users: UsersSummary }) {
  const rows: Array<[string, number]> = [
    ['פעילים', users.active],
    ['סה״כ', users.total],
    ['מנהלים', users.admins],
  ].filter((row): row is [string, number] => typeof row[1] === 'number');

  return (
    <Card className="p-4">
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">משתמשי הבית</p>
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-2">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dd className="text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
              {value}
            </dd>
            <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
          </div>
        ))}
      </dl>
      {users.names.length > 0 ? (
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">{users.names.join(' · ')}</p>
      ) : null}
    </Card>
  );
}

/** Bobi's feature toggles. READ-ONLY in Phase 2. */
function FeaturesCard({ features }: { features: FeatureFlag[] }) {
  return (
    <Card className="p-4">
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">תכונות</p>
      <ul className="mt-2.5 flex flex-wrap gap-1.5">
        {features.map((feature) => (
          <li key={feature.id}>
            <Badge tone={feature.enabled === false ? 'muted' : 'ok'} dot>
              {feature.label}
            </Badge>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-xs text-slate-400 dark:text-slate-500">
        עריכה תהיה זמינה בשלב הבא
      </p>
    </Card>
  );
}

function IssueRow({ issue }: { issue: BridgeIssue }) {
  const isError = issue.severity.toLowerCase() === 'error';
  // Technical identifiers stay out of the summary and live in the disclosure.
  const technical = [
    issue.code ? `code: ${issue.code}` : null,
    ...issue.entity_ids,
    issue.detail,
  ]
    .filter(Boolean)
    .join('\n');

  return (
    <Card
      as="li"
      className={cn(
        'p-4',
        isError
          ? 'border-rose-200 bg-rose-50/40 dark:border-rose-500/30 dark:bg-rose-500/5'
          : 'border-amber-200 bg-amber-50/40 dark:border-amber-500/30 dark:bg-amber-500/5',
      )}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className={cn(
            'mt-0.5 shrink-0',
            isError ? 'text-rose-600 dark:text-rose-400' : 'text-amber-600 dark:text-amber-400',
          )}
        >
          {isError ? <XCircle size={18} /> : <AlertTriangle size={18} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium text-slate-900 dark:text-slate-100">{issue.title}</p>
            {issue.component ? <Badge tone="neutral">{issue.component}</Badge> : null}
          </div>
          {issue.message ? (
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{issue.message}</p>
          ) : null}
          {issue.suggested_action ? (
            <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">
              {issue.suggested_action}
            </p>
          ) : null}

          {technical ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-500 hover:underline dark:text-slate-400">
                פרטים טכניים
              </summary>
              <pre
                dir="ltr"
                className="mt-1.5 overflow-x-auto rounded-lg bg-white/70 p-2 text-left text-xs text-slate-600 dark:bg-slate-900/50 dark:text-slate-300"
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

export function DashboardPage() {
  const status = useStatus();
  const diagnostics = useDiagnostics();
  const connection = useConnection();

  const counts = Object.entries(status.data?.counts ?? {});
  const issues = diagnostics.data?.issues ?? [];
  // Sections the bridge reports beyond the health row.
  const ai = status.data?.ai ?? null;
  const users = status.data?.users ?? null;
  const features = status.data?.features ?? [];

  return (
    <>
      <PageHeader title="🤖 בובי" description="מבט מהיר על מה שקורה בבית ובמה כדאי לטפל." />

      {connection.data && !connection.data.connected ? (
        <div className="mb-4 flex items-start gap-2.5 rounded-2xl border border-amber-200 bg-amber-50 p-3.5 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <PlugZap aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
          <p>{connection.data.detail ?? 'אין חיבור ל-Home Assistant'}</p>
        </div>
      ) : null}

      {status.isLoading ? <LoadingState /> : null}

      {status.error ? (
        <ErrorState
          error={status.error}
          fallbackMessage="לא הצלחתי לקבל נתונים מ-Home Assistant"
          onRetry={() => void status.refetch()}
        />
      ) : null}

      {status.data ? (
        <div className="space-y-8">
          <section aria-labelledby="health-heading">
            <h2 id="health-heading" className="sr-only">
              מצב רכיבי המערכת
            </h2>
            {status.data.components.length === 0 ? (
              <EmptyState title="אין מידע על רכיבי המערכת" />
            ) : (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {status.data.components.map((component) => (
                  <HealthCard key={component.id} component={component} />
                ))}
              </div>
            )}
          </section>

          {ai || users || features.length > 0 ? (
            <section aria-labelledby="bobi-heading">
              <SectionTitle>
                <span id="bobi-heading">בובי בקצרה</span>
              </SectionTitle>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {ai ? <FastPathsCard ai={ai} /> : null}
                {users ? <UsersCard users={users} /> : null}
                {features.length > 0 ? <FeaturesCard features={features} /> : null}
              </div>
            </section>
          ) : null}

          {counts.length > 0 ? (
            <section aria-labelledby="stats-heading">
              <h2 id="stats-heading" className="sr-only">
                נתונים כלליים
              </h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                {counts.map(([key, value]) => (
                  <StatCard
                    key={key}
                    label={countLabel(key)}
                    value={value}
                    warn={key === 'issues'}
                  />
                ))}
              </div>
            </section>
          ) : null}

          <section aria-labelledby="attention-heading">
            <SectionTitle
              action={
                <Link
                  to="/diagnostics"
                  className="inline-flex items-center gap-1 text-sm font-medium text-bobi-700 hover:underline dark:text-bobi-300"
                >
                  למסך התקלות
                  <ChevronLeft aria-hidden="true" size={14} />
                </Link>
              }
            >
              <span id="attention-heading">דורש תשומת לב</span>
            </SectionTitle>

            {diagnostics.isLoading ? <LoadingState label="בודק תקלות…" /> : null}

            {diagnostics.error ? (
              <ErrorState
                error={diagnostics.error}
                fallbackMessage="לא הצלחתי לקבל את רשימת התקלות"
                onRetry={() => void diagnostics.refetch()}
              />
            ) : null}

            {diagnostics.data && issues.length === 0 ? (
              <EmptyState
                title="לא נמצאו תקלות 🎉"
                description="הכול עובד כמו שצריך."
                icon={<CheckCircle2 size={32} />}
              />
            ) : null}

            {issues.length > 0 ? (
              <ul className="space-y-3">
                {issues.slice(0, 5).map((issue) => (
                  <IssueRow key={issue.id} issue={issue} />
                ))}
              </ul>
            ) : null}
          </section>

          <p className="pt-2 text-center text-xs text-slate-400 dark:text-slate-500">
            {status.data.version ? `גרסה ${status.data.version} · ` : ''}
            מקור נתונים: {connection.data?.adapter ?? '—'} · קריאה בלבד
          </p>
        </div>
      ) : null}
    </>
  );
}
