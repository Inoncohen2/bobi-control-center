import type { ReactNode } from 'react';
import { cn } from '@/utils/cn';
import type { HealthState, Severity } from '@/types/api';

type Tone = 'neutral' | 'ok' | 'warning' | 'error' | 'info' | 'muted';

const TONES: Record<Tone, string> = {
  neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  ok: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  warning: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  error: 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
  info: 'bg-bobi-50 text-bobi-700 dark:bg-bobi-500/15 dark:text-bobi-300',
  muted: 'bg-slate-100 text-slate-500 dark:bg-slate-700/60 dark:text-slate-400',
};

/**
 * A dot accompanies the colour so state is never conveyed by colour alone.
 */
export function Badge({
  children,
  tone = 'neutral',
  dot = false,
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
        TONES[tone],
        className,
      )}
    >
      {dot ? <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

export const severityTone: Record<Severity, Tone> = {
  ok: 'ok',
  warning: 'warning',
  error: 'error',
};

export const healthTone: Record<HealthState, Tone> = {
  online: 'ok',
  degraded: 'warning',
  offline: 'error',
  unknown: 'muted',
};
