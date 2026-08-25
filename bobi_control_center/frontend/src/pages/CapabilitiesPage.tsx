import { useMemo, useState } from 'react';
import { Cpu, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
import { NextPhaseBadge, ReadOnlyNotice, ReadOnlyToggle } from '@/components/ui/ReadOnly';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useCapabilities } from '@/hooks/queries';
import type { BridgeCapability, CapabilityToggle } from '@/types/api';
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
        <NextPhaseBadge />
      </div>
    </li>
  );
}

export function CapabilitiesPage() {
  const query = useCapabilities();
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

      <ReadOnlyNotice className="mb-4">
        רשימת היכולות והמתגים מוצגים לקריאה בלבד. שינוי מצב יהיה זמין בשלב הבא.
      </ReadOnlyNotice>

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
    </>
  );
}
