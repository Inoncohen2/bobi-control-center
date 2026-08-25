import { Bell, Moon } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { AdvancedDetails, AdvancedDisclosure } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { Toggle } from '@/components/ui/Toggle';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useNotifications, useToggleNotification } from '@/hooks/queries';
import type { NotificationRule, QuietHours } from '@/types/api';
import { formatMinutes, timeAgo } from '@/utils/format';
import { iconFor } from '@/utils/icons';

const QUIET_BEHAVIOR_LABELS: Record<QuietHours['behavior'], string> = {
  hold: 'לשלוח אחר כך',
  drop: 'לא לשלוח',
  send: 'לשלוח בכל מקרה',
};

const FREQUENCY_LABELS: Record<string, string> = {
  event: 'בכל פעם שקורה',
  hourly: 'לכל היותר פעם בשעה',
  daily: 'לכל היותר פעם ביום',
};

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="shrink-0 text-sm text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-left text-sm font-medium text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}

function RuleCard({
  rule,
  onToggle,
  pending,
}: {
  rule: NotificationRule;
  onToggle: (enabled: boolean) => void;
  pending: boolean;
}) {
  const Icon = iconFor(rule.icon);

  return (
    <Card as="li" className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300"
        >
          <Icon size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">{rule.name}</h3>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{rule.description}</p>
        </div>
        <Toggle
          checked={rule.enabled}
          onChange={onToggle}
          disabled={pending}
          label={`הפעלת ההתראה ${rule.name}`}
        />
      </div>

      <dl className="divide-y divide-slate-100 dark:divide-slate-700/60">
        <DetailRow label="נשלח אל" value={rule.recipients.join(', ') || '—'} />
        {rule.lead_time_minutes !== null ? (
          <DetailRow label="לפני האירוע" value={formatMinutes(rule.lead_time_minutes)} />
        ) : null}
        <DetailRow
          label="שעות שקטות"
          value={
            rule.quiet_hours.enabled ? (
              <span className="inline-flex items-center gap-1.5">
                <Moon aria-hidden="true" size={14} className="text-slate-400" />
                <span className="tabular-nums">
                  {rule.quiet_hours.start}–{rule.quiet_hours.end}
                </span>
                <Badge tone="muted">{QUIET_BEHAVIOR_LABELS[rule.quiet_hours.behavior]}</Badge>
              </span>
            ) : (
              'ללא'
            )
          }
        />
        <DetailRow label="תדירות" value={FREQUENCY_LABELS[rule.frequency] ?? rule.frequency} />
        <DetailRow label="המתנה בין התראות" value={formatMinutes(rule.cooldown_minutes)} />
        <DetailRow label="נשלח לאחרונה" value={timeAgo(rule.last_triggered)} />
        <DetailRow label="בשבוע האחרון" value={`${rule.trigger_count_7d} פעמים`} />
      </dl>

      {rule.conditions.length > 0 ? (
        <div>
          <p className="mb-1.5 text-sm text-slate-500 dark:text-slate-400">תנאים</p>
          <ul className="space-y-1">
            {rule.conditions.map((condition) => (
              <li
                key={condition.label}
                className="rounded-lg bg-slate-50 px-3 py-1.5 text-sm text-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
              >
                {condition.label}
                {condition.detail ? (
                  <span className="text-slate-400"> · {condition.detail}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <Badge tone={rule.enabled ? 'ok' : 'muted'} dot>
          {rule.enabled ? 'פעיל' : 'כבוי'}
        </Badge>
      </div>

      <AdvancedDisclosure>
        <AdvancedDetails advanced={rule.advanced} />
      </AdvancedDisclosure>
    </Card>
  );
}

export function NotificationsPage() {
  const query = useNotifications();
  const toggle = useToggleNotification();

  return (
    <>
      <PageHeader
        title="הודעות חכמות"
        description="מתי בובי יוזם הודעה מעצמו, ולמי."
      />

      {toggle.isError ? (
        <div className="mb-4">
          <ErrorState error={toggle.error} fallbackMessage="לא הצלחתי לשנות את ההתראה" />
        </div>
      ) : null}

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את ההודעות החכמות"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.rules.length === 0}
        empty={
          <EmptyState
            title="אין כרגע הודעות חכמות"
            description="כשיוגדרו כללים, הם יופיעו כאן."
            icon={<Bell size={32} />}
          />
        }
      >
        {(data) => (
          <ul className="grid gap-3 lg:grid-cols-2">
            {data.rules.map((rule) => (
              <RuleCard
                key={rule.id}
                rule={rule}
                pending={toggle.isPending && toggle.variables?.id === rule.id}
                onToggle={(enabled) => toggle.mutate({ id: rule.id, enabled })}
              />
            ))}
          </ul>
        )}
      </QueryBoundary>
    </>
  );
}
