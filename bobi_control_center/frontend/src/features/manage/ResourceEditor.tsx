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

import { useMemo, useState } from 'react';
import { Lock } from 'lucide-react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader } from '@/components/ui/Card';
import { Chip, SelectField, TextField, TimeField } from '@/components/ui/Field';
import { Switch } from '@/components/ui/Switch';
import { allows, useRole } from '@/features/auth/useRole';
import { useManagementContract } from '@/hooks/queries';
import { cn } from '@/utils/cn';
import type {
  ManagedGroup,
  ManagedItem,
  ManagedOperation,
  ResourceSnapshot,
} from '@/types/api';
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
   * The detail above already says what the value is, so do not print it twice.
   *
   * For the calendar, where an event's value is its start time and the detail
   * renders that as "יום ד׳, 2 בספט׳" beside its hours. Printing the reading as
   * well put `2026-09-02T18:00:00` under a line that had just said the same
   * thing in Hebrew.
   */
  valueShownInDetail?: boolean;
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
  valueShownInDetail = false,
  readOnly = false,
  emptyLabel = 'אין כאן פריטים לניהול.',
}: ResourceEditorProps) {
  // Read here rather than passed in by each screen.
  //
  // What this needs from the contract is the one thing an item cannot say
  // about itself: which of the verbs named on it are a complete request on
  // their own, and what to call them in Hebrew. Eighteen screens render this
  // component, and a prop that eighteen call sites have to remember is a prop
  // seventeen of them will eventually be right about. The query is the same one
  // the page above already made, so this costs a cache read.
  const contract = useManagementContract();
  const operations =
    (contract.data?.resources ?? []).find((entry) => entry.id === snapshot.resource)
      ?.operations ?? [];

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
          operations={operations}
          renderDetail={renderDetail}
          valueShownInDetail={valueShownInDetail}
        />
      ))}
    </div>
  );
}

