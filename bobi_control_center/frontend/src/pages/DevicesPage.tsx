import { useMemo, useState } from 'react';
import { Boxes, Search, SlidersHorizontal, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Chip } from '@/components/ui/Field';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
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
import { ManagedSection } from '@/features/manage/ManagedSection';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import { CAMERA_CLASS, DeviceDetail as ManagedDeviceDetail } from '@/pages/DeviceControlPage';
import { ChangeDialog } from '@/features/manage/ChangeDialog';
import { operableWith, useManagedFamily } from '@/features/manage/useManagedFamily';
import { Switch } from '@/components/ui/Switch';
import { cn } from '@/utils/cn';
import type { ManagedItem } from '@/types/api';

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

/**
 * One device in the catalogue — and its switch, when it has one.
 *
 * The card used to be a single button that opened a detail sheet, so turning a
 * light on meant: open the page, scroll past the whole catalogue to a second
 * list, find the same light again by name, and press there. Now the switch is
 * on the light.
 *
 * The card body is still the detail sheet, and the switch is a separate control
 * beside it rather than nested inside it — a button inside a button is invalid
 * markup and, more to the point, makes "which one did I just press" a question.
 *
 * `managed` is the item from the management snapshot, matched to this catalogue
 * row by its canonical id. Absent, not controllable, or no value reported means
 * no switch: the reading stays, and it is the honest thing to show.
 */
