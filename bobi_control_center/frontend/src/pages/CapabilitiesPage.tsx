import { useMemo, useState } from 'react';
import { Cpu, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
import { NextPhaseBadge, ReadOnlyToggle } from '@/components/ui/ReadOnly';
import { ChangeDialog } from '@/features/manage/ChangeDialog';
import { useManagedChange } from '@/features/manage/useManagedChange';
import { ManagementNotice, useResource } from '@/features/manage/ManagementNotice';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { keys, useCapabilities, useManagementContract } from '@/hooks/queries';
import { cn } from '@/utils/cn';
import type { BridgeCapability, CapabilityToggle, ManagedTarget } from '@/types/api';
import { RISK_LABELS, RISK_TONE } from '@/utils/format';

/** Fallback grouping when the registry entry carries no `group`. */
const UNGROUPED = 'יכולות נוספות';

const TECHNICAL_FIELDS: Array<[string, string]> = [
  ['handler', 'Handler'],
  ['id', 'מזהה'],
  ['local', 'מעובד מקומית'],
  ['local_after_parse', 'מקומי אחרי פירוק'],
  ['risk', 'רמת סיכון'],
];

function CapabilityDetail({
  capability,
  onClose,
}: {
  capability: BridgeCapability;
  onClose: () => void;
}) {
  const risk = (capability.risk ?? '').toLowerCase();

  return (
    <Modal
      open
      onClose={onClose}
      title={capability.label}
      description={capability.example ? `לדוגמה: ${capability.example}` : undefined}
    >
      <div className="flex flex-wrap gap-2">
        {capability.risk ? (
          <Badge tone={RISK_TONE[risk] ?? 'muted'} dot>
            {RISK_LABELS[risk] ?? capability.risk}
          </Badge>
        ) : null}
        {capability.local === true ? <Badge tone="info">מעובד מקומית</Badge> : null}
        {capability.local_after_parse === true ? (
          <Badge tone="info">מקומי אחרי פירוק</Badge>
        ) : null}
        {capability.local === false ? <Badge tone="muted">נעזר בשירות חיצוני</Badge> : null}
      </div>

      {capability.example ? (
        <div className="mt-4 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
            דוגמה למשפט שבובי יבין
          </p>
          <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">
            „{capability.example}”
          </p>
        </div>
      ) : null}

      <AdvancedDisclosure title="פרטים טכניים">
        <TechnicalDetails
          source={capability as unknown as Record<string, unknown>}
          known={TECHNICAL_FIELDS}
          extra={capability.extra}
        />
      </AdvancedDisclosure>
    </Modal>
  );
}

function CapabilityCard({
  capability,
  onOpen,
}: {
  capability: BridgeCapability;
  onOpen: () => void;
}) {
  const risk = (capability.risk ?? '').toLowerCase();

  return (
    <Card interactive as="li" className="flex flex-col">
      <button type="button" onClick={onOpen} className="flex-1 text-right">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">{capability.label}</h3>
        {capability.example ? (
          <p className="mt-1 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            „{capability.example}”
          </p>
        ) : null}
      </button>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {capability.risk ? (
          <Badge tone={RISK_TONE[risk] ?? 'muted'} dot>
            {RISK_LABELS[risk] ?? capability.risk}
          </Badge>
        ) : null}
        {capability.local === false ? <Badge tone="muted">שירות חיצוני</Badge> : null}
      </div>
    </Card>
  );
}

/**
 * One of the capability registry's master switches.
 *
 * Read-only, and staying that way: the AI master toggle and Fast Paths are
 * explicitly outside the Phase 3A contract, so there is no bridge operation
 * that could change them and no control here that pretends otherwise.
 */
function ToggleRow({ toggle }: { toggle: CapabilityToggle }) {
  const label = toggle.label;
  // `enabled` is resolved by the backend; the raw state is only a fallback.
  const on = toggle.enabled ?? (toggle.state ?? '').toLowerCase() === 'on';

  return (
    <li className="px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="min-w-0 font-medium text-slate-900 dark:text-slate-100">{label}</p>
        <ReadOnlyToggle on={on} label={label} />
      </div>
      {/* The badge sits on its own line: side by side it crowds the label on a
          narrow screen. */}
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {on ? 'מופעל' : 'כבוי'}
        </span>
        <NextPhaseBadge reason="להפעלה או כיבוי: מסך ההגדרות" />
      </div>
    </li>
  );
}

/**
 * One of Bobi's manageable features, from the management contract.
 *
 * A separate list from the capability toggles above, because these are the only
 * things the write bridge accepts. Flipping one opens the preview dialog; the
 * switch keeps showing what the bridge last reported, never what was clicked.
 *
 * A feature whose current state the bridge does not report is shown but not
 * operable: `expected_state` has to be observed, and guessing it would either
 * be rejected as stale or — worse — accepted while describing the wrong change.
 */
function FeatureRow({
  feature,
  onChange,
}: {
  feature: ManagedTarget;
  onChange?: (feature: ManagedTarget, next: boolean) => void;
}) {
  const known = feature.enabled !== null;
  const on = feature.enabled === true;

  return (
    <li className="px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="min-w-0 font-medium text-slate-900 dark:text-slate-100">{feature.label}</p>
        {onChange && known ? (
          <button
            type="button"
            role="switch"
            aria-checked={on}
            aria-label={feature.label}
            onClick={() => onChange(feature, !on)}
            className={cn(
              'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
              on ? 'bg-bobi-500' : 'bg-slate-300 dark:bg-slate-600',
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                'absolute right-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform',
                on ? '-translate-x-5' : 'translate-x-0',
              )}
            />
          </button>
        ) : (
          <ReadOnlyToggle on={on} label={feature.label} />
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {known ? (on ? 'מופעל' : 'כבוי') : 'מצב לא ידוע'}
        </span>
        {onChange && !known ? (
          <span className="text-xs text-slate-400 dark:text-slate-500">
            בובי לא מדווח על המצב הנוכחי, ולכן אי אפשר לשנות אותו מכאן.
          </span>
        ) : null}
      </div>
    </li>
  );
}

export function CapabilitiesPage() {
  const query = useCapabilities();
  const management = useManagementContract();
  const featuresResource = useResource(management.data, 'features');
  const change = useManagedChange('features', [keys.managementContract, keys.capabilities]);
  const features = featuresResource?.targets ?? [];
  const [openKey, setOpenKey] = useState<string | null>(null);

  // Memoised so the `?? []` fallback does not produce a fresh array on every
  // render and invalidate the grouping below.
  const capabilities = useMemo(() => query.data?.capabilities ?? [], [query.data]);

  /** Grouped dynamically: whatever groups the registry names are the groups. */
  const grouped = useMemo(() => {
    const groups = new Map<string, BridgeCapability[]>();
    capabilities.forEach((capability) => {
      const group = capability.group ?? UNGROUPED;
      const existing = groups.get(group);
      if (existing) existing.push(capability);
      else groups.set(group, [capability]);
    });
    return [...groups.entries()];
  }, [capabilities]);

  const openCapability = capabilities.find((capability) => capability.id === openKey) ?? null;

  return (
    <>
      <PageHeader
        title="יכולות"
        description="מה בובי יודע לעשות, לפי הרישום הקנוני שלו."
      />

      <ManagementNotice
        status={management.data}
        resource="features"
        className="mb-4"
        readOnlyText="רשימת היכולות והמתגים מוצגים לקריאה בלבד."
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את רשימת היכולות מ-Home Assistant"
        loadingLabel="טוען יכולות…"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.capabilities.length === 0 && data.toggles.length === 0}
        empty={
          <EmptyState
            title="אין כרגע יכולות רשומות"
            description="כשבובי ירשום יכולות, הן יופיעו כאן."
            icon={<Sparkles size={32} />}
          />
        }
      >
        {(data) => (
          <div className="space-y-8">
            {grouped.map(([group, groupCapabilities]) => (
              <section key={group} aria-labelledby={`group-${group}`}>
                <h2
                  id={`group-${group}`}
                  className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                >
                  {group}
                </h2>
                <ul className="grid gap-3 sm:grid-cols-2">
                  {groupCapabilities.map((capability) => (
                    <CapabilityCard
                      key={capability.id}
                      capability={capability}
                      onOpen={() => setOpenKey(capability.id)}
                    />
                  ))}
                </ul>
              </section>
            ))}

            {data.toggles.length > 0 ? (
              <section aria-labelledby="toggles-heading">
                <SectionTitle>
                  <span id="toggles-heading">מתגים ראשיים</span>
                </SectionTitle>
                <Card className="p-0">
                  <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                    {data.toggles.map((toggle) => (
                      <ToggleRow key={toggle.id} toggle={toggle} />
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null}

            {features.length > 0 ? (
              <section aria-labelledby="features-heading">
                <SectionTitle>
                  <span id="features-heading">תכונות בובי</span>
                </SectionTitle>
                <Card className="p-0">
                  <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                    {features.map((feature) => (
                      <FeatureRow
                        key={feature.id}
                        feature={feature}
                        onChange={
                          featuresResource?.available
                            ? (item, next) =>
                                void change.start({
                                  operation: 'set',
                                  resource_id: item.id,
                                  payload: { enabled: next },
                                })
                            : undefined
                        }
                      />
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null}

            <p className="flex items-center justify-center gap-2 text-xs text-slate-400 dark:text-slate-500">
              <Cpu aria-hidden="true" size={13} />
              {capabilities.length} יכולות רשומות
            </p>
          </div>
        )}
      </QueryBoundary>

      {openCapability ? (
        <CapabilityDetail capability={openCapability} onClose={() => setOpenKey(null)} />
      ) : null}

      <ChangeDialog change={change} />
    </>
  );
}
