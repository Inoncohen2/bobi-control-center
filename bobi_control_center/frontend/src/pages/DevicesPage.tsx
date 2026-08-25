import { useMemo, useState } from 'react';
import { Boxes, Search, SlidersHorizontal, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Chip } from '@/components/ui/Field';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
import { ReadOnlyNotice } from '@/components/ui/ReadOnly';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useDevices } from '@/hooks/queries';
import {
  EMPTY_FILTERS,
  filterDevices,
  groupByArea,
  hasActiveFilters,
  type AvailabilityFilter,
  type DeviceFilters,
} from '@/features/devices/filter';
import { DEVICE_SCOPES, type BridgeDevice, type DeviceScope } from '@/types/api';
import { SCOPE_LABELS, limitEntries, stateLabel, timeAgo } from '@/utils/format';

const AVAILABILITY_OPTIONS: Array<{ value: AvailabilityFilter; label: string }> = [
  { value: 'all', label: 'הכול' },
  { value: 'available', label: 'זמינים' },
  { value: 'unavailable', label: 'לא זמינים' },
];

/** Technical fields, shown only inside the Advanced disclosure. */
const TECHNICAL_FIELDS: Array<[string, string]> = [
  ['entity_id', 'מזהה טכני'],
  ['handler', 'Handler'],
  ['domain', 'Domain'],
  ['group', 'קבוצה'],
  ['semantic_scopes', 'קטגוריות'],
  ['controllable', 'ניתן לשליטה'],
  ['logical_controllable', 'שליטה לוגית'],
  ['last_changed', 'שינוי אחרון'],
];

