import { Link } from 'react-router-dom';
import { CheckCircle2, Play, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useRunTests, useTests } from '@/hooks/queries';
import type { TestSuite } from '@/types/api';
import { timeAgo } from '@/utils/format';

function SuiteCard({ suite }: { suite: TestSuite }) {
  const allPassed = suite.failed === 0;
  const percent = suite.total > 0 ? Math.round((suite.passed / suite.total) * 100) : 0;

  return (
    <Card as="li">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">{suite.name}</h3>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{suite.description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-lg font-bold tabular-nums text-slate-900 dark:text-slate-100">
            {suite.passed} / {suite.total}
          </span>
          {allPassed ? (
            <CheckCircle2
              aria-label="כל הבדיקות עברו"
              size={20}
              className="text-emerald-600 dark:text-emerald-400"
            />
          ) : (
            <XCircle
              aria-label={`${suite.failed} בדיקות נכשלו`}
              size={20}
              className="text-rose-600 dark:text-rose-400"
            />
          )}
        </div>
      </div>

      <div className="mt-3">
        <div
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${suite.name}: ${percent}% עברו`}
          className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700"
        >
          <div
            className={allPassed ? 'h-full bg-emerald-500' : 'h-full bg-amber-500'}
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
        <span>הרצה אחרונה {timeAgo(suite.last_run)}</span>
        <span aria-hidden="true">·</span>
        <span>{(suite.duration_ms / 1000).toFixed(1)} שניות</span>
        {suite.failed > 0 ? <Badge tone="error">{suite.failed} נכשלו</Badge> : null}
      </div>

      {suite.cases.length > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-slate-500 hover:underline dark:text-slate-400">
            דוגמאות מקרי בדיקה
          </summary>
          <ul className="mt-2 space-y-1">
            {suite.cases.map((testCase) => (
              <li
                key={testCase.id}
                className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-1.5 text-sm dark:bg-slate-900/40"
              >
                <span className="text-slate-700 dark:text-slate-200">{testCase.name}</span>
                <Badge tone={testCase.passed ? 'ok' : 'error'}>
                  {testCase.passed ? 'עבר' : 'נכשל'}
                </Badge>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}

export function TestsPage() {
  const query = useTests();
  const run = useRunTests();

  return (
    <>
      <PageHeader
        title="בדיקות אוטומטיות"
        description="חבילות בדיקה שמוודאות שבובי ממשיך להבין נכון."
        action={
          <Button icon={<Play size={16} />} loading={run.isPending} onClick={() => run.mutate()}>
            הרץ בדיקות
          </Button>
        }
      />

      {run.isError ? (
        <div className="mb-4">
          <ErrorState error={run.error} fallbackMessage="לא הצלחתי להריץ את הבדיקות" />
        </div>
      ) : null}

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את הבדיקות"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.suites.length === 0}
        empty={<EmptyState title="אין עדיין חבילות בדיקה" />}
      >
        {(report) => (
          <div className="space-y-5">
            <Card className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-3xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
                  {report.passed} / {report.total}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  בדיקות עברו · הרצה אחרונה {timeAgo(report.last_run)}
                </p>
              </div>
              <Badge tone={report.failed === 0 ? 'ok' : 'error'} dot>
                {report.failed === 0 ? 'הכול עובר' : `${report.failed} נכשלו`}
              </Badge>
            </Card>

            <ul className="grid gap-3 lg:grid-cols-2">
              {report.suites.map((suite) => (
                <SuiteCard key={suite.id} suite={suite} />
              ))}
            </ul>

            <p className="rounded-xl bg-slate-100 p-3 text-sm text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {report.note} כדי לבדוק משפט מסוים בעצמכם, אפשר להשתמש ב
              <Link to="/test-center" className="mx-1 font-medium text-bobi-700 hover:underline dark:text-bobi-300">
                מרכז הבדיקות
              </Link>
              .
            </p>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
