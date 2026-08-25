/**
 * The one dialog every change goes through.
 *
 * It shows two clearly separated things, and never both at once:
 *
 * * **תצוגה מקדימה** — what *will* happen. Nothing has been done yet, and the
 *   dialog says so in as many words.
 * * **ביצוע** — the result, after the backend has applied the change and read
 *   it back.
 *
 * There is no path from opening this dialog to a change without pressing the
 * confirm button, and for a destructive change the button stays disabled until
 * the confirmation word is typed exactly.
 */

import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, HelpCircle, XCircle } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { TextField } from '@/components/ui/Field';
import { ApiError } from '@/api/client';
import type { ManagedChange } from './useManagedChange';

/** The three outcomes, each with its own words and its own icon. */
interface ResultTone {
  icon: typeof CheckCircle2;
  className: string;
}

const FAILED_TONE: ResultTone = { icon: XCircle, className: 'text-rose-600 dark:text-rose-400' };

const RESULT_TONES: Record<string, ResultTone> = {
  committed: { icon: CheckCircle2, className: 'text-emerald-600 dark:text-emerald-400' },
  committed_unverified: { icon: HelpCircle, className: 'text-amber-600 dark:text-amber-400' },
  failed: FAILED_TONE,
};

export function ChangeDialog({ change }: { change: ManagedChange }) {
  const { stage, preview, result, error } = change;
  const [word, setWord] = useState('');

  // A fresh preview starts a fresh confirmation.
  useEffect(() => {
    setWord('');
  }, [preview?.preview_id]);

  const open = stage !== 'idle' && (preview !== null || error !== null);
  if (!open) return null;

  const showingResult = stage === 'result' && result !== null;
  const destructive = preview?.destructive ?? false;
  const wordMatches = !destructive || word.trim() === (preview?.confirm_word ?? '');

  const title = showingResult ? 'ביצוע' : 'תצוגה מקדימה';

  return (
    <Modal
      open
      onClose={change.reset}
      title={title}
      description={showingResult ? undefined : 'עדיין לא בוצע דבר. אפשר לבטל.'}
      footer={
        showingResult ? (
          <Button onClick={change.reset}>סגירה</Button>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button
              variant={destructive ? 'danger' : 'primary'}
              loading={stage === 'committing'}
              disabled={!preview?.valid || !wordMatches}
              onClick={() => void change.commit(destructive ? word.trim() : undefined)}
            >
              {preview?.confirm_label ?? 'אישור'}
            </Button>
            <Button variant="secondary" onClick={change.reset}>
              ביטול
            </Button>
          </div>
        )
      }
    >
      {showingResult ? <ResultBody change={change} /> : <PreviewBody change={change} />}
      {error ? <ErrorNote error={error} /> : null}
      {destructive && !showingResult ? (
        <div className="mt-4">
          <TextField
            id="confirm-word"
            label={`להמשך יש להקליד "${preview?.confirm_word}"`}
            value={word}
            onChange={(event) => setWord(event.target.value)}
            autoComplete="off"
          />
        </div>
      ) : null}
    </Modal>
  );
}

function PreviewBody({ change }: { change: ManagedChange }) {
  const { preview, stage } = change;
  if (stage === 'previewing' || !preview) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">מכין תצוגה מקדימה…</p>;
  }

  return (
    <div className="space-y-4">
      <p className="font-semibold text-slate-900 dark:text-slate-100">{preview.title}</p>

      {preview.changes.length > 0 ? (
        <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-slate-700/60 dark:border-slate-700/60">
          {preview.changes.map((field) => (
            <div key={field.label} className="flex items-baseline justify-between gap-4 px-3 py-2">
              <dt className="text-sm text-slate-500 dark:text-slate-400">{field.label}</dt>
              <dd className="text-sm font-medium text-slate-900 dark:text-slate-100">
                {field.before !== field.after && field.before ? (
                  <>
                    <span className="text-slate-400 line-through dark:text-slate-500">
                      {field.before}
                    </span>{' '}
                    {field.after ? <span>{field.after}</span> : null}
                  </>
                ) : (
                  (field.after ?? field.before ?? '—')
                )}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {preview.explanation ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">{preview.explanation}</p>
      ) : null}

      {preview.errors.length > 0 ? (
        <ul className="space-y-1 rounded-xl bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-500/10 dark:text-rose-200">
          {preview.errors.map((item) => (
            <li key={`${item.field}-${item.code}`}>{item.message}</li>
          ))}
        </ul>
      ) : null}

      {preview.warning ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          <AlertTriangle aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
          <p>{preview.warning}</p>
        </div>
      ) : null}
    </div>
  );
}

function ResultBody({ change }: { change: ManagedChange }) {
  const result = change.result?.result;
  if (!result) return null;

  const tone = RESULT_TONES[result.status] ?? FAILED_TONE;
  const Icon = tone.icon;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className={tone.className}>
          <Icon size={20} />
        </span>
        <p className="font-semibold text-slate-900 dark:text-slate-100">{result.message}</p>
      </div>
      {result.verification.detail ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{result.verification.detail}</p>
      ) : null}
      {result.status === 'committed_unverified' ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          כדאי לרענן את המסך ולוודא שהשינוי נראה כמצופה.
        </p>
      ) : null}
    </div>
  );
}

function ErrorNote({ error }: { error: Error }) {
  const message =
    error instanceof ApiError ? error.message : 'משהו השתבש. אפשר לנסות שוב.';
  return (
    <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-500/10 dark:text-rose-200">
      {message}
    </p>
  );
}
