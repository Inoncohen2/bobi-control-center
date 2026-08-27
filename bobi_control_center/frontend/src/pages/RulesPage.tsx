import { useMemo } from 'react';
import { Timer } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useRules } from '@/hooks/queries';
import type { BridgeRule, ManagedItem } from '@/types/api';
import { timeAgo } from '@/utils/format';
import { ManagedSection } from '@/features/manage/ManagedSection';
import { ChangeDialog } from '@/features/manage/ChangeDialog';
import { operableWith, useManagedFamily } from '@/features/manage/useManagedFamily';
import { Switch } from '@/components/ui/Switch';
import { ResourceEditor } from '@/features/manage/ResourceEditor';

const KIND_LABELS: Record<string, string> = {
  schedule: 'תזמון',
  notification: 'התראה',
  automation: 'אוטומציה',
  scene: 'סצנה',
};

function RuleCard({
  rule,
  managed,
  writesEnabled,
  onToggle,
}: {
  rule: BridgeRule;
  managed: ManagedItem | undefined;
  writesEnabled: boolean;
  onToggle: (item: ManagedItem, next: boolean) => void;
}) {
  const kind = (rule.kind ?? '').toLowerCase();
  const operation = operableWith(managed, writesEnabled);
  const togglable = operation !== null && managed?.kind === 'toggle';

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
        {/* The switch says active or not, so the badge beside it would be the
            same fact twice. The badge stays where there is no switch. */}
        {togglable && managed ? (
          <Switch
            on={managed.value === true}
            label={rule.name}
            onChange={(next) => onToggle(managed, next)}
          />
        ) : (
          <Badge tone={rule.enabled === false ? 'muted' : 'ok'} dot>
            {rule.enabled === false ? 'מושבת' : 'פעיל'}
          </Badge>
        )}
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
        {/* No edit button. Rewriting a rule is a compound change the contract
            cannot express, so no bridge implements it — and a locked button
            repeated on every card is furniture, not information. The page says
            it once, above. */}
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
  const managed = useManagedFamily('rules');

  // Both halves name a rule by the summary of the same underlying item, so the
  // join is on that one field. A summary shared by two rules matches neither —
  // the same rule as on the devices screen, for the same reason.
  const managedByName = useMemo(() => {
    const seen = new Map<string, ManagedItem | null>();
    for (const item of managed.itemsById.values()) {
      if (item.kind !== 'toggle') continue;
      seen.set(item.label, seen.has(item.label) ? null : item);
    }
    return seen;
  }, [managed.itemsById]);

  return (
    <>
      <PageHeader
        title="כללים חכמים"
        description="הכללים הקנוניים של בובי — לא אוטומציות גולמיות של Home Assistant."
      />

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
              <RuleCard
                key={rule.id}
                rule={rule}
                managed={managedByName.get(rule.name) ?? undefined}
                writesEnabled={managed.writesEnabled}
                onToggle={(item, next) => managed.request(item, next)}
              />
            ))}
          </ul>
        )}
      </QueryBoundary>

      {/* Only when the switches could not be put on the cards: otherwise this
          is the same list of rules a second time, several screens down. */}
      {managed.available ? null : (
        <ManagedSection resource="rules" title="ניהול אוטומציות">
          {({ snapshot, request, writesEnabled }) => (
            <ResourceEditor snapshot={snapshot} onChange={request} writesEnabled={writesEnabled} />
          )}
        </ManagedSection>
      )}

      <ChangeDialog change={managed.change} />
    </>
  );
}