function ResourceGroup({
  group,
  onChange,
  writesEnabled,
  operations,
  renderDetail,
  valueShownInDetail,
}: {
  group: ManagedGroup;
  onChange: ResourceEditorProps['onChange'];
  writesEnabled: boolean;
  operations?: ManagedOperation[];
  renderDetail?: ResourceEditorProps['renderDetail'];
  valueShownInDetail?: boolean;
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
              operations={operations}
              renderDetail={renderDetail}
              valueShownInDetail={valueShownInDetail}
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
export function isOperable(
  item: ManagedItem,
  writesEnabled: boolean,
  role: Role | undefined,
): boolean {
  return (
    writesEnabled &&
    item.controllable &&
    item.operations.length > 0 &&
    // `readonly` is the backend saying it could not work out how this item is
    // edited, and it is deliberate: an unrecognised kind becomes a reading
    // rather than being passed through. Falling through to a text field undid
    // that — a calendar event came back `readonly` with `edit` advertised on
    // it, and the screen drew a box you could type anything into and a button
    // that sent it as the event. Refusing here is what the kind already meant.
    item.kind !== 'readonly' &&
    // A missing value means the bridge could not read the item, and writing
    // something it cannot read is writing against a preview bound to nothing.
    // An `action` is the exception, and the only one: a self-check has no
    // value to miss. Requiring one here left the system bridge's two safe
    // checks marked controllable and drawn as readings.
    (item.kind === 'action' || (item.value !== null && item.value !== undefined)) &&
    allows(role, item.risk)
  );
}

/**
 * The verbs this row can offer as a single button.
 *
 * `item.run_operations` is the backend's answer to "which verbs did the control
 * for this kind not already send" — a scene's `activate`, an automation's
 * `trigger`, a vacuum's pause and locate. It is decided there because deciding
 * it needs to know that a switch stands for six verbs at once, which is the
 * bridge vocabulary this screen has never known and must not learn.
 *
 * What is decided here is narrower, and it is a judgement rather than a fact:
 * which of them this application is willing to put one tap away, and what to
 * call them. `delete` takes no payload and still does not get a button; the
 * words come from the contract.
 */
function runnable(
  item: ManagedItem,
  operations: ManagedOperation[],
  writesEnabled: boolean,
  role: Role | undefined,
): ManagedOperation[] {
  if (!writesEnabled || !item.controllable || !allows(role, item.risk)) return [];
  return operations.filter(
    (operation) => !operation.destructive && item.run_operations.includes(operation.id),
  );
}

export function ItemRow({
  item,
  onChange,
  writesEnabled,
  operations = [],
  renderDetail,
  valueShownInDetail = false,
}: {
  item: ManagedItem;
  onChange: ResourceEditorProps['onChange'];
  writesEnabled: boolean;
  operations?: ManagedOperation[];
  renderDetail?: ResourceEditorProps['renderDetail'];
  valueShownInDetail?: boolean;
}) {
  const { role } = useRole();
  const operable = isOperable(item, writesEnabled, role);
  const riskLabel = RISK_LABELS[item.risk];
  // A reading is not a locked control, and neither the padlock nor the
  // permission sentence belongs on one: nobody's role would unlock it and no
  // bridge is withholding it — this application simply has no editor for the
  // kind. Saying otherwise sends someone looking for permission they already
  // have.
  const editable = item.kind !== 'readonly';
  // Told apart on purpose: "the bridge will not let anyone do this" and "you
  // may not do this" are different sentences, and only one of them is about
  // the person reading it.
  const blockedByRole = writesEnabled && editable && item.controllable && !allows(role, item.risk);
  // A scene, a script, a timer, "run this automation now".
  const runs = runnable(item, operations, writesEnabled, role);

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
          {!operable && runs.length === 0 && editable && item.controllable ? (
            <Lock aria-hidden className="h-3.5 w-3.5 text-slate-400" />
          ) : null}
        </div>
        {item.description ? (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{item.description}</p>
        ) : null}
        {!operable && editable && item.unavailable_reason ? (
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

      {/*
        A switch is 52 pixels wide and was being given a full-width row of its
        own on a phone, so every notification took two lines: its name, then a
        switch alone under it. Only the controls that need the room get it.

        Run buttons are the opposite case and must not be `shrink-0`: three of
        them — start, pause and cancel a timer — asked for more width than the
        phone had, could not shrink, and pushed the whole page 33 pixels wide.
        Given the full row they wrap inside the card instead.
      */}
      <div
        className={cn(
          runs.length > 0
            ? 'w-full min-w-0 sm:w-auto'
            : item.kind === 'toggle' || item.kind === 'action'
              ? 'w-auto shrink-0'
              : 'w-full shrink-0 sm:w-56',
        )}
      >
        {operable ? (
          <div className={cn(runs.length > 0 && 'flex flex-wrap items-center gap-2 sm:justify-end')}>
            <ItemControl item={item} onChange={onChange} />
            {runs.map((operation) => (
              <RunButton key={operation.id} item={item} operation={operation} onChange={onChange} />
            ))}
          </div>
        ) : runs.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            {item.display ? (
              <span className="text-sm text-slate-500 dark:text-slate-400">{item.display}</span>
            ) : null}
            {runs.map((operation) => (
              <RunButton key={operation.id} item={item} operation={operation} onChange={onChange} />
            ))}
          </div>
        ) : valueShownInDetail ? null : (
          <p className="text-sm text-slate-600 sm:text-end dark:text-slate-300">
            {item.display ?? '—'}
          </p>
        )}
      </div>
    </div>
  );
}

/** One verb, as one button, under the word the contract gave it. */
function RunButton({
  item,
  operation,
  onChange,
}: {
  item: ManagedItem;
  operation: ManagedOperation;
  onChange: ResourceEditorProps['onChange'];
}) {
  return (
    <Button variant="secondary" onClick={() => onChange(item, true, operation.id)}>
      {operation.label}
    </Button>
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

  // A list is edited as a set, not as text, so it needs its own draft. Both
  // hooks run unconditionally — the branch comes after them.
  const chosen = useMemo(
    () => (Array.isArray(item.value) ? item.value.map(String) : []),
    [item.value],
  );
  const [members, setMembers] = useState<string[]>(chosen);
  const membersDirty =
    members.length !== chosen.length || members.some((value) => !chosen.includes(value));

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
    // The same switch the device cards use. It was a button reading "כבה" or
    // "הפעל", which states the *action* rather than the state, so a row of them
    // read as a column of instructions instead of a panel you can scan.
    return (
      <div className="flex sm:justify-end">
        <Switch on={on} label={item.label} onChange={(next) => onChange(item, next, operation)} />
      </div>
    );
  }

  if (item.kind === 'list') {
    // `constraints.allowed` is the documented home for a list's choices, and
    // `options` is where a bridge naturally puts them — the live Shabbat
    // bridge does. Reading only the first left every profile's device picker
    // with nothing to pick from.
    const allowed = item.constraints?.allowed?.length ? item.constraints.allowed : item.options;
    // Without a published list there is nothing safe to offer: the bridge has
    // not said what may go in, so this stays a reading.
    if (allowed.length === 0) {
      return (
        <p className="text-sm text-slate-600 sm:text-end dark:text-slate-300">
          {item.display ?? '—'}
        </p>
      );
    }
    return (
      <div className="space-y-2">
        {/*
          One chip per thing the bridge said may be in this list, labelled the
          way the household names it. This used to be a text box holding
          `kitchen,dining,led_salon`: to add a device you had to know its
          internal token, type it, and get the commas right — which is not a
          control, it is a form of trust in the person's memory.
        */}
        <div className="flex flex-wrap gap-1.5 sm:justify-end">
          {allowed.map((option) => {
            const selected = members.includes(option.value);
            return (
              <Chip
                key={option.value}
                selected={selected}
                onClick={() =>
                  setMembers((current) =>
                    selected
                      ? current.filter((value) => value !== option.value)
                      : [...current, option.value],
                  )
                }
              >
                {option.label}
              </Chip>
            );
          })}
        </div>
        <Button
          className={cn('w-full', !membersDirty && 'invisible')}
          onClick={() => onChange(item, members)}
          disabled={!membersDirty}
        >
          בדוק שינוי
        </Button>
      </div>
    );
  }

  if (item.kind === 'time') {
    // Its own control rather than `<input type="time">`, which renders
    // "11:30 PM" in a Hebrew household because the format follows the
    // browser's UI language and no page setting reaches it.
    return (
      <div className="space-y-2">
        <TimeField label={item.label} srOnlyLabel value={draft} onChange={setDraft} />
        <Button
          className={cn('w-full', !dirty && 'invisible')}
          onClick={() => onChange(item, draft)}
          disabled={!dirty}
        >
          בדוק שינוי
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
    const unit = (limits.unit ?? '').trim();
    // Said in words rather than as "0–99". Two numbers either side of a dash
    // are all neutral-or-LTR characters inside a right-to-left paragraph, so
    // the line resolves right-to-left and a range of nought to ninety-nine is
    // displayed as "99-0". Hebrew between the numbers fixes the order because
    // it fixes the reason for the order.
    parts.push(`מ־${limits.minimum} עד ${limits.maximum}${unit ? ` ${unit}` : ''}`);
  }
  if (limits.step) parts.push(`בקפיצות של ${limits.step}`);
  if (limits.max_length) parts.push(`עד ${limits.max_length} תווים`);
  return parts.length > 0 ? parts.join(' · ') : undefined;
}
