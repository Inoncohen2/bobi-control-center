/**
 * The "מתקדם" disclosure.
 *
 * This is the only sanctioned way to surface Home Assistant identifiers to a
 * user: collapsed by default, and never something the UI branches on.
 */

import type { ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';
import type { Advanced as AdvancedData } from '@/types/api';

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

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1 text-sm">
      <dt className="shrink-0 text-slate-500 dark:text-slate-400">{label}</dt>
      <dd dir="ltr" className="min-w-0 break-all text-left font-mono text-xs text-slate-700 dark:text-slate-300">
        {value}
      </dd>
    </div>
  );
}

/** Renders an `advanced` block verbatim. Display only. */
export function AdvancedDetails({ advanced }: { advanced: AdvancedData }) {
  const hasRaw = Object.keys(advanced.raw ?? {}).length > 0;

  return (
    <dl className="divide-y divide-slate-100 dark:divide-slate-700/60">
      {advanced.entity_id ? <Row label="מזהה טכני" value={advanced.entity_id} /> : null}
      {advanced.object_id ? <Row label="מזהה פנימי" value={advanced.object_id} /> : null}
      {advanced.integration ? <Row label="אינטגרציה" value={advanced.integration} /> : null}
      {advanced.notes.length > 0 ? (
        <Row label="הערות" value={advanced.notes.join(' · ')} />
      ) : null}
      {hasRaw ? (
        <div className="pt-2">
          <p className="mb-1 text-sm text-slate-500 dark:text-slate-400">מאפיינים</p>
          <pre
            dir="ltr"
            className="overflow-x-auto rounded-lg bg-slate-50 p-2 text-left text-xs text-slate-700 dark:bg-slate-900/50 dark:text-slate-300"
          >
            {JSON.stringify(advanced.raw, null, 2)}
          </pre>
        </div>
      ) : null}
    </dl>
  );
}
