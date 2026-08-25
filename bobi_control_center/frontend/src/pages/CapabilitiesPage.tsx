import { useMemo, useState } from 'react';
import { AlertTriangle, Settings2, Sparkles } from 'lucide-react';

import { Badge, healthTone } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { IconButton } from '@/components/ui/Button';
import { AdvancedDetails, AdvancedDisclosure } from '@/components/ui/Advanced';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
import { Toggle } from '@/components/ui/Toggle';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useCapabilities, useToggleCapability } from '@/hooks/queries';
import type { Capability } from '@/types/api';
import { timeAgo } from '@/utils/format';
import { iconFor } from '@/utils/icons';

function SettingRow({ label, value, help }: { label: string; value: string; help?: string | null }) {
  return (
    <div className="border-b border-slate-100 py-2.5 last:border-0 dark:border-slate-700/60">
      <div className="flex items-baseline justify-between gap-4">
        <dt className="text-sm text-slate-500 dark:text-slate-400">{label}</dt>
        <dd className="text-sm font-medium text-slate-900 dark:text-slate-100">{value}</dd>
      </div>
      {help ? <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">{help}</p> : null}
    </div>
  );
}

function formatSettingValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'כן' : 'לא';
  if (value === null || value === undefined) return '—';
  return String(value);
}

function CapabilityDetail({
  capability,
  onClose,
  onToggle,
  pending,
}: {
  capability: Capability;
  onClose: () => void;
  onToggle: (enabled: boolean) => void;
  pending: boolean;
}) {
  const Icon = iconFor(capability.icon);

  return (
    <Modal open onClose={onClose} title={capability.name} description={capability.description}>
      <div className="flex items-center justify-between rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
        <div className="flex items-center gap-3">
          <Icon aria-hidden="true" size={20} className="text-bobi-600 dark:text-bobi-400" />
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
              פעיל: {capability.enabled ? 'כן' : 'לא'}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              שימוש אחרון: {timeAgo(capability.last_used)}
            </p>
          </div>
        </div>
        <Toggle
          checked={capability.enabled}
          onChange={onToggle}
          disabled={pending}
          label={`הפעלה או כיבוי של ${capability.name}`}
        />
      </div>

      {capability.warning ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <AlertTriangle aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
          {capability.warning}
        </p>
      ) : null}

      {capability.settings.length > 0 ? (
        <div className="mt-4">
          <h3 className="mb-1 text-sm font-semibold text-slate-900 dark:text-slate-100">הגדרות</h3>
          <dl>
            {capability.settings.map((setting) => (
              <SettingRow
                key={setting.key}
                label={setting.label}
                value={formatSettingValue(setting.value)}
                help={setting.help}
              />
            ))}
          </dl>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">
          ליכולת הזו אין הגדרות שניתן לשנות.
        </p>
      )}

      <AdvancedDisclosure>
        <AdvancedDetails advanced={capability.advanced} />
      </AdvancedDisclosure>
    </Modal>
  );
}

function CapabilityCard({
  capability,
  onOpen,
  onToggle,
  pending,
}: {
  capability: Capability;
  onOpen: () => void;
  onToggle: (enabled: boolean) => void;
  pending: boolean;
}) {
  const Icon = iconFor(capability.icon);

  return (
    <Card interactive as="li" className="flex flex-col">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300"
        >
          <Icon size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">{capability.name}</h3>
          <p className="mt-0.5 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            {capability.description}
          </p>
        </div>
        <Toggle
          checked={capability.enabled}
          onChange={onToggle}
          disabled={pending}
          size="sm"
          label={`הפעלה או כיבוי של ${capability.name}`}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge tone={capability.enabled ? healthTone[capability.state] : 'muted'} dot>
          {capability.enabled ? capability.state_label : 'כבוי'}
        </Badge>
        {capability.warning ? (
          <Badge tone="warning">
            <AlertTriangle aria-hidden="true" size={12} />
            אזהרה
          </Badge>
        ) : null}
      </div>

      {capability.warning ? (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{capability.warning}</p>
      ) : null}

      <div className="mt-auto flex items-center justify-between pt-3">
        <span className="text-xs text-slate-400 dark:text-slate-500">
          {timeAgo(capability.last_used)}
        </span>
        <IconButton
          label={`הגדרות של ${capability.name}`}
          icon={<Settings2 size={16} />}
          onClick={onOpen}
        />
      </div>
    </Card>
  );
}

export function CapabilitiesPage() {
  const query = useCapabilities();
  const toggle = useToggleCapability();
  const [openId, setOpenId] = useState<string | null>(null);

  const grouped = useMemo(() => {
    const groups = new Map<string, Capability[]>();
    for (const capability of query.data ?? []) {
      const existing = groups.get(capability.group);
      if (existing) existing.push(capability);
      else groups.set(capability.group, [capability]);
    }
    return [...groups.entries()];
  }, [query.data]);

  const openCapability = (query.data ?? []).find((item) => item.id === openId) ?? null;

  return (
    <>
      <PageHeader
        title="יכולות"
        description="מה בובי יודע לעשות. אפשר לכבות יכולת שלא צריך."
      />

      {toggle.isError ? (
        <div className="mb-4">
          <ErrorState error={toggle.error} fallbackMessage="לא הצלחתי לשנות את היכולת" />
        </div>
      ) : null}

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את היכולות"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.length === 0}
        empty={
          <EmptyState
            title="עדיין אין יכולות מוגדרות"
            description="כשבובי יחובר, היכולות שלו יופיעו כאן."
            icon={<Sparkles size={32} />}
          />
        }
      >
        {() => (
          <div className="space-y-7">
            {grouped.map(([group, capabilities]) => (
              <section key={group} aria-labelledby={`group-${group}`}>
                <h2
                  id={`group-${group}`}
                  className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                >
                  {group}
                </h2>
                <ul className="grid gap-3 sm:grid-cols-2">
                  {capabilities.map((capability) => (
                    <CapabilityCard
                      key={capability.id}
                      capability={capability}
                      pending={toggle.isPending && toggle.variables?.id === capability.id}
                      onOpen={() => setOpenId(capability.id)}
                      onToggle={(enabled) => toggle.mutate({ id: capability.id, enabled })}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </QueryBoundary>

      {openCapability ? (
        <CapabilityDetail
          capability={openCapability}
          onClose={() => setOpenId(null)}
          pending={toggle.isPending}
          onToggle={(enabled) => toggle.mutate({ id: openCapability.id, enabled })}
        />
      ) : null}
    </>
  );
}
