/**
 * One managed family, rendered from what the bridge described.
 *
 * Settings, users, Shabbat, rules, the calendar, devices and the system all
 * come back in the same envelope, so they all render through here. The screen
 * knows nothing about morning summaries or air conditioners: it reads `kind`
 * to pick a control, `constraints` to bound it, `options` to fill it, and
 * `controllable` to decide whether there is a control at all.
 *
 * Three rules hold whatever the bridge sends:
 *
 * 1. **No control without permission.** `controllable: false`, an empty
 *    `operations`, or a `value` the bridge did not report all render as a
 *    read-only row. Fail closed is the default, not the exception.
 * 2. **Nothing is applied on change.** Moving a slider stages a value; the
 *    change happens through preview → confirm → commit like every other write,
 *    and the row shows the bridge's value until a commit has been read back.
 * 3. **A limit that was published is enforced here too.** The backend and Home
 *    Assistant both check again — this one just spares a round trip and says so
 *    in the field rather than in a dialog.
 */

import { useState } from 'react';
import { Lock } from 'lucide-react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader } from '@/components/ui/Card';
import { SelectField, TextField } from '@/components/ui/Field';
import { allows, useRole } from '@/features/auth/useRole';
import { cn } from '@/utils/cn';
import type { ManagedGroup, ManagedItem, ResourceSnapshot } from '@/types/api';
import type { Role } from '@/features/auth/useRole';

/** Hebrew for the risk words, for the badge beside a sensitive row. */
const RISK_LABELS: Record<string, string> = {
  medium: 'שינוי מורגש',
  high: 'רגיש',
  destructive: 'בלתי הפיך',
};

const RISK_TONES: Record<string, BadgeTone> = {
  medium: 'neutral',
  high: 'warning',
  destructive: 'error',
};

export interface ResourceEditorProps {
  snapshot: ResourceSnapshot;
  /** Ask for a preview. The parent owns the change flow and the dialog. */
  onChange: (item: ManagedItem, value: unknown, operation?: string) => void;
  /** Writes are possible at all — Home Assistant's master switch is on. */
  writesEnabled: boolean;
  /** Show only the items a page cares about, e.g. one notification class. */
  filter?: (item: ManagedItem) => boolean;
  /** Rendered under each row — a family's own extra detail. */
  renderDetail?: (item: ManagedItem) => React.ReactNode;
  /**
   * Never draw a control, whatever the bridge says about the items.
   *
   * For the camera screen. Switching a camera on from a web page is the one
   * action on this system that reversing does not undo — by the time you could
   * switch it off again, somebody has been recorded — so that screen refuses by
   * construction rather than by trusting a flag to stay false.
   */
  readOnly?: boolean;
  emptyLabel?: string;
}

export function ResourceEditor({
  snapshot,
  onChange,
  writesEnabled,
  filter,
  renderDetail,
  readOnly = false,
  emptyLabel = 'אין כאן פריטים לניהול.',
}: ResourceEditorProps) {
  const groups = snapshot.groups
    .map((group) => ({ ...group, items: filter ? group.items.filter(filter) : group.items }))
    .filter((group) => group.items.length > 0);

  if (groups.length === 0) {
    return (
      <Card>
        <p className="text-sm text-slate-500 dark:text-slate-400">{emptyLabel}</p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <ResourceGroup
          key={group.id}
          group={group}
          onChange={onChange}
          writesEnabled={writesEnabled && !readOnly}
          renderDetail={renderDetail}
        />
      ))}
    </div>
  );
}

