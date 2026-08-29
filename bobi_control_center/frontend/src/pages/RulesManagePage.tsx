/**
 * Bobi's smart rules.
 *
 * These are Bobi's own rules, not Home Assistant automations: nothing here
 * creates an `automation.*`, and the internal list Bobi stores them in is never
 * named or shown. Parsing and conflict detection stay on Bobi's side — when the
 * bridge reports a conflict this screen shows it, and when the bridge calls it
 * blocking the change is refused rather than argued with.
 *
 * Creating one is offered because the bridge declares it, and the bridge does
 * not write the rule itself — it hands the request to the engine that owns the
 * stored format, which runs its own duplicate and conflict checks first. A rule
 * is a standing instruction to Bobi, so this is rated high and asks for the
 * confirmation word typed. Rewriting an existing rule is still not offered.
 */

import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader } from '@/components/ui/Card';
import { SelectField, TextField } from '@/components/ui/Field';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

/**
 * Days as the bridge counts them: 0 is Monday, 6 is Sunday.
 *
 * That is Python's `weekday()`, which is what the rule engine stores, and it is
 * *not* what `Date.getDay()` returns — see `toBridgeDay`. The three-letter keys
 * are kept beside the numbers because older rules carry those instead, and a
 * screen that only understood one of the two would show a rule's days as raw
 * tokens half the time.
 */
const DAY_LABELS: Record<string, string> = {
  sun: 'א׳',
  mon: 'ב׳',
  tue: 'ג׳',
  wed: 'ד׳',
  thu: 'ה׳',
  fri: 'ו׳',
  sat: 'שבת',
  '0': 'ב׳',
  '1': 'ג׳',
  '2': 'ד׳',
  '3': 'ה׳',
  '4': 'ו׳',
  '5': 'שבת',
  '6': 'א׳',
};

/** The week, in the order a Hebrew speaker reads it, as the bridge numbers it. */
const WEEK: { value: number; label: string }[] = [
  { value: 6, label: 'א׳' },
  { value: 0, label: 'ב׳' },
  { value: 1, label: 'ג׳' },
  { value: 2, label: 'ד׳' },
  { value: 3, label: 'ה׳' },
  { value: 4, label: 'ו׳' },
  { value: 5, label: 'שבת' },
];

const TYPE_LABELS: Record<string, string> = {
  once: 'חד־פעמי',
  weekly: 'שבועי',
};

function RuleDetail({ item }: { item: ManagedItem }) {
  const days = Array.isArray(item.detail.days) ? (item.detail.days as unknown[]) : [];
  // `rule_type` is this application's name for it; the live bridge sends
  // `mode`. Reading only the first showed no type badge on any real rule.
  const type = String(item.detail.rule_type ?? item.detail.mode ?? '');
  const time = item.detail.time;
  const nextDue = item.detail.next_due ?? item.detail.due;
  const action = item.detail.action ?? item.detail.command;
  const conflicts = Array.isArray(item.detail.conflicts) ? item.detail.conflicts : [];

  return (
    <div className="mt-1.5 space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        {type ? <Badge tone="info">{TYPE_LABELS[type] ?? type}</Badge> : null}
        {days.map((day) => (
          <Badge key={String(day)} tone="neutral">
            {DAY_LABELS[String(day)] ?? String(day)}
          </Badge>
        ))}
        {typeof time === 'string' && time ? <Badge tone="neutral">{time}</Badge> : null}
        {typeof nextDue === 'string' && nextDue ? (
          <Badge tone="neutral">{nextDue.replace('T', ' ')}</Badge>
        ) : null}
      </div>
      {typeof action === 'string' && action ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">{action}</p>
      ) : null}
      {conflicts.length > 0 ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          בובי מצא חפיפה עם אוטומציה קיימת.
        </p>
      ) : null}
    </div>
  );
}

/** `Date.getDay()` (0 = Sunday) → the bridge's numbering (0 = Monday). */
function toBridgeDay(jsDay: number): number {
  return (jsDay + 6) % 7;
}

/**
 * The first moment this rule would run, as a local `YYYY-MM-DDTHH:MM:SS`.
 *
 * The engine refuses a rule whose `due` is not in the future, and for a weekly
 * rule the due it wants is the *next* occurrence — so the screen has to work it
 * out rather than send the time of day alone. Returns an empty string when the
 * form cannot yet name one, which is what keeps the button disabled.
 */
