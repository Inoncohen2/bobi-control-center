/**
 * Read-only affordances for the Phase 2 catalogue rows.
 *
 * Every control that does not write is rendered through one of these, so the
 * reason it is inert is stated on screen rather than left for the user to
 * discover by clicking.
 *
 * The wording used to promise a later phase. That phase arrived: these screens
 * now carry a live "שליטה" section driven by the management contract, and a row
 * saying editing comes later while a working control sits on the same page is
 * worse than no label at all — it is the screen telling a person not to bother
 * scrolling. The label points at the real control instead.
 */

import type { ReactNode } from 'react';
import { Eye, Lock } from 'lucide-react';

import { cn } from '@/utils/cn';

/** Where the working control actually is, for a catalogue row that has none. */
export const NEXT_PHASE_LABEL = 'לעריכה: קטע "שליטה" בעמוד הזה';

/** A banner explaining that a whole screen is view-only. */
export function ReadOnlyNotice({
  children = 'הרשימה הזו מציגה נתונים. השינויים נעשים בקטע "שליטה" בעמוד.',
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex items-start gap-2.5 rounded-2xl border border-bobi-200 bg-bobi-50/70 p-3.5 text-sm',
        'text-bobi-900 dark:border-bobi-500/30 dark:bg-bobi-500/10 dark:text-bobi-200',
        className,
      )}
    >
      <Eye aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
      <p>{children}</p>
    </div>
  );
}

/** A small inline badge saying why a section has no controls, and where the
 *  working ones are. `reason` when this section's answer is not the default. */
export function NextPhaseBadge({ className, reason }: { className?: string; reason?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium',
        'text-slate-500 dark:bg-slate-700 dark:text-slate-400',
        className,
      )}
    >
      <Lock aria-hidden="true" size={10} />
      {reason ?? NEXT_PHASE_LABEL}
    </span>
  );
}

/**
 * A disabled control with an explanation.
 *
 * `disabled` plus `aria-disabled` and a title means the reason is available to
 * pointer, keyboard and screen-reader users alike.
 */
export function DisabledAction({
  children,
  reason = NEXT_PHASE_LABEL,
  className,
}: {
  children: ReactNode;
  reason?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      disabled
      aria-disabled="true"
      title={reason}
      aria-label={`${typeof children === 'string' ? children : 'פעולה'} — ${reason}`}
      className={cn(
        'inline-flex h-9 cursor-not-allowed items-center gap-1.5 rounded-xl bg-slate-100 px-3',
        'text-sm font-medium text-slate-400 dark:bg-slate-700/60 dark:text-slate-500',
        className,
      )}
    >
      <Lock aria-hidden="true" size={13} />
      {children}
    </button>
  );
}

/** Read-only rendering of a master toggle in a catalogue row. */
export function ReadOnlyToggle({
  on,
  label,
}: {
  on: boolean | null | undefined;
  label: string;
}) {
  const isOn = on === true;
  return (
    <span
      role="img"
      aria-label={`${label}: ${isOn ? 'מופעל' : 'כבוי'} (לקריאה בלבד)`}
      title={NEXT_PHASE_LABEL}
      className={cn(
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full opacity-70',
        isOn ? 'bg-bobi-500' : 'bg-slate-300 dark:bg-slate-600',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'absolute right-0.5 h-5 w-5 rounded-full bg-white shadow',
          isOn ? '-translate-x-5' : 'translate-x-0',
        )}
      />
    </span>
  );
}
