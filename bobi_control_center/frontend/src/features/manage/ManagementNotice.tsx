/**
 * The banner every manageable screen shows above its content.
 *
 * When Home Assistant has not declared a write bridge, this is the whole
 * explanation a household member gets — and the screen's editing controls are
 * simply not rendered, rather than rendered and disabled: a control that cannot
 * work is not a control.
 */

import { Info } from 'lucide-react';

import { ReadOnlyNotice } from '@/components/ui/ReadOnly';
import type { ManagementResource, ManagementStatus } from '@/types/api';
import { cn } from '@/utils/cn';

/** Find one resource's entry in the discovered contract. */
export function useResource(
  status: ManagementStatus | undefined,
  resource: string,
): ManagementResource | null {
  if (!status?.available) return null;
  return status.resources.find((item) => item.id === resource) ?? null;
}

export function ManagementNotice({
  status,
  resource,
  readOnlyText,
  className,
}: {
  status: ManagementStatus | undefined;
  resource: string;
  /** What the screen says while management is off. */
  readOnlyText: string;
  className?: string;
}) {
  // Still loading: say nothing rather than flash a "not enabled" message that
  // may be wrong a moment later.
  if (status === undefined) return null;

  const entry = status.available
    ? (status.resources.find((item) => item.id === resource) ?? null)
    : null;

  if (entry?.available) {
    return (
      <div
        className={cn(
          'flex items-start gap-2.5 rounded-2xl border border-bobi-200 bg-bobi-50 p-3.5 text-sm text-bobi-900 dark:border-bobi-500/30 dark:bg-bobi-500/10 dark:text-bobi-100',
          className,
        )}
      >
        <Info aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
        <p>כל שינוי יוצג קודם בתצוגה מקדימה, ויבוצע רק אחרי אישור.</p>
      </div>
    );
  }

  return (
    <ReadOnlyNotice className={className}>
      {entry?.detail ?? status.reason ?? 'ניהול עדיין לא הופעל ב-Home Assistant'}{' '}
      {readOnlyText}
    </ReadOnlyNotice>
  );
}