function DeviceDetail({ device, onClose }: { device: BridgeDevice; onClose: () => void }) {
  const limits = limitEntries(device.limits as unknown as Record<string, unknown> | null);

  return (
    <Modal open onClose={onClose} title={device.name}>
      <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
        <Badge tone={device.available ? 'ok' : 'error'} dot>
          {stateLabel(device.state)}
        </Badge>
        {device.last_changed ? (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            השתנה {timeAgo(device.last_changed)}
          </p>
        ) : null}
      </div>

      <dl className="mt-4 space-y-3">
        <div>
          <dt className="text-sm text-slate-500 dark:text-slate-400">שם בבובי</dt>
          <dd className="font-medium text-slate-900 dark:text-slate-100">{device.name}</dd>
        </div>
        {device.area ? (
          <div>
            <dt className="text-sm text-slate-500 dark:text-slate-400">חדר</dt>
            <dd className="font-medium text-slate-900 dark:text-slate-100">{device.area}</dd>
          </div>
        ) : null}

        {device.aliases.length > 0 ? (
          <div>
            <dt className="mb-1 text-sm text-slate-500 dark:text-slate-400">
              כינויים שבובי מבין
            </dt>
            <dd className="flex flex-wrap gap-1.5">
              {device.aliases.map((alias) => (
                <Badge key={alias} tone="info">
                  {alias}
                </Badge>
              ))}
            </dd>
          </div>
        ) : null}

        {device.capabilities.length > 0 ? (
          <div>
            <dt className="mb-1 text-sm text-slate-500 dark:text-slate-400">יכולות</dt>
            <dd className="flex flex-wrap gap-1.5">
              {device.capabilities.map((capability) => (
                <Badge key={capability} tone="neutral">
                  {capability}
                </Badge>
              ))}
            </dd>
          </div>
        ) : null}

        {/*
          The bridge's own limits, kept whole by the backend rather than
          collapsed into a single range — a climate device has its mode lists,
          a light its colour temperature, the diffuser its slots and timer.
        */}
        {limits.length > 0 ? (
          <div>
            <dt className="mb-1 text-sm text-slate-500 dark:text-slate-400">טווחים ואפשרויות</dt>
            <dd>
              <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-700/60">
                {limits.map(([label, value]) => (
                  <li key={label} className="flex items-baseline justify-between gap-4 py-1.5">
                    <span className="text-slate-500 dark:text-slate-400">{label}</span>
                    <span className="text-left font-medium text-slate-900 dark:text-slate-100">
                      {value}
                    </span>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        ) : null}
      </dl>

      <AdvancedDisclosure title="פרטים טכניים">
        <TechnicalDetails
          source={device as unknown as Record<string, unknown>}
          known={TECHNICAL_FIELDS}
          extra={device.extra}
        />
      </AdvancedDisclosure>
    </Modal>
  );
}

function DeviceCard({ device, onOpen }: { device: BridgeDevice; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="w-full rounded-2xl border border-slate-200/80 bg-white p-4 text-right shadow-card transition-shadow hover:shadow-lift focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600 dark:border-slate-700/60 dark:bg-slate-800/60"
      >
        {/* The user-facing name only — never the entity id. */}
        <p className="line-clamp-2 font-medium leading-snug text-slate-900 dark:text-slate-100">
          {device.name}
        </p>
        {device.group ? (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{device.group}</p>
        ) : null}
        <div className="mt-3">
          <Badge tone={device.available ? 'ok' : 'error'} dot>
            {stateLabel(device.state)}
          </Badge>
        </div>
      </button>
    </li>
  );
}

export function DevicesPage() {
  const [scope, setScope] = useState<DeviceScope>('all');
  const [includeUnavailable, setIncludeUnavailable] = useState(true);
  const [filters, setFilters] = useState<DeviceFilters>(EMPTY_FILTERS);
  const [openId, setOpenId] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const query = useDevices(scope, includeUnavailable);
  const devices = useMemo(() => query.data?.devices ?? [], [query.data]);

  const visible = useMemo(() => filterDevices(devices, filters), [devices, filters]);
  const grouped = useMemo(() => groupByArea(visible), [visible]);
  // Supplied by the backend rather than recomputed here.
  const areas = query.data?.areas ?? [];

  const openDevice = devices.find((device) => device.id === openId) ?? null;
  const filtersActive = hasActiveFilters(filters);

  return (
    <>
      <PageHeader title="מכשירים" description="הקטלוג של בובי, מסודר לפי חדרים." />

      <ReadOnlyNotice className="mb-4">
        שליטה במכשירים מהממשק תהיה זמינה בשלב הבא. כרגע זו תצוגה בלבד.
      </ReadOnlyNotice>

      <div className="mb-4 space-y-3">
        {/* Scope is a bridge parameter, so changing it refetches. */}
        <div className="flex flex-wrap gap-2">
          {DEVICE_SCOPES.map((value) => (
            <Chip key={value} selected={scope === value} onClick={() => setScope(value)}>
              {SCOPE_LABELS[value] ?? value}
            </Chip>
          ))}
        </div>

        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search
              aria-hidden="true"
              size={18}
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              type="search"
              value={filters.search}
              onChange={(event) =>
                setFilters((current) => ({ ...current, search: event.target.value }))
              }
              placeholder="חיפוש לפי שם, חדר או כינוי…"
              aria-label="חיפוש מכשירים"
              className="w-full rounded-xl border border-slate-300 bg-white py-2.5 pr-10 ps-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-bobi-500 focus:outline-none focus:ring-2 focus:ring-bobi-500/30 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>
          <Button
            variant={filtersActive ? 'primary' : 'secondary'}
            icon={<SlidersHorizontal size={16} />}
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
          >
            סינון
          </Button>
        </div>

        {filtersOpen ? (
          <Card className="space-y-4 p-4">
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">חדר</p>
              <div className="flex flex-wrap gap-2">
                <Chip
                  selected={filters.area === null}
                  onClick={() => setFilters((current) => ({ ...current, area: null }))}
                >
                  כל החדרים
                </Chip>
                {areas.map((area) => (
                  <Chip
                    key={area}
                    selected={filters.area === area}
                    onClick={() =>
                      setFilters((current) => ({
                        ...current,
                        area: current.area === area ? null : area,
                      }))
                    }
                  >
                    {area}
                  </Chip>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">זמינות</p>
              <div className="flex flex-wrap gap-2">
                {AVAILABILITY_OPTIONS.map((option) => (
                  <Chip
                    key={option.value}
                    selected={filters.availability === option.value}
                    onClick={() =>
                      setFilters((current) => ({ ...current, availability: option.value }))
                    }
                  >
                    {option.label}
                  </Chip>
                ))}
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={includeUnavailable}
                onChange={(event) => setIncludeUnavailable(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-bobi-600 focus:ring-bobi-500"
              />
              לכלול מכשירים שאינם זמינים (נשלף מבובי)
            </label>

            {filtersActive ? (
              <Button
                variant="ghost"
                size="sm"
                icon={<X size={14} />}
                onClick={() => setFilters(EMPTY_FILTERS)}
              >
                ניקוי סינון
              </Button>
            ) : null}
          </Card>
        ) : null}
      </div>

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את רשימת המכשירים מ-Home Assistant"
        loadingLabel="טוען מכשירים…"
        onRetry={() => void query.refetch()}
      >
        {() =>
          visible.length === 0 ? (
            <EmptyState
              title={
                filtersActive || scope !== 'all'
                  ? 'לא נמצאו מכשירים שמתאימים לסינון'
                  : 'בובי עדיין לא מכיר מכשירים'
              }
              description={
                filtersActive || scope !== 'all'
                  ? 'אפשר לנקות את הסינון ולנסות שוב.'
                  : undefined
              }
              icon={<Boxes size={32} />}
              action={
                filtersActive ? (
                  <Button variant="secondary" onClick={() => setFilters(EMPTY_FILTERS)}>
                    ניקוי סינון
                  </Button>
                ) : null
              }
            />
          ) : (
            <div className="space-y-7">
              {grouped.map(([area, areaDevices]) => (
                <section key={area} aria-labelledby={`area-${area}`}>
                  <h2
                    id={`area-${area}`}
                    className="mb-3 flex items-baseline gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                  >
                    {area}
                    <span className="text-xs font-normal normal-case">
                      ({areaDevices.length})
                    </span>
                  </h2>
                  <ul className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                    {areaDevices.map((device) => (
                      <DeviceCard
                        key={device.id}
                        device={device}
                        onOpen={() => setOpenId(device.id)}
                      />
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )
        }
      </QueryBoundary>

      {openDevice ? <DeviceDetail device={openDevice} onClose={() => setOpenId(null)} /> : null}
    </>
  );
}
