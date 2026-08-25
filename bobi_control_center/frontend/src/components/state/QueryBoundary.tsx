/**
 * The states every real-data screen must handle: loading, Home Assistant
 * disconnected, API error, empty, normal.
 *
 * Centralising them keeps behaviour identical across pages and guarantees a
 * user never sees a Python traceback or a raw HTTP status.
 */

import type { ReactNode } from 'react';
import { AlertTriangle, Inbox, PlugZap, RefreshCw } from 'lucide-react';

import { ApiError, toDisplayError } from '@/api/client';
import { Button } from '@/components/ui/Button';

export function LoadingState({ label = 'מתחבר ל-Bobi…' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 py-2">
      <span className="sr-only">{label}</span>
      <p aria-hidden="true" className="text-sm text-slate-400 dark:text-slate-500">
        {label}
      </p>
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

/**
 * A failure to reach Home Assistant is a different situation from a bug, and
 * gets its own wording and its own icon.
 */
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
  const disconnected = apiError.isDisconnected;

  const tone = disconnected
    ? 'border-amber-200 bg-amber-50/70 dark:border-amber-500/30 dark:bg-amber-500/10'
    : 'border-rose-200 bg-rose-50/70 dark:border-rose-500/30 dark:bg-rose-500/10';
  const iconTone = disconnected
    ? 'text-amber-600 dark:text-amber-400'
    : 'text-rose-600 dark:text-rose-400';
  const textTone = disconnected
    ? 'text-amber-900 dark:text-amber-200'
    : 'text-rose-900 dark:text-rose-200';

  return (
    <div role="alert" className={`rounded-2xl border p-5 ${tone}`}>
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className={`mt-0.5 shrink-0 ${iconTone}`}>
          {disconnected ? <PlugZap size={20} /> : <AlertTriangle size={20} />}
        </span>
        <div className="min-w-0 flex-1">
          <p className={`font-medium ${textTone}`}>
            {disconnected ? 'לא הצלחתי לקבל נתונים מ-Home Assistant' : apiError.message}
          </p>
          {disconnected ? (
            <p className={`mt-1 text-sm ${textTone} opacity-90`}>{apiError.message}</p>
          ) : null}

          <details className="mt-3">
            <summary className={`cursor-pointer text-sm ${textTone} opacity-80 hover:underline`}>
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
  loadingLabel?: string;
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
  loadingLabel,
  isEmpty,
  empty,
  onRetry,
  children,
}: QueryBoundaryProps<T>) {
  if (isLoading) return <LoadingState label={loadingLabel} />;
  if (error) return <ErrorState error={error} fallbackMessage={errorMessage} onRetry={onRetry} />;
  if (data === undefined) {
    return <ErrorState error={null} fallbackMessage={errorMessage} onRetry={onRetry} />;
  }
  if (isEmpty?.(data) && empty) return <>{empty}</>;
  return <>{children(data)}</>;
}