function DeviceCard({
  device,
  managed,
  writesEnabled,
  pending,
  onOpen,
  onToggle,
}: {
  device: BridgeDevice;
  managed: ManagedItem | undefined;
  writesEnabled: boolean;
  pending: boolean;
  onOpen: () => void;
  onToggle: (item: ManagedItem, next: boolean) => void;
}) {
  const operation = operableWith(managed, writesEnabled);
  // A switch belongs on something with two states. A thermostat's target
  // temperature is managed in the detail sheet, not by a knob on a card.
  const togglable = operation !== null && managed?.kind === 'toggle';
  const on = managed?.value === true;

  return (
    <li>
      <div
        className={cn(
          'flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white',
          'px-4 py-3 shadow-card transition-shadow hover:shadow-lift',
          'dark:border-slate-700/60 dark:bg-slate-800/60',
        )}
      >
        <button
          type="button"
          onClick={onOpen}
          className="min-w-0 flex-1 text-right focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600"
        >
          {/* The user-facing name only — never the entity id. */}
          <p className="truncate font-medium leading-tight text-slate-900 dark:text-slate-100">
            {device.name}
          </p>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
            {/* A switch already says on or off. Repeating it in a pill beside
                the switch is the same fact twice and a whole row of height for
                it. The state is spelled out only where there is no switch to
                read it from — a camera, a vacuum's dock, anything unavailable. */}
            {togglable ? null : (
              <span
                aria-hidden="true"
                className={cn(
                  'h-1.5 w-1.5 shrink-0 rounded-full',
                  device.available ? 'bg-emerald-500' : 'bg-rose-500',
                )}
              />
            )}
            <span className="truncate">
              {togglable
                ? (SCOPE_LABELS[device.group ?? ''] ?? device.group ?? '')
                : stateLabel(device.state)}
            </span>
          </p>
        </button>

        {togglable && managed ? (
          <Switch
            on={on}
            pending={pending}
            label={device.name}
            onChange={(next) => onToggle(managed, next)}
          />
        ) : null}
      </div>
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

  const managed = useManagedFamily('devices');

  /**
   * Catalogue row → its management item.
   *
   * The two halves are keyed differently — the catalogue by entity id, the
   * management snapshot by canonical id — and the canonical id deliberately
   * never reaches this client, so there is no id to join on. What both do carry
   * is the bridge's own `canonical` name: `BridgeDevice.name` and
   * `ManagedItem.label` are the same field from the same entry, not two
   * renderings that happen to agree.
   *
   * A name is still weaker than an id, so a name shared by two switchable
   * devices matches neither. A missing switch is a bad afternoon; the wrong
   * light going off in a child's room is worse.
   */
  const managedByName = useMemo(() => {
    const seen = new Map<string, ManagedItem | null>();
    for (const item of managed.itemsById.values()) {
      if (item.kind !== 'toggle') continue;
      seen.set(item.label, seen.has(item.label) ? null : item);
    }
    return seen;
  }, [managed.itemsById]);

  const busy = managed.change.stage !== 'idle';

  return (
    <>
      <PageHeader title="מכשירים" description="הקטלוג של בובי, מסודר לפי חדרים." />

      <div className="mb-4 space-y-3">
        {/*
          Scope is a bridge parameter, so changing it refetches.

          One scrolling row rather than a wrapped block: eleven scopes wrapped
          onto three lines on a phone and pushed the devices themselves below
          the fold. The negative margin lets the row bleed to the screen edge,
          which is the cue that it scrolls.
        */}
        <div className="-mx-4 overflow-x-auto px-4 pb-1 lg:mx-0 lg:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <div className="flex w-max gap-2">
            {DEVICE_SCOPES.map((value) => (
              <Chip key={value} selected={scope === value} onClick={() => setScope(value)}>
                {SCOPE_LABELS[value] ?? value}
              </Chip>
            ))}
          </div>
        </div>

        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search
              aria-hidden="true"
              size={18}
              className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              type="search"
              value={filters.search}
              onChange={(event) =>
                setFilters((current) => ({ ...current, search: event.target.value }))
              }
              placeholder="חיפוש לפי שם, חדר או כינוי…"
              aria-label="חיפוש מכשירים"
              className="w-full rounded-xl border border-slate-300 bg-white py-2.5 pe-3 ps-10 text-sm text-slate-900 placeholder:text-slate-400 focus:border-bobi-500 focus:outline-none focus:ring-2 focus:ring-bobi-500/30 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
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
            <div className="space-y-5">
              {grouped.map(([area, areaDevices]) => (
                <section key={area} aria-labelledby={`area-${area}`}>
                  <h2
                    id={`area-${area}`}
                    className="mb-2 flex items-baseline gap-2 px-1 text-xs font-semibold tracking-wide text-slate-400 dark:text-slate-500"
                  >
                    {area}
                    <span className="font-normal">({areaDevices.length})</span>
                  </h2>
                  <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {areaDevices.map((device) => (
                      <DeviceCard
                        key={device.id}
                        device={device}
                        managed={managedByName.get(device.name) ?? undefined}
                        writesEnabled={managed.writesEnabled}
                        pending={busy}
                        onOpen={() => setOpenId(device.id)}
                        onToggle={(item, next) => managed.request(item, next)}
                      />
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )
        }
      </QueryBoundary>

      <ManagedSection resource="devices" title="הגדרות מכשירים">
        {({ snapshot, request, writesEnabled }) => (
          <ResourceEditor
            snapshot={snapshot}
            onChange={request}
            writesEnabled={writesEnabled}
            // On/off lives on the card now. What is left here is everything a
            // switch cannot express — a target temperature, a fan mode, a
            // brightness — so the section stopped being the same list twice.
            //
            // "A toggle is fully covered by its card" is not the same as "a
            // toggle": a vacuum publishes a switch *and* pause, return-to-base
            // and locate, and dropping every toggle dropped all four. The
            // backend already says which verbs a switch does not stand for, so
            // a row is a duplicate only when that list is empty.
            filter={(item) =>
              String(item.detail.device_class ?? '') !== CAMERA_CLASS &&
              (item.kind !== 'toggle' || item.run_operations.length > 0)
            }
            renderDetail={(item) => <ManagedDeviceDetail item={item} />}
            emptyLabel="אין כאן הגדרות נוספות."
          />
        )}
      </ManagedSection>

      <ChangeDialog change={managed.change} />

      {openDevice ? <DeviceDetail device={openDevice} onClose={() => setOpenId(null)} /> : null}
    </>
  );
}
