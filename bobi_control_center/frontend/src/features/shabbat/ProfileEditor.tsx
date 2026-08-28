/**
 * One Shabbat profile, as a card you can actually work.
 *
 * The bridge publishes a profile as a flat list of items with dotted ids —
 * `profile.pre_on.devices`, `profile.pre_on.ac_salon` — and the generic editor
 * rendered them as exactly that: a control per row, one under another, with the
 * device list as a picker and each air conditioner as an unrelated number field
 * further down. Nothing on the screen said the temperature belonged to a device
 * that was in the profile, and nothing said which profile a row was part of.
 *
 * So this reassembles them:
 *
 * * **membership is a chip** — every device the bridge offers, on or off with
 *   one tap, which is the whole interaction for a light or a socket;
 * * **a device with more to say opens a sheet** — the chip carries a gear, the
 *   sheet holds its own membership switch and every extra control the bridge
 *   published *for this device in this profile*, and the chip then reads back
 *   what was chosen: "מזגן סלון · 24°".
 *
 * Which devices get a sheet is not a list kept here. It is worked out from the
 * items the bridge sent: a device with extra items has a sheet, a device
 * without has a chip. Today that means the three air conditioners, because
 * their temperature is the only per-device setting the Shabbat bridge
 * publishes. If it starts publishing a brightness for the LED or a speed for
 * the vacuum, those get sheets too, and none of this changes.
 */

import { useMemo, useState } from 'react';
import { Settings2 } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { Switch } from '@/components/ui/Switch';
import { ItemRow, isOperable } from '@/features/manage/ResourceEditor';
import { useRole } from '@/features/auth/useRole';
import { cn } from '@/utils/cn';
import type { ManagedItem, ManagedOption } from '@/types/api';

/** `profile.pre_on.ac_salon` → `{ profile: 'pre_on', part: 'ac_salon' }`. */
export function parseProfileId(id: string): { profile: string; part: string } | null {
  const match = /^profile\.([^.]+)\.(.+)$/.exec(id);
  if (!match?.[1] || !match[2]) return null;
  return { profile: match[1], part: match[2] };
}

export interface ProfileParts {
  /** The membership list — which devices this profile acts on. */
  devices: ManagedItem | null;
  /** Extra published settings, by the device token they belong to. */
  extras: Map<string, ManagedItem[]>;
}

/** Split one profile's items into its membership list and its per-device extras. */
export function splitProfile(items: ManagedItem[]): ProfileParts {
  let devices: ManagedItem | null = null;
  const extras = new Map<string, ManagedItem[]>();

  for (const item of items) {
    const parsed = parseProfileId(item.id);
    if (!parsed) continue;
    if (parsed.part === 'devices') {
      devices = item;
      continue;
    }
    // Anything else is named after the device it belongs to.
    extras.set(parsed.part, [...(extras.get(parsed.part) ?? []), item]);
  }

  return { devices, extras };
}

/**
 * What a device's extra settings currently say, in a few words.
 *
 * "24°" rather than "טמפרטורה: 24" — the chip already carries the device's
 * name, and a chip that repeats the label of every field it summarises stops
 * being a summary.
 */
function summarise(extras: ManagedItem[]): string | null {
  const parts = extras
    .map((item) => item.display ?? (item.value === null ? null : String(item.value)))
    .filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(' · ') : null;
}

function DeviceChip({
  option,
  selected,
  extras,
  disabled,
  onToggle,
  onOpen,
}: {
  option: ManagedOption;
  selected: boolean;
  extras: ManagedItem[];
  disabled: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const summary = selected ? summarise(extras) : null;
  const hasSheet = extras.length > 0;

  return (
    <button
      type="button"
      // The chip *is* the control for a simple device and the door to the sheet
      // for a complicated one. `aria-pressed` describes the first; a device
      // with a sheet gets `aria-haspopup` instead, because "pressed" would
      // describe a state this button no longer sets on its own.
      {...(hasSheet ? { 'aria-haspopup': 'dialog' as const } : { 'aria-pressed': selected })}
      disabled={disabled}
      onClick={hasSheet ? onOpen : onToggle}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',
        'focus-visible:outline-bobi-600 disabled:cursor-not-allowed disabled:opacity-40',
        selected
          ? 'bg-bobi-600 text-white'
          : 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
      )}
    >
      <span>{option.label}</span>
      {summary ? (
        <span className="tabular-nums opacity-80">· {summary}</span>
      ) : null}
      {hasSheet ? <Settings2 aria-hidden className="h-3.5 w-3.5 opacity-70" /> : null}
    </button>
  );
}