function firstRun(mode: string, date: string, time: string, days: number[]): string {
  if (!time) return '';
  if (mode === 'once') return date ? `${date}T${time}:00` : '';
  if (days.length === 0) return '';

  const [hourText, minuteText] = time.split(':');
  const hours = Number(hourText);
  const minutes = Number(minuteText);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return '';

  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  for (let ahead = 0; ahead <= 7; ahead += 1) {
    const candidate = new Date(now);
    candidate.setDate(now.getDate() + ahead);
    candidate.setHours(hours, minutes, 0, 0);
    if (candidate > now && days.includes(toBridgeDay(candidate.getDay()))) {
      return (
        `${candidate.getFullYear()}-${pad(candidate.getMonth() + 1)}-${pad(candidate.getDate())}` +
        `T${pad(candidate.getHours())}:${pad(candidate.getMinutes())}:00`
      );
    }
  }
  return '';
}

function NewRuleForm({ onCreate }: { onCreate: (payload: Record<string, unknown>) => void }) {
  const [name, setName] = useState('');
  const [command, setCommand] = useState('');
  const [mode, setMode] = useState('once');
  const [date, setDate] = useState('');
  const [time, setTime] = useState('');
  const [days, setDays] = useState<number[]>([]);
  const [until, setUntil] = useState('');

  const due = firstRun(mode, date, time, days);
  const complete = Boolean(name.trim() && command.trim() && due);

  return (
    <Card>
      <CardHeader
        title="אוטומציה חדשה"
        description="בובי יבצע את מה שתכתבו כאן, במועד שתבחרו."
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label="שם" value={name} onChange={(event) => setName(event.target.value)} />
        <SelectField
          label="סוג"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          options={[
            { value: 'once', label: 'חד־פעמי' },
            { value: 'weekly', label: 'שבועי' },
          ]}
        />
        <TextField
          label="מה בובי יעשה"
          value={command}
          onChange={(event) => setCommand(event.target.value)}
          help="במילים, כמו שהייתם מבקשים ממנו."
        />
        {mode === 'once' ? (
          <TextField
            label="תאריך"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        ) : (
          <TextField
            label="עד תאריך (לא חובה)"
            type="date"
            value={until}
            onChange={(event) => setUntil(event.target.value)}
          />
        )}
        <TextField
          label="שעה"
          type="time"
          value={time}
          onChange={(event) => setTime(event.target.value)}
        />
      </div>

      {mode === 'weekly' ? (
        <fieldset className="mt-3">
          <legend className="mb-1.5 text-xs text-slate-500 dark:text-slate-400">ימים</legend>
          <div className="flex flex-wrap gap-1.5">
            {WEEK.map((day) => {
              const chosen = days.includes(day.value);
              return (
                <button
                  key={day.value}
                  type="button"
                  aria-pressed={chosen}
                  onClick={() =>
                    setDays((current) =>
                      current.includes(day.value)
                        ? current.filter((value) => value !== day.value)
                        : [...current, day.value],
                    )
                  }
                  className={
                    chosen
                      ? 'rounded-lg bg-sky-600 px-3 py-1.5 text-sm text-white'
                      : 'rounded-lg bg-slate-100 px-3 py-1.5 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200'
                  }
                >
                  {day.label}
                </button>
              );
            })}
          </div>
        </fieldset>
      ) : null}

      <div className="mt-3 flex justify-end">
        <Button
          disabled={!complete}
          onClick={() => {
            onCreate({
              name: name.trim(),
              mode,
              command: command.trim(),
              due,
              ...(mode === 'weekly' ? { days, time, ...(until ? { until } : {}) } : {}),
            });
            setName('');
            setCommand('');
          }}
        >
          בדוק שינוי
        </Button>
      </div>
    </Card>
  );
}

export function RulesManagePage() {
  return (
    <ManagedResourcePage
      resource="rules"
      title="אוטומציות"
      description="הכללים החכמים של בובי."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            בדיקת ההתנגשויות נעשית אצל בובי. אם הוא אומר שהשינוי מתנגש — הוא לא יבוצע.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, requestNew, writesEnabled, operations }) => (
        <div className="space-y-4">
          {writesEnabled && operations.some((operation) => operation.id === 'create') ? (
            <NewRuleForm onCreate={(payload) => requestNew('create', payload)} />
          ) : null}
          <ResourceEditor
            snapshot={snapshot}
            onChange={request}
            writesEnabled={writesEnabled}
            renderDetail={(item) => <RuleDetail item={item} />}
            emptyLabel="אין אוטומציות."
          />
        </div>
      )}
    </ManagedResourcePage>
  );
}
