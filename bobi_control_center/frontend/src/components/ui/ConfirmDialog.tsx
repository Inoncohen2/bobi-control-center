/**
 * The Confirm half of Preview → Confirm → Execute.
 *
 * It renders a `ChangePreview` that the *backend* produced, so what the user
 * approves is exactly what the server will act on.
 */

import { AlertTriangle } from 'lucide-react';
import type { ChangePreview } from '@/types/api';
import { Button } from './Button';
import { Modal } from './Modal';

interface ConfirmDialogProps {
  open: boolean;
  preview: ChangePreview | null;
  title: string;
  confirmLabel?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  preview,
  title,
  confirmLabel = 'אישור',
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!preview) return null;

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      description="זו תצוגה מקדימה. שום דבר לא נשמר עד שתאשרו."
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={loading}>
            ביטול
          </Button>
          <Button
            variant={preview.destructive ? 'danger' : 'primary'}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-base font-medium text-slate-900 dark:text-slate-100">{preview.summary}</p>

      {preview.lines.length > 0 ? (
        <ul className="mt-3 space-y-1 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
          {preview.lines.map((line, index) => (
            <li
              key={`${line.text}-${index}`}
              className={
                line.emphasis
                  ? 'text-sm font-semibold text-slate-900 dark:text-slate-100'
                  : 'text-sm text-slate-600 dark:text-slate-300'
              }
              style={{ whiteSpace: 'pre-wrap' }}
            >
              {line.text}
            </li>
          ))}
        </ul>
      ) : null}

      {preview.warnings.length > 0 ? (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="flex items-center gap-2 text-sm font-medium text-amber-900 dark:text-amber-200">
            <AlertTriangle aria-hidden="true" size={16} />
            שימו לב
          </p>
          <ul className="mt-1.5 list-inside list-disc space-y-1 text-sm text-amber-800 dark:text-amber-200/90">
            {preview.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
        בשלב זה השינוי נשמר בממשק הניהול בלבד ואינו משפיע על מערכת הבית.
      </p>
    </Modal>
  );
}