export function ProfileEditor({
  label,
  description,
  items,
  writesEnabled,
  onChange,
  timeControl,
}: {
  label: string;
  description?: string;
  items: ManagedItem[];
  writesEnabled: boolean;
  onChange: (item: ManagedItem, value: unknown, operation?: string) => void;
  /** The one timing row that governs when this profile runs, if there is one. */
  timeControl?: React.ReactNode;
}) {
  const { devices, extras } = useMemo(() => splitProfile(items), [items]);
  const { role } = useRole();
  const [openDevice, setOpenDevice] = useState<string | null>(null);

  const chosen = useMemo(
    () => (Array.isArray(devices?.value) ? devices.value.map(String) : []),
    [devices],
  );
  const [members, setMembers] = useState<string[]>(chosen);
  // The bridge is the truth: when a commit lands and a fresh snapshot arrives,
  // the staged set is whatever it now says, not what was staged against the
  // version before it.
  const [seen, setSeen] = useState<string[]>(chosen);
  if (seen !== chosen && seen.join() !== chosen.join()) {
    setSeen(chosen);
    setMembers(chosen);
  }

  const dirty = members.length !== chosen.length || members.some((m) => !chosen.includes(m));
  const options = devices?.constraints?.allowed?.length
    ? devices.constraints.allowed
    : (devices?.options ?? []);
  // The same question the generic rows ask, asked the same way. Writing it out
  // again here is how a chip came to be tappable for a session whose role the
  // backend would have refused — the padlock appeared on the row beside it and
  // not on the chips, because only one of them was asking.
  const operable = Boolean(devices && isOperable(devices, writesEnabled, role));

  const toggle = (token: string) =>
    setMembers((current) =>
      current.includes(token) ? current.filter((t) => t !== token) : [...current, token],
    );

  const openItem = openDevice ? (extras.get(openDevice) ?? []) : [];
  const openLabel = options.find((option) => option.value === openDevice)?.label ?? '';

  return (
    <Card as="li" className="flex flex-col gap-3">
      <div>
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">{label}</h3>
        {description ? (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{description}</p>
        ) : null}
      </div>

      {timeControl}

      {options.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          הגשר לא פרסם מכשירים לפרופיל הזה.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {options.map((option) => (
              <DeviceChip
                key={option.value}
                option={option}
                selected={members.includes(option.value)}
                extras={extras.get(option.value) ?? []}
                disabled={!operable}
                onToggle={() => toggle(option.value)}
                onOpen={() => setOpenDevice(option.value)}
              />
            ))}
          </div>

          {/* Named for what it changes. The time row above carries its own
              confirm button, and two buttons reading "בדוק שינוי" in one card
              is a card that does not say which change it is about to make. */}
          {devices && operable ? (
            <Button
              className={cn('w-full', !dirty && 'invisible')}
              onClick={() => onChange(devices, members)}
              disabled={!dirty}
            >
              בדוק שינוי במכשירים
            </Button>
          ) : null}
        </>
      )}

      <Modal
        open={openDevice !== null}
        onClose={() => setOpenDevice(null)}
        title={openLabel}
        description={`מה יקרה ל${openLabel} ב"${label}"`}
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
              נכלל בפרופיל
            </span>
            <Switch
              on={openDevice ? members.includes(openDevice) : false}
              label={`${openLabel} נכלל ב${label}`}
              disabled={!operable}
              onChange={() => openDevice && toggle(openDevice)}
            />
          </div>

          {openItem.length > 0 ? (
            <ul className="divide-y divide-slate-200 dark:divide-slate-700">
              {openItem.map((item) => (
                <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                  {/* The same row the rest of the app renders, so a control
                      here is the contract's, not this screen's idea of one. */}
                  <ItemRow item={item} onChange={onChange} writesEnabled={writesEnabled} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              לפרופיל הזה אין הגדרות נוספות למכשיר הזה — רק אם הוא נכלל בו.
            </p>
          )}
        </div>
      </Modal>
    </Card>
  );
}