function ResourceGroup({
  group,
  onChange,
  writesEnabled,
  renderDetail,
}: {
  group: ManagedGroup;
  onChange: ResourceEditorProps['onChange'];
  writesEnabled: boolean;
  renderDetail?: ResourceEditorProps['renderDetail'];
}) {
  return (
    <Card>
      {group.id === '_' ? null : <CardHeader title={group.label} description={group.description} />}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {group.items.map((item) => (
          <li key={item.id} className="py-3 first:pt-0 last:pb-0">
            <ItemRow
              item={item}
              onChange={onChange}
              writesEnabled={writesEnabled}
              renderDetail={renderDetail}
            />
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * Whether this row gets an editor at all. Every condition must hold.
 *
 * The role check is the last of them and the only one that is advisory: the
 * backend refuses an operation above the session's role whatever this returns.
 * Checking here as well means a viewer is not shown a button that would come
 * back 403 — a kinder screen, not a second lock.
 */
function isOperable(item: ManagedItem, writesEnabled: boolean, role: Role | undefined): boolean {
  return (
    writesEnabled &&
    item.controllable &&
    item.operations.length > 0 &&
    // A missing value means the bridge could not read the item, and writing
    // something it cannot read is writing against a preview bound to nothing.
    // An `action` is the exception, and the only one: a self-check has no
    // value to miss. Requiring one here left the system bridge's two safe
    // checks marked controllable and drawn as readings.
    (item.kind === 'action' || (item.value !== null && item.value !== undefined)) &&
    allows(role, item.risk)
  );
}

export function ItemRow({
  item,
  onChange,
  writesEnabled,
  renderDetail,
}: {
  item: ManagedItem;
  onChange: ResourceEditorProps['onChange'];
  writesEnabled: boolean;
  renderDetail?: ResourceEditorProps['renderDetail'];
}) {
  const { role } = useRole();
  const operable = isOperable(item, writesEnabled, role);
  const riskLabel = RISK_LABELS[item.risk];
  // Told apart on purpose: "the bridge will not let anyone do this" and "you
  // may not do this" are different sentences, and only one of them is about
  // the person reading it.
  const blockedByRole = writesEnabled && item.controllable && !allows(role, item.risk);

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
            {item.label}
          </span>
          {riskLabel ? (
            <Badge tone={RISK_TONES[item.risk] ?? 'warning'}>{riskLabel}</Badge>
          ) : null}
          {!operable && item.controllable ? (
            <Lock aria-hidden className="h-3.5 w-3.5 text-slate-400" />
          ) : null}
        </div>
        {item.description ? (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{item.description}</p>
        ) : null}
        {!operable && item.unavailable_reason ? (
          <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
            {item.unavailable_reason}
          </p>
        ) : null}
        {blockedByRole ? (
          <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
            להרשאה שלך אין גישה לשינוי הזה.
          </p>
        ) : null}
        {renderDetail?.(item)}
      </div>

      <div className="w-full shrink-0 sm:w-56">
        {operable ? (
          <ItemControl item={item} onChange={onChange} />
        ) : (
          <p className="text-sm text-slate-600 sm:text-end dark:text-slate-300">
            {item.display ?? '—'}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * The control for one item, chosen by its kind.
 *
 * A toggle asks immediately — there is one thing it can mean. Everything else
 * stages a value and waits for "בדוק שינוי", because a half-typed number is not
 * a request to change anything.
 */
function ItemControl({
  item,
  onChange,
}: {
  item: ManagedItem;
  onChange: ResourceEditorProps['onChange'];
}) {
  const [draft, setDraft] = useState<string>(
    item.value === null || item.value === undefined ? '' : String(item.value),
  );
  const current = item.value === null || item.value === undefined ? '' : String(item.value);
  const dirty = draft !== current;

  if (item.kind === 'action') {
    // One button, and the label is the bridge's own word for it.
    return (
      <div className="flex sm:justify-end">
        <Button variant="secondary" onClick={() => onChange(item, true, item.primary_operation ?? undefined)}>
          {item.display ?? 'הרץ'}
        </Button>
      </div>
    );
  }

  if (item.kind === 'toggle') {
    const on = item.value === true;
    // `enable`/`disable` when the bridge named them, `set` or `power`
    // otherwise. Which one that is comes from the backend, on the item, so the
    // rule lives in one place and is tested there — this used to be worked out
    // here, and a screen that reasons about a vocabulary is a screen that has
    // to be corrected every time the vocabulary grows.
    const operation = item.primary_operation ?? undefined;
    return (
      <div className="flex sm:justify-end">
        <Button
          variant={on ? 'secondary' : 'primary'}
          onClick={() => onChange(item, !on, operation)}
        >
          {on ? 'כבה' : 'הפעל'}
        </Button>
      </div>
    );
  }

  if (item.kind === 'choice') {
    return (
      <SelectField
        label={item.label}
        srOnlyLabel
        value={draft}
        options={item.options.map((option) => ({ value: option.value, label: option.label }))}
        onChange={(event) => {
          setDraft(event.target.value);
          onChange(item, event.target.value);
        }}
      />
    );
  }

  const limits = item.constraints;
  const inputType =
    item.kind === 'number'
      ? 'number'
      : item.kind === 'time'
        ? 'time'
        : item.kind === 'date'
          ? 'date'
          : item.kind === 'datetime'
            ? 'datetime-local'
            : 'text';

  return (
    <div className="space-y-2">
      <TextField
        label={item.label}
        srOnlyLabel
        type={inputType}
        value={draft}
        min={limits?.minimum ?? undefined}
        max={limits?.maximum ?? undefined}
        step={limits?.step ?? undefined}
        maxLength={limits?.max_length ?? undefined}
        onChange={(event) => setDraft(event.target.value)}
        help={describeLimits(limits)}
      />
      <Button
        className={cn('w-full', !dirty && 'invisible')}
        onClick={() => onChange(item, item.kind === 'number' ? Number(draft) : draft)}
        disabled={!dirty}
      >
        בדוק שינוי
      </Button>
    </div>
  );
}

/** The published limits, said once under the field rather than in a dialog. */
function describeLimits(limits: ManagedItem['constraints']): string | undefined {
  if (!limits) return undefined;
  const parts: string[] = [];
  if (limits.minimum !== null && limits.maximum !== null) {
    parts.push(`${limits.minimum}–${limits.maximum}${limits.unit ?? ''}`);
  }
  if (limits.step) parts.push(`בקפיצות של ${limits.step}`);
  if (limits.max_length) parts.push(`עד ${limits.max_length} תווים`);
  return parts.length > 0 ? parts.join(' · ') : undefined;
}
