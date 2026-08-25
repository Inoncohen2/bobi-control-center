/**
 * The "מתקדם / פרטים טכניים" disclosure.
 *
 * This is the only sanctioned way to surface an `entity_id`, a `handler`, or any
 * other technical value. Collapsed by default, and never something the UI
 * branches on.
 */

import type { ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';

import { displayValue } from '@/utils/format';

export function AdvancedDisclosure({
  title = 'מתקדם',
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <details className="group mt-3 rounded-xl border border-slate-200 dark:border-slate-700">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200">
        <ChevronLeft
          aria-hidden="true"
          size={16}
          className="transition-transform group-open:-rotate-90"
        />
        {title}
      </summary>
      <div className="border-t border-slate-200 px-3 py-3 dark:border-slate-700">{children}</div>
    </details>
  );
}

export function TechnicalRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1 text-sm">
      <dt className="shrink-0 text-slate-500 dark:text-slate-400">{label}</dt>
      <dd
        dir="ltr"
        className="min-w-0 break-all text-left font-mono text-xs text-slate-700 dark:text-slate-300"
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Render a normalized object's technical fields.
 *
 * `known` names the fields to show with friendly labels. `extra` is the
 * backend's own map of fields the normalizer did not map explicitly — listed
 * under "שדות נוספים" so a growing bridge surfaces here rather than
 * disappearing.
 */
export function TechnicalDetails({
  source,
  known,
  extra,
}: {
  source: Record<string, unknown>;
  known: Array<[key: string, label: string]>;
  extra?: Record<string, unknown>;
}) {
  const extras = Object.entries(extra ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  );

  return (
    <dl className="divide-y divide-slate-100 dark:divide-slate-700/60">
      {known.map(([key, label]) => {
        const value = source[key];
        if (value === null || value === undefined || value === '') return null;
        return <TechnicalRow key={key} label={label} value={displayValue(value)} />;
      })}

      {extras.length > 0 ? (
        <div className="pt-2">
          <p className="mb-1 text-sm text-slate-500 dark:text-slate-400">שדות נוספים</p>
          <pre
            dir="ltr"
            className="overflow-x-auto rounded-lg bg-slate-50 p-2 text-left text-xs text-slate-700 dark:bg-slate-900/50 dark:text-slate-300"
          >
            {JSON.stringify(Object.fromEntries(extras), null, 2)}
          </pre>
        </div>
      ) : null}
    </dl>
  );
}
