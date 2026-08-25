import { Link } from 'react-router-dom';
import {
  Activity,
  AirVent,
  AlertTriangle,
  Bell,
  Bot,
  CameraOff,
  Flame,
  CheckSquare,
  ChevronLeft,
  HelpCircle,
  Lightbulb,
  type LucideIcon,
} from 'lucide-react';

import { Badge, healthTone, severityTone } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useStatus } from '@/hooks/queries';
import type { ActivityEntry, AttentionItem, ComponentHealth, StatItem } from '@/types/api';
import { cn } from '@/utils/cn';

/** Icon names come from the API as strings; unknown names fall back gracefully. */
const ACTIVITY_ICONS: Record<string, LucideIcon> = {
  bell: Bell,
  'air-vent': AirVent,
  candlestick: Flame,
  'check-square': CheckSquare,
  'camera-off': CameraOff,
  lightbulb: Lightbulb,
  bot: Bot,
  'help-circle': HelpCircle,
  activity: Activity,
};

function HealthCard({ component }: { component: ComponentHealth }) {
  return (
    <Card className="p-4">
      <p className="text-sm text-slate-500 dark:text-slate-400">{component.name}</p>
      <div className="mt-1.5">
        <Badge tone={healthTone[component.state]} dot>
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

function StatCard({ stat }: { stat: StatItem }) {
  const isWarning = stat.severity === 'warning' && stat.value > 0;
  return (
    <Card className={cn('p-4', isWarning && 'border-amber-300 dark:border-amber-500/40')}>
      <p
        className={cn(
          'text-3xl font-bold tabular-nums',
          isWarning ? 'text-amber-600 dark:text-amber-400' : 'text-slate-900 dark:text-slate-50',
        )}
      >
        {stat.value}
      </p>
      <p className="mt-1 text-sm font-medium text-slate-600 dark:text-slate-300">{stat.label}</p>
      {stat.hint ? (
        <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{stat.hint}</p>
      ) : null}
    </Card>
  );
}

function ActivityRow({ entry }: { entry: ActivityEntry }) {
  const Icon = ACTIVITY_ICONS[entry.icon] ?? Activity;
  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <span
          aria-hidden="true"
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
            entry.severity === 'warning'
              ? 'bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400'
              : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-300',
          )}
        >
          <Icon size={16} />
        </span>
        <span aria-hidden="true" className="mt-1 w-px flex-1 bg-slate-200 dark:bg-slate-700" />
      </div>
      <div className="min-w-0 flex-1 pb-5">
        <div className="flex items-baseline gap-2">
          <time className="shrink-0 text-xs font-medium tabular-nums text-slate-400 dark:text-slate-500">
            {entry.time}
          </time>
          <p className="min-w-0 text-sm font-medium text-slate-800 dark:text-slate-200">
            {entry.title}
          </p>
        </div>
        {entry.detail ? (
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{entry.detail}</p>
        ) : null}
      </div>
    </li>
  );
}

function AttentionCard({ item }: { item: AttentionItem }) {
  return (
    <Card className="border-amber-200 bg-amber-50/40 p-4 dark:border-amber-500/30 dark:bg-amber-500/5">
      <div className="flex items-start gap-3">
        <AlertTriangle
          aria-hidden="true"
          size={18}
          className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium text-slate-900 dark:text-slate-100">{item.title}</p>
            <Badge tone={severityTone[item.severity]}>{item.component}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.description}</p>

          {item.technical_details ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-500 hover:underline dark:text-slate-400">
                פרטים טכניים
              </summary>
              <pre
                dir="ltr"
                className="mt-1.5 overflow-x-auto rounded-lg bg-white/70 p-2 text-left text-xs text-slate-600 dark:bg-slate-900/50 dark:text-slate-300"
              >
                {item.technical_details}
              </pre>
            </details>
          ) : null}

          {item.action_href && item.action_label ? (
            <Link
              to={item.action_href}
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-bobi-700 hover:underline dark:text-bobi-300"
            >
              {item.action_label}
              <ChevronLeft aria-hidden="true" size={14} />
            </Link>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

export function DashboardPage() {
  const query = useStatus();

  return (
    <>
      <PageHeader
        title="🤖 בובי"
        description="מבט מהיר על מה שקורה בבית ובמה כדאי לטפל."
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את מצב המערכת"
        onRetry={() => void query.refetch()}
      >
        {(status) => (
          <div className="space-y-8">
            <section aria-labelledby="health-heading">
              <h2 id="health-heading" className="sr-only">
                מצב רכיבי המערכת
              </h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {status.components.map((component) => (
                  <HealthCard key={component.id} component={component} />
                ))}
              </div>
            </section>

            <section aria-labelledby="stats-heading">
              <h2 id="stats-heading" className="sr-only">
                נתונים כלליים
              </h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                {status.stats.map((stat) => (
                  <StatCard key={stat.id} stat={stat} />
                ))}
              </div>
            </section>

            <section aria-labelledby="activity-heading">
              <SectionTitle>
                <span id="activity-heading">מה קורה עכשיו</span>
              </SectionTitle>
              <Card>
                {status.activity.length === 0 ? (
                  <EmptyState title="עדיין לא קרה כלום היום" />
                ) : (
                  <ul className="-mb-5">
                    {status.activity.map((entry) => (
                      <ActivityRow key={entry.id} entry={entry} />
                    ))}
                  </ul>
                )}
              </Card>
            </section>

            <section aria-labelledby="attention-heading">
              <SectionTitle>
                <span id="attention-heading">דורש תשומת לב</span>
              </SectionTitle>
              {status.attention.length === 0 ? (
                <EmptyState title="הכול תקין 🎉" description="אין כרגע שום דבר שדורש טיפול." />
              ) : (
                <div className="space-y-3">
                  {status.attention.map((item) => (
                    <AttentionCard key={item.id} item={item} />
                  ))}
                </div>
              )}
            </section>

            <p className="pt-2 text-center text-xs text-slate-400 dark:text-slate-500">
              גרסה {status.version} · מקור נתונים: {status.adapter} ·{' '}
              {status.read_only ? 'לקריאה בלבד' : 'כתיבה מאופשרת'}
            </p>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
