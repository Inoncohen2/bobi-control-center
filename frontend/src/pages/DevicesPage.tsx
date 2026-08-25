import { useMemo, useState } from 'react';
import { Search, SlidersHorizontal, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Chip } from '@/components/ui/Field';
import { AdvancedDetails, AdvancedDisclosure } from '@/components/ui/Advanced';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useDevices } from '@/hooks/queries';
import {
  EMPTY_FILTERS,
  filterDevices,
  groupByRoom,
  hasActiveFilters,
  type AvailabilityFilter,
  type DeviceFilters,
} from '@/features/devices/filter';
import type { Device, DeviceCategory } from '@/types/api';
import { CATEGORY_LABELS } from '@/utils/format';
import { iconFor } from '@/utils/icons';

const AVAILABILITY_OPTIONS: Array<{ value: AvailabilityFilter; label: string }> = [
  { value: 'all', label: 'הכול' },
  { value: 'available', label: 'זמינים' },
  { value: 'unavailable', label: 'לא זמינים' },
];

function DeviceDetail({ device, onClose }: { device: Device; onClose: () => void }) {
  const Icon = iconFor(device.icon);

  return (
    <Modal open onClose={onClose} title={device.display_name}>
      <div className="flex items-center gap-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
        <Icon aria-hidden="true" size={22} className="text-bobi-600 dark:text-bobi-400" />
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
            {device.state_label}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {device.available ? 'המכשיר זמין' : 'המכשיר אינו זמין כרגע'}
          </p>
        </div>
      </div>

      <dl className="mt-4 space-y-3">
        <div>
          <dt className="text-sm text-slate-500 dark:text-slate-400">שם בבובי</dt>
          <dd className="font-medium text-slate-900 dark:text-slate-100">{device.display_name}</dd>
        </div>
        <div>
          <dt className="text-sm text-slate-500 dark:text-slate-400">חדר</dt>
          <dd className="font-medium text-slate-900 dark:text-slate-100">{device.room}</dd>
        </div>
        <div>
          <dt className="text-sm text-slate-500 dark:text-slate-400">סוג</dt>
          <dd className="font-medium text-slate-900 dark:text-slate-100">
            {CATEGORY_LABELS[device.category]}
          </dd>
        </div>
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
      </dl>

      <AdvancedDisclosure title="מידע טכני">
        <AdvancedDetails advanced={device.advanced} />
      </AdvancedDisclosure>
    </Modal>
  );
}

function DeviceCard({ device, onOpen }: { device: Device; onOpen: () => void }) {
  const Icon = iconFor(device.icon);

  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="w-full rounded-2xl border border-slate-200/80 bg-white p-4 text-right shadow-card transition-shadow hover:shadow-lift focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600 dark:border-slate-700/60 dark:bg-slate-800/60"
      >
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className={
              device.available
                ? 'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300'
                : 'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500'
            }
          >
            <Icon size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-slate-900 dark:text-slate-100">
              {device.display_name}
            </p>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              {CATEGORY_LABELS[device.category]}
            </p>
          </div>
        </div>
        <div className="mt-3">
          <Badge tone={device.available ? 'ok' : 'error'} dot>
            {device.state_label}
          </Badge>
        </div>
      </button>
    </li>
  );
}

export function DevicesPage() {
  const query = useDevices();
  const [filters, setFilters] = useState<DeviceFilters>(EMPTY_FILTERS);
  const [openId, setOpenId] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const visible = useMemo(
    () => filterDevices(query.data?.devices ?? [], filters),
    [query.data, filters],
  );
  const grouped = useMemo(
    () => groupByRoom(visible, query.data?.rooms ?? []),
    [visible, query.data],
  );

  const openDevice = (query.data?.devices ?? []).find((device) => device.id === openId) ?? null;
  const filtersActive = hasActiveFilters(filters);

  return (
    <>
      <PageHeader
        title="מכשירים"
        description="כל מה שבובי מכיר בבית, מסודר לפי חדרים."
      />

      <div className="mb-4 space-y-3">
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
                  selected={filters.room === null}
                  onClick={() => setFilters((current) => ({ ...current, room: null }))}
                >
                  כל החדרים
                </Chip>
                {(query.data?.rooms ?? []).map((room) => (
                  <Chip
                    key={room}
                    selected={filters.room === room}
                    onClick={() =>
                      setFilters((current) => ({
                        ...current,
                        room: current.room === room ? null : room,
                      }))
                    }
                  >
                    {room}
                  </Chip>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">סוג</p>
              <div className="flex flex-wrap gap-2">
                <Chip
                  selected={filters.category === null}
                  onClick={() => setFilters((current) => ({ ...current, category: null }))}
                >
                  הכול
                </Chip>
                {(query.data?.categories ?? []).map((category: DeviceCategory) => (
                  <Chip
                    key={category}
                    selected={filters.category === category}
                    onClick={() =>
                      setFilters((current) => ({
                        ...current,
                        category: current.category === category ? null : category,
                      }))
                    }
                  >
                    {CATEGORY_LABELS[category]}
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
        errorMessage="לא הצלחתי לטעון את המכשירים"
        onRetry={() => void query.refetch()}
      >
        {() =>
          visible.length === 0 ? (
            <EmptyState
              title={
                filtersActive ? 'לא נמצאו מכשירים שמתאימים לסינון' : 'בובי עדיין לא מכיר מכשירים'
              }
              description={
                filtersActive
                  ? 'אפשר לנקות את הסינון ולנסות שוב.'
                  : 'כשיתחברו מכשירים לבית, הם יופיעו כאן.'
              }
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
              {grouped.map(([room, devices]) => (
                <section key={room} aria-labelledby={`room-${room}`}>
                  <h2
                    id={`room-${room}`}
                    className="mb-3 flex items-baseline gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                  >
                    {room}
                    <span className="text-xs font-normal normal-case">({devices.length})</span>
                  </h2>
                  <ul className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                    {devices.map((device) => (
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
