/**
 * The four states every page must handle: loading, error, empty, normal.
 *
 * Centralising them here is what keeps the behaviour identical across pages and
 * guarantees a user never sees an HTTP status or a stack trace.
 */

import type { ReactNode } from 'react';
import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react';

import { ApiError, toDisplayError } from '@/api/client';
import { Button } from '@/components/ui/Button';

export function LoadingState({ label = 'טוען…' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 py-2">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((index) => (
        <div
          key={index}
          aria-hidden="true"
          className="h-24 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800"
        />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 px-6 py-12 text-center dark:border-slate-700">
      <span aria-hidden="true" className="mb-3 text-slate-400 dark:text-slate-500">
        {icon ?? <Inbox size={32} />}
      </span>
      <p className="text-base font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  fallbackMessage,
  onRetry,
}: {
  error: unknown;
  fallbackMessage: string;
  onRetry?: () => void;
}) {
  const apiError: ApiError = toDisplayError(error, fallbackMessage);

  return (
    <div
      role="alert"
      className="rounded-2xl border border-rose-200 bg-rose-50/70 p-5 dark:border-rose-500/30 dark:bg-rose-500/10"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle
          aria-hidden="true"
          size={20}
          className="mt-0.5 shrink-0 text-rose-600 dark:text-rose-400"
        />
        <div className="min-w-0 flex-1">
          {/* The user-facing message is Hebrew and never technical. */}
          <p className="font-medium text-rose-900 dark:text-rose-200">{apiError.message}</p>

          <details className="mt-3">
            <summary className="cursor-pointer text-sm text-rose-700 hover:underline dark:text-rose-300">
              פרטים טכניים
            </summary>
            <pre
              dir="ltr"
              className="mt-2 overflow-x-auto rounded-xl bg-white/70 p-3 text-left text-xs text-slate-700 dark:bg-slate-900/50 dark:text-slate-300"
            >
              {apiError.technical}
            </pre>
          </details>

          {onRetry ? (
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              icon={<RefreshCw size={14} />}
              onClick={onRetry}
            >
              לנסות שוב
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

interface QueryBoundaryProps<T> {
  isLoading: boolean;
  error: unknown;
  data: T | undefined;
  /** Hebrew message shown if the request failed. */
  errorMessage: string;
  /** Return true when `data` loaded fine but has nothing to show. */
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  onRetry?: () => void;
  children: (data: T) => ReactNode;
}

export function QueryBoundary<T>({
  isLoading,
  error,
  data,
  errorMessage,
  isEmpty,
  empty,
  onRetry,
  children,
}: QueryBoundaryProps<T>) {
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} fallbackMessage={errorMessage} onRetry={onRetry} />;
  if (data === undefined) {
    return <ErrorState error={null} fallbackMessage={errorMessage} onRetry={onRetry} />;
  }
  if (isEmpty?.(data) && empty) return <>{empty}</>;
  return <>{children(data)}</>;
}
