import { Timer } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { DisabledAction, ReadOnlyNotice } from '@/components/ui/ReadOnly';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useRules } from '@/hooks/queries';
import type { BridgeRule } from '@/types/api';
import { timeAgo } from '@/utils/format';

const KIND_LABELS: Record<string, string> = {
  schedule: 'תזמון',
  notification: 'התראה',
  automation: 'אוטומציה',
  scene: 'סצנה',
};

function RuleCard({ rule }: { rule: BridgeRule }) {
  const kind = (rule.kind ?? '').toLowerCase();

  return (
    <Card as="li" className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">{rule.name}</h3>
          {rule.description ? (
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              {rule.description}
            </p>
          ) : null}
        </div>
        <Badge tone={rule.enabled === false ? 'muted' : 'ok'} dot>
          {rule.enabled === false ? 'מושבת' : 'פעיל'}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
        {rule.kind ? <Badge tone="neutral">{KIND_LABELS[kind] ?? rule.kind}</Badge> : null}
        {rule.schedule ? (
          <span dir="ltr" className="tabular-nums">
            {rule.schedule}
          </span>
        ) : null}
        {rule.trigger ? <span>{rule.trigger}</span> : null}
      </div>

      {rule.targets.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {rule.targets.map((target) => (
            <Badge key={target} tone="info">
              {target}
            </Badge>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-700/60">
        <span className="text-xs text-slate-400 dark:text-slate-500">
          הופעל לאחרונה {timeAgo(rule.last_triggered)}
        </span>
        {/* Editing rules writes to Home Assistant, so it is inert in Phase 2. */}
        <DisabledAction>עריכה</DisabledAction>
      </div>

      <AdvancedDisclosure title="פרטים טכניים">
        <TechnicalDetails
          source={rule as unknown as Record<string, unknown>}
          known={[
            ['id', 'מזהה'],
            ['entity_id', 'מזהה טכני'],
            ['kind', 'סוג'],
          ]}
          extra={rule.extra}
        />
      </AdvancedDisclosure>
    </Card>
  );
}

export function RulesPage() {
  const query = useRules();

  return (
    <>
      <PageHeader
        title="כללים חכמים"
        description="הכללים הקנוניים של בובי — לא אוטומציות גולמיות של Home Assistant."
      />

      <ReadOnlyNotice className="mb-4">
        הכללים מוצגים לקריאה בלבד. יצירה, עריכה ומחיקה יהיו זמינות בשלב הבא.
      </ReadOnlyNotice>

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את הכללים החכמים מ-Home Assistant"
        loadingLabel="טוען כללים…"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.rules.length === 0}
        empty={
          <EmptyState
            title="אין כרגע כללים חכמים"
            description="כשבובי ירשום כללים, הם יופיעו כאן."
            icon={<Timer size={32} />}
          />
        }
      >
        {(data) => (
          <ul className="space-y-3">
            {data.rules.map((rule) => (
              <RuleCard key={rule.id} rule={rule} />
            ))}
          </ul>
        )}
      </QueryBoundary>
    </>
  );
}
